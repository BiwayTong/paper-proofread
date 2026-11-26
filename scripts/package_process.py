"""Verify the three translation rounds and export a readable revision archive."""
import argparse
import html
import json
import os
from pathlib import Path
import tempfile
from zipfile import ZipFile, ZIP_DEFLATED
from rounds import read_texts, selection, verify_record


def export(job, destination):
    original = read_texts(job / "original.json")
    if original != selection(job):
        raise ValueError("The original text differs from the selected text")
    service = json.loads((job / "service.json").read_text(encoding="utf-8"))["provider"]
    label = {"apple": "苹果翻译", "google": "Google 翻译"}[service]
    def draft(name):
        values = read_texts(job / (name + ".json"))
        if values.keys() != original.keys():
            raise ValueError(f"IDs changed in {name}")
        return values
    baseline = draft("baseline")
    current = baseline
    with tempfile.TemporaryDirectory(dir=destination.parent) as tmp:
        out = Path(tmp)/"process.zip"
        with ZipFile(out, "w", ZIP_DEFLATED) as archive:
            for name in ("scope.json", "original.json", "baseline.json", "service.json", "review.md"):
                archive.write(job/name, name)
            spans = json.loads((job / "scope.json").read_text(encoding="utf-8"))["spans"]
            if isinstance(spans, list):
                lines = ["# 选中的原文"]
                for span in spans:
                    pages = ", ".join(str(p) for p in span.get("pages", []))
                    location = f" · PDF 页 {pages}" if pages else ""
                    lines.extend([f"## {span['id']}{location}", span["text"]])
                archive.writestr("highlights.md", "\n\n".join(lines) + "\n")
            for n in (1, 2, 3):
                sections = []
                for direction, raw_title, edit_title in (
                        ("zh", label + "中文原文", "中文调整稿"),
                        ("en", label + "英文回译原文", "本轮英文稿")):
                    tag = f"r{n}-{direction}"
                    raw = draft(tag+"-raw")
                    for ident in original:
                        rec_file = job/".records"/tag/(ident+".json")
                        rec = json.loads(rec_file.read_text(encoding="utf-8"))
                        if not verify_record(rec, current[ident], direction, service) or rec["output"] != raw[ident]:
                            raise ValueError(f"Translation record differs: {tag}/{ident}")
                        archive.write(rec_file, f"records/{tag}/{ident}.json")
                    current = draft(tag+"-edit")
                    for suffix in ("raw", "edit"):
                        filename = f"{tag}-{suffix}.json"
                        archive.write(job/filename, filename)
                    sections.extend([(raw_title, raw), (edit_title, current)])
                lines = [f"# 第 {n} 轮"]
                for ident in original:
                    lines.append("## "+ident)
                    for title, values in sections:
                        lines.extend(["### "+title, values[ident]])
                archive.writestr(f"round-{n}.md", "\n\n".join(lines)+"\n")
            draft("check")
            final = draft("final")
            for name in ("check.json", "final.json"):
                archive.write(job/name, name)
            final_zh = draft("r3-zh-edit")
            lines = ["# 段落对照", "", "| 编号 | 英文基准稿 | 第三轮中文调整稿 | 最终英文稿 |",
                     "| --- | --- | --- | --- |"]
            for ident in original:
                cells = (ident, baseline[ident], final_zh[ident], final[ident])
                escaped = [html.escape(cell).replace("|", "&#124;").replace("\n", "<br>") for cell in cells]
                lines.append("| " + " | ".join(escaped) + " |")
            archive.writestr("comparison.md","\n".join(lines)+"\n")
        with ZipFile(out) as archive:
            if archive.testzip():
                raise ValueError("Invalid process ZIP")
        os.link(out,destination)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("job", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    try:
        export(args.job,args.output)
    except (OSError, ValueError, KeyError) as exc:
        parser.exit(1,f"{exc}\n")
