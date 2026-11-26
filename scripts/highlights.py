"""Map coloured PDF rectangles to Word character ranges and merge reviewed replacements."""
import argparse
import copy
import hashlib
import json
import shutil
import tempfile
import unicodedata
from collections import Counter, defaultdict
from difflib import SequenceMatcher
from pathlib import Path
from zipfile import ZipFile

from lxml import etree as ET
from fileops import publish_file
from manuscript import Piece, SPACE, distribute

NS = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
PART = "word/document.xml"
W = "{%s}" % NS["w"]
ANCHOR = 8       # characters a match needs before it is trusted on its own
SLACK = 3000     # Word characters searched beyond each PDF page
MIN_MATCHED = .9  # share of the Word body the PDF pages must reproduce


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def normal(text):
    # Soft hyphens are invisible in Word unless a line breaks there.
    return "".join(c for c in unicodedata.normalize("NFKC", text) if not c.isspace() and c != "\u00ad")


def paragraphs(root):
    """Body paragraphs in reading order, table cells included, text boxes excluded."""
    body = root.find(W+"body")
    return [p for p in body.iter(W+"p") if not any(a.tag == W+"p" for a in p.iterancestors())]


def text_nodes(paragraph):
    return [n for n in paragraph.iter(W+"t") if next(n.iterancestors(W+"p")) is paragraph]


def field_results(root):
    """Text nodes shown as the result of a complex field such as a citation."""
    fields, depth = set(), 0
    for n in root.iter():
        if n.tag == W+"fldChar":
            kind = n.get(W+"fldCharType")
            depth += int(kind == "begin") - int(kind == "end")
        if depth and n.tag == W+"t":
            fields.add(n)
    return fields


def run_key(node):
    run = node.getparent()
    props = run.find(W+"rPr") if run is not None and run.tag == W+"r" else None
    return ET.tostring(props, method="c14n") if props is not None else b""


def runs(items, key):
    """Group consecutive items that share key(item) into lists."""
    out = []
    for item in items:
        if out and key(out[-1][-1], item):
            out[-1].append(item)
        else:
            out.append([item])
    return out


def align(page_chars, word, pos):
    """Map page characters to Word offsets at or after pos.

    Text only the PDF shows (list numbers, footnotes, note markers, line-end hyphens)
    and text only Word holds stay unmatched. A short match counts only when it
    continues the Word text of the previous trusted match, so stray letters inside a
    footnote or a reflowed table are never anchored.
    """
    window = word[pos:pos + len(page_chars) + SLACK]
    blocks = SequenceMatcher(None, page_chars, window, autojunk=False).get_matching_blocks()
    mapping, end = {}, None
    for a, b, size in blocks:
        if not size or (size < ANCHOR and b != end):
            continue
        for k in range(size):
            mapping[a + k] = pos + b + k
        end = b + size
    return mapping


def inspect(args):
    import pdfplumber
    with pdfplumber.open(args.pdf) as pdf:
        for p in pdf.pages:
            colors = Counter(str(r["non_stroking_color"]) for r in p.rects if r["fill"])
            print(f"p{p.page_number} {p.width:.1f} × {p.height:.1f}, rects {dict(colors)}, annotations {len(p.annots)}")


def extract(args):
    import pdfplumber
    with ZipFile(args.word) as doc:
        root = ET.fromstring(doc.read(PART))
    texts = ["".join(t.text or "" for t in text_nodes(p)) for p in paragraphs(root)]
    chars, offsets = [], []
    for pi, text in enumerate(texts):
        for index, c in enumerate(text):
            for letter in normal(c):
                chars.append(letter)
                offsets.append((pi, index))
    full = "".join(chars)
    pos = 0
    matched = set()
    selected = defaultdict(set)
    unplaced = []
    with pdfplumber.open(args.pdf) as pdf:
        first, last = args.pages
        require(1 <= first <= last <= len(pdf.pages), "Invalid PDF page range")
        top, bottom = args.y
        for page in pdf.pages[first - 1:last]:
            require(0 <= top < bottom <= page.height, "Invalid body crop for this PDF page")
            body = page.crop((0, top, page.width, bottom))
            rects = [r for r in body.rects if r["fill"] and isinstance(r["non_stroking_color"], (tuple, list))
                     and len(r["non_stroking_color"]) == 3
                     and max(abs(a-b) for a, b in zip(r["non_stroking_color"], args.rgb)) <= .002]
            used = set()
            glyphs = []  # (normalized letter, line number, highlighted)
            for ln, line in enumerate(body.extract_text_lines(return_chars=True)):
                for glyph in line["chars"]:
                    x = (glyph["x0"] + glyph["x1"]) / 2
                    y = (glyph["top"] + glyph["bottom"]) / 2
                    hits = {n for n, rect in enumerate(rects)
                            if rect["x0"] <= x <= rect["x1"] and rect["top"] <= y <= rect["bottom"]}
                    used |= hits
                    for letter in normal(glyph["text"]):
                        glyphs.append((letter, ln, bool(hits)))
            require(len(used) == len(rects), f"Selected colour includes a rectangle without mapped text on page {page.page_number}")
            mapping = align("".join(g[0] for g in glyphs), full, pos)
            if mapping:
                pos = max(mapping.values()) + 1
            matched.update(mapping.values())
            for i, (_, _, hit) in enumerate(glyphs):
                if hit and i in mapping:
                    selected[offsets[mapping[i]]].add(page.page_number)
            loose = [i for i, g in enumerate(glyphs) if g[2] and i not in mapping]
            for group in runs(loose, lambda a, b: b == a + 1):
                text = ""
                for i in group:
                    if text and glyphs[i][1] != glyphs[i-1][1]:
                        text += " "
                    text += glyphs[i][0]
                # A lone line-end hyphen or stray mark carries no editable wording.
                if any(c.isalnum() for c in text):
                    unplaced.append(dict(page=page.page_number, text=text))
    require(selected or unplaced, "No text under the chosen colour; inspect the PDF marking type and layout")
    share = len(matched) / max(len(full), 1)
    require(share >= MIN_MATCHED, f"The PDF pages reproduce only {share:.0%} of the Word body; "
            "check the page range, body crop and that both files are the submitted version")
    missing = [i for i in range(len(full)) if i not in matched]
    word_only = []
    for group in runs(missing, lambda a, b: b == a + 1 and offsets[a][0] == offsets[b][0]):
        pi = offsets[group[0]][0]
        a, b = offsets[group[0]][1], offsets[group[-1]][1] + 1
        word_only.append(dict(paragraph=pi, start=a, end=b, text=texts[pi][a:b]))
    spans = []
    for (pi, index), pages in sorted(selected.items()):
        prev = spans[-1] if spans else None
        if prev and pi == prev["paragraph"] and not texts[pi][prev["end"]:index].strip():
            prev["end"] = index + 1
            prev["pages"].update(pages)
        else:
            spans.append(dict(id=f"P{len(spans)+1:03d}", paragraph=pi, start=index, end=index+1, pages=set(pages)))
    for h in spans:
        h["text"] = texts[h["paragraph"]][h["start"]:h["end"]]
        h["pages"] = sorted(h["pages"])
    manifest = dict(word_sha256=sha(args.word), pdf_sha256=sha(args.pdf), spans=spans,
                    unplaced=unplaced, word_only=word_only)
    with args.output.open("x", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    print(f"{len(spans)} spans; {share:.1%} of the Word body matched")
    for item in unplaced:
        print(f"Unplaced highlight on page {item['page']}: {item['text'][:65]!r}; locate it manually")
    if word_only:
        print(f"{len(word_only)} Word passages not found in the PDF are listed under word_only; "
              "review them if a highlight sits near them")


def merge(args):
    scope = json.loads(args.scope.read_text(encoding="utf-8"))
    replacements = json.loads(args.edits.read_text(encoding="utf-8"))
    require(sha(args.word) == scope["word_sha256"], "Base Word file changed; locate the matching version")
    spans = scope["spans"]
    ids = [s["id"] for s in spans]
    require(ids and len(set(ids)) == len(ids) and set(ids) == set(replacements), "Replacement IDs differ from scope")
    with ZipFile(args.word) as doc:
        root = ET.fromstring(doc.read(PART))
        ps = paragraphs(root)
        fields = field_results(root)
        previous = None
        changed = 0
        # Reverse order keeps earlier offsets stable when replacement lengths change.
        for s in sorted(spans, key=lambda h: (h["paragraph"], h["start"]), reverse=True):
            pi, a, b = s["paragraph"], s["start"], s["end"]
            require(0 <= pi < len(ps) and 0 <= a < b, "Invalid span offsets")
            require(previous is None or pi != previous[0] or b <= previous[1], "Overlapping spans")
            previous = (pi, a)
            val = replacements[s["id"]]
            require(isinstance(val, str) and val.strip() and not any(c in val for c in "\r\n\t"), "Expected single-paragraph replacement")
            nodes = text_nodes(ps[pi])
            before = "".join(n.text or "" for n in nodes)
            require(before[a:b] == s["text"] and b <= len(before), f"Original span differs at {s['id']}")
            if val == s["text"]:
                continue
            # Only the text the span touches must be plain run text; citation fields,
            # links and tracked changes elsewhere in the paragraph stay untouched.
            touched, cursor = [], 0
            for node in nodes:
                t = node.text or ""
                lo, hi = max(a, cursor), min(b, cursor + len(t))
                if lo < hi:
                    touched.append((node, lo - cursor, hi - cursor))
                cursor += len(t)
            for node, _, _ in touched:
                require(node not in fields and not node.xpath(
                    "ancestor::w:fldSimple | ancestor::w:hyperlink | ancestor::w:ins | ancestor::w:moveTo"
                    " | ancestor::w:sdt", namespaces=NS),
                    f"{s['id']} overlaps a field, link, tracked change or content control; edit it manually")
            if len(touched) == 1:
                node, lo, hi = touched[0]
                node.text = node.text[:lo] + val + node.text[hi:]
            else:
                pieces = [Piece(node.text[lo:hi], key=run_key(node)) for node, lo, hi in touched]
                parts = distribute(pieces, val)
                for (node, lo, hi), piece, part in zip(touched, pieces, parts):
                    node.text = node.text[:lo] + part + node.text[hi:]
                    if node.text != node.text.strip():
                        node.set(SPACE, "preserve")
                weight = Counter()
                for piece in pieces:
                    weight[piece.key] += len(piece.text.strip())
                base = weight.most_common(1)[0][0]
                for piece, part in zip(pieces, parts):
                    if piece.key != base and part.strip() != piece.text.strip():
                        print(f"{s['id']}: formatted run {piece.text.strip()!r} now reads {part.strip()!r}; check its formatting")
            require("".join(n.text or "" for n in nodes) == before[:a]+val+before[b:], "Unexpected paragraph edit")
            changed += 1
        with tempfile.TemporaryDirectory(dir=args.output.parent) as tmp:
            staged = Path(tmp)/"verified.docx"
            if changed:
                payload = ET.tostring(root, encoding="UTF-8", xml_declaration=True, standalone=True)
                with ZipFile(staged, "w") as out:
                    for entry in doc.infolist():
                        out.writestr(copy.copy(entry), payload if entry.filename == PART else doc.read(entry))
                with ZipFile(staged) as check:
                    require(check.testzip() is None and check.namelist() == doc.namelist(), "Invalid output archive")
                    for name in doc.namelist():
                        require(check.read(name) == (payload if name == PART else doc.read(name)), f"Unexpected change in {name}")
            else:
                shutil.copyfile(args.word, staged)
                require(sha(staged) == scope["word_sha256"], "Base Word file changed")
                with ZipFile(staged) as check:
                    require(check.testzip() is None, "Invalid output archive")
            publish_file(staged, args.output)  # publish only after validation; existing files are never overwritten
    print(f"{changed} of {len(spans)} verified spans changed")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    show = sub.add_parser("inspect", help="sample rectangle colours and count annotations")
    show.add_argument("pdf", type=Path)
    take = sub.add_parser("extract", help="map rectangular highlights against a complete linear Word body")
    take.add_argument("pdf", type=Path)
    take.add_argument("word", type=Path)
    take.add_argument("output", type=Path, help="new JSON scope file")
    take.add_argument("--pages", type=int, nargs=2, required=True, metavar=("FIRST", "LAST"))
    take.add_argument("--y", type=float, nargs=2, required=True, metavar=("TOP", "BOTTOM"))
    take.add_argument("--rgb", type=float, nargs=3, required=True)
    put = sub.add_parser("merge", help="apply a JSON object of ID to final English text")
    for arg in ("word", "scope", "edits", "output"):
        put.add_argument(arg, type=Path)
    args = parser.parse_args()
    try:
        {"inspect": inspect, "extract": extract, "merge": merge}[args.command](args)
    except (ValueError, OSError) as err:
        parser.exit(1, f"{err}\n")


if __name__ == "__main__":
    main()
