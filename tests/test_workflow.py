"""Integration checks with synthetic manuscripts and offline translation fixtures."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from zipfile import ZipFile

from docx import Document
from reportlab.pdfgen.canvas import Canvas
from reportlab.pdfbase.pdfmetrics import stringWidth

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import rounds
from rounds import WEB_PROVIDER, APPLE_MANUAL


def call(script, *args, ok=True):
    proc = subprocess.run([sys.executable, str(SCRIPTS / (script + ".py")), *map(str, args)],
                          text=True, capture_output=True)
    if (proc.returncode == 0) != ok:
        raise AssertionError(f"{proc.args} exited {proc.returncode}: {proc.stderr}")
    return proc


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


class WorkflowTest(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)

    def exercise(self, service, highlights):
        folder = self.root / (service + ("-blue" if highlights else "-whole"))
        folder.mkdir()
        job = folder / "job"
        selected = "Two teams may leave."
        outside = "The second sentence stays."
        if highlights:
            source = folder / "source.docx"
            doc = Document()
            doc.add_paragraph(selected + " " + outside)
            doc.save(source)
            pdf = folder / "report.pdf"
            page = Canvas(str(pdf), pagesize=(500, 700))
            page.setFillColorRGB(0, .5, 1)
            page.rect(50, 598, stringWidth(selected, "Helvetica", 12), 15, stroke=0, fill=1)
            page.setFillColorRGB(0, 0, 0)
            page.setFont("Helvetica", 12)
            page.drawString(50, 600, selected + " " + outside)
            page.save()
            job.mkdir()
            call("highlights", "extract", pdf, source, job / "scope.json", "--pages", 1, 1,
                 "--y", 10, 680, "--rgb", 0, .5, 1)
            self.assertEqual(read(job / "scope.json")["spans"][0]["text"], selected)
        else:
            source = folder / "source.txt"
            source.write_bytes((selected + "\r\n\r\n " + outside + "\r\n").encode())
            call("manuscript", "prepare", source, job, "--blocks", "B001")
        original_bytes = source.read_bytes()
        expected = {"P001": selected}
        write(job / "baseline.json", expected)
        for n in (1, 2, 3):
            for direction in ("zh", "en"):
                form = folder / f"{n}-{direction}.json"
                cmd = ["rounds", job, n, direction, "--provider", service]
                call(*cmd, "--export-form", form)
                table = read(form)
                row = table["paragraphs"]["P001"]
                self.assertEqual(row["source"], expected["P001"])
                row["translation"] = f" offline fixture {n}/{direction} "
                write(form, table)
                call(*cmd, "--import-form", form)
                stage = f"r{n}-{direction}"
                self.assertEqual(read(job / (stage + "-raw.json"))["P001"], row["translation"])
                expected = {"P001": f"Reviewed {n}/{direction}."}
                write(job / (stage + "-edit.json"), expected)
        other = "google" if service == "apple" else "apple"
        call("rounds", job, 3, "en", "--provider", other, "--export-form", folder / "mixed.json", ok=False)
        call("rounds", job, 4, "zh", "--provider", service, "--export-form", folder / "fourth.json", ok=False)
        final = {"P001": "Two teams may depart."}
        write(job / "check.json", final)
        write(job / "final.json", final)
        (job / "review.md").write_text("Offline fixture.")
        output = folder / ("revised" + source.suffix)
        if highlights:
            call("highlights", "merge", source, job / "scope.json", job / "final.json", output)
            self.assertEqual(Document(output).paragraphs[0].text, final["P001"] + " " + outside)
        else:
            call("manuscript", "merge", source, job, output)
            self.assertEqual(output.read_bytes(), original_bytes.replace(selected.encode(), final["P001"].encode()))
        self.assertEqual(original_bytes, source.read_bytes())
        archive = folder / "process.zip"
        call("package_process", job, archive)
        with ZipFile(archive) as bundle:
            self.assertIsNone(bundle.testzip())
            self.assertEqual("highlights.md" in bundle.namelist(), highlights)
            self.assertEqual(len([f for f in bundle.namelist() if f.startswith("records/")]), 6)
            self.assertEqual(len([f for f in bundle.namelist() if f.startswith("r") and
                                  f.endswith(("-raw.json", "-edit.json"))]), 12)
            record = json.loads(bundle.read("records/r3-en/P001.json"))
            self.assertEqual(record["provider"], WEB_PROVIDER if service == "google" else APPLE_MANUAL)
            self.assertIn(final["P001"], bundle.read("comparison.md").decode())
        write(job / "r1-en-edit.json", {"P001": "Different input."})
        call("package_process", job, folder / "tampered.zip", ok=False)
        self.assertFalse((folder / "tampered.zip").exists())

    def test_routing(self):
        for service in ("apple", "google"):
            for highlights in (False, True):
                with self.subTest(service=service, highlights=highlights):
                    self.exercise(service, highlights)

    def test_automatic_channels_preserve_raw_output(self):
        sample = {"P001": "Two teams may leave."}
        for service in ("apple", "google"):
            job = self.root / service
            job.mkdir()
            write(job / "scope.json", {"spans": [{"id": "P001", "text": sample["P001"]}]})
            write(job / "baseline.json", sample)
            args = SimpleNamespace(job=job, round=1, to="zh", provider=service,
                                   shortcut="Fixture EN-ZH" if service == "apple" else None,
                                   cloud=service == "google", export_form=None, import_form=None)
            raw = "  测试译文。\n"
            with patch.object(rounds, "apple_translate", return_value=raw) as apple, \
                 patch.object(rounds, "GoogleTranslator") as google:
                google.return_value.translate.return_value = raw
                rounds.run(args)
                rounds.run(args)
                if service == "apple":
                    apple.assert_called_once_with(sample["P001"], args.shortcut)
                    google.assert_not_called()
                else:
                    google.return_value.translate.assert_called_once_with(sample["P001"], "zh")
                    apple.assert_not_called()
            self.assertEqual(read(job / "r1-zh-raw.json")["P001"], raw)
            record = read(job / ".records" / "r1-zh" / "P001.json")
            self.assertEqual(record["provider"], rounds.APPLE_SHORTCUT if service == "apple" else rounds.API_PROVIDER)


if __name__ == "__main__":
    unittest.main()
