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

    def formatted_source(self):
        from docx.oxml import OxmlElement
        from docx.oxml.ns import qn
        source = self.root / "formatted.docx"
        doc = Document()
        p = doc.add_paragraph("Smith ")
        p.add_run("et al.").italic = True
        p.add_run(" found that teams ")
        for tag, attrs in (("w:proofErr", {"w:type": "spellStart"}),
                           ("w:bookmarkStart", {"w:id": "0", "w:name": "b"}),
                           ("w:bookmarkEnd", {"w:id": "0"})):
            marker = OxmlElement(tag)
            for name, value in attrs.items():
                marker.set(qn(name), value)
            p._p.append(marker)
        p.add_run("may leave.")
        q = doc.add_paragraph("Before the tab.")
        q.add_run().add_tab()
        q.add_run("After the tab.")
        doc.save(source)
        return source

    def test_formatted_runs_form_one_unit(self):
        source = self.formatted_source()
        job = self.root / "job"
        call("manuscript", "prepare", source, job, "--blocks", "all")
        # Formatting changes and Word's zero-width markers stay inside one unit;
        # a tab is a protected element and still separates units.
        self.assertEqual(read(job / "original.json"), {
            "P001": "Smith et al. found that teams may leave.",
            "P002": "Before the tab.",
            "P003": "After the tab."})
        write(job / "final.json", {"P001": "Smith et al. reported that both teams may depart.",
                                   "P002": "Before the tab.", "P003": "After the tab."})
        output = self.root / "revised.docx"
        proc = call("manuscript", "merge", source, job, output)
        self.assertNotIn("formatted run", proc.stdout)
        paragraph = Document(output).paragraphs[0]
        self.assertEqual(paragraph.text, "Smith et al. reported that both teams may depart.")
        self.assertEqual([r.text for r in paragraph.runs if r.italic], ["et al."])
        self.assertIn("w:proofErr", ZipFile(output).read("word/document.xml").decode())

    def test_changed_formatted_run_is_reported(self):
        source = self.formatted_source()
        job = self.root / "job"
        call("manuscript", "prepare", source, job, "--blocks", "B001")
        write(job / "final.json", {"P001": "Smith and colleagues found that teams may leave."})
        output = self.root / "revised.docx"
        proc = call("manuscript", "merge", source, job, output)
        self.assertIn("P001: formatted run 'et al.'", proc.stdout)
        paragraph = Document(output).paragraphs[0]
        self.assertEqual(paragraph.text, "Smith and colleagues found that teams may leave.")

    def test_distribution_keeps_unchanged_words_in_their_runs(self):
        import manuscript
        pieces = [manuscript.Piece("The ", key=b""), manuscript.Piece("in vitro", key=b"i"),
                  manuscript.Piece(" assay was run twice.", key=b"")]
        self.assertEqual(manuscript.distribute(pieces, "The in vitro assay was repeated three times."),
                         ["The ", "in vitro", " assay was repeated three times."])
        self.assertEqual(manuscript.distribute(pieces, "In this study, the in vitro assay was run twice."),
                         ["In this study, the ", "in vitro", " assay was run twice."])

    def test_highlights_survive_pdf_only_text_and_tables(self):
        source = self.root / "submitted.docx"
        doc = Document()
        doc.add_paragraph("Teams may leave early in the season.", style="List Number")
        doc.add_paragraph("The example shows a clear pattern in the data.")
        cells = doc.add_table(rows=1, cols=2).rows[0].cells
        cells[0].text, cells[1].text = "Alpha group", "Beta group"
        doc.add_paragraph("The second sentence stays.")
        doc.save(source)
        pdf = self.root / "report.pdf"
        page = Canvas(str(pdf), pagesize=(500, 700))
        page.setFont("Helvetica", 12)
        def draw(x, y, text, mark=False):
            width = stringWidth(text, "Helvetica", 12)
            if mark:
                page.setFillColorRGB(0, .5, 1)
                page.rect(x, y - 2, width, 14, stroke=0, fill=1)
                page.setFillColorRGB(0, 0, 0)
            page.drawString(x, y, text)
            return x + width
        # Word numbering, the hyphen at a line break, the note marker and the footnote
        # appear only in the PDF; the table row is read across both cells.
        draw(50, 640, "1. Teams may leave early in the season.")
        draw(draw(50, 610, "The "), 610, "exam-", mark=True)
        x = draw(50, 595, "ple shows", mark=True)
        x = draw(draw(x, 595, " a clear pattern in the data."), 599, "1")
        draw(draw(50, 565, "Alpha group "), 565, "Beta group", mark=True)
        draw(50, 535, "The second sentence stays.")
        draw(50, 80, "1 Survey archive, 2020.", mark=True)
        page.save()
        job = self.root / "job"
        job.mkdir()
        proc = call("highlights", "extract", pdf, source, job / "scope.json", "--pages", 1, 1,
                    "--y", 10, 680, "--rgb", 0, .5, 1)
        scope = read(job / "scope.json")
        self.assertEqual([s["text"] for s in scope["spans"]], ["example shows", "Beta group"])
        self.assertEqual(scope["unplaced"], [{"page": 1, "text": "1Surveyarchive,2020."}])
        self.assertIn("Unplaced highlight on page 1", proc.stdout)
        final = {"P001": "example reveals", "P002": "Beta cohort"}
        write(job / "final.json", final)
        output = self.root / "revised.docx"
        call("highlights", "merge", source, job / "scope.json", job / "final.json", output)
        revised = Document(output)
        self.assertEqual(revised.paragraphs[1].text, "The example reveals a clear pattern in the data.")
        self.assertEqual(revised.tables[0].rows[0].cells[1].text, "Beta cohort")
        self.assertEqual(revised.paragraphs[0].text, "Teams may leave early in the season.")

    def test_highlights_reject_a_different_document(self):
        source = self.root / "submitted.docx"
        doc = Document()
        doc.add_paragraph("An entirely different manuscript about rivers and their floodplains.")
        doc.save(source)
        pdf = self.root / "report.pdf"
        page = Canvas(str(pdf), pagesize=(500, 700))
        page.setFillColorRGB(0, .5, 1)
        page.rect(50, 598, 100, 15, stroke=0, fill=1)
        page.setFillColorRGB(0, 0, 0)
        page.setFont("Helvetica", 12)
        page.drawString(50, 600, "Two teams may leave the league next season.")
        page.save()
        proc = call("highlights", "extract", pdf, source, self.root / "scope.json", "--pages", 1, 1,
                    "--y", 10, 680, "--rgb", 0, .5, 1, ok=False)
        self.assertIn("reproduce only", proc.stderr)
        self.assertFalse((self.root / "scope.json").exists())

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
