"""Convert a PDF (local path or URL) into markdown draft(s) inside a book folder.

    python fetch_pdf.py BOOK paper.pdf [--pages 1-40] [--ocr auto|always|never]

- Born-digital PDFs: pymupdf4llm (fast, keeps headings, tables, images).
- Scanned PDFs (almost no text layer): marker_single OCR if it is installed
  (--ocr auto does this automatically), otherwise the script says so and stops.
- Running headers/footers and page numbers repeated on most pages are removed.
- Long documents are split into one draft file per top-level heading.
"""
from __future__ import annotations

import argparse
import collections
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pymupdf
import pymupdf4llm

from common import Book, download, first_heading, log, shift_headings, slugify, tidy_markdown

SCANNED_CHARS_PER_PAGE = 200


def pdf_date(raw: str | None) -> str | None:
    """'D:20230802123456Z' -> '2023-08-02'."""
    m = re.match(r"D?:?(\d{4})(\d{2})?(\d{2})?", raw or "")
    return "-".join(x for x in m.groups() if x) if m else None


def parse_pages(spec: str | None, n: int):
    if not spec:
        return None
    pages = set()
    for part in spec.split(","):
        a, _, b = part.partition("-")
        pages.update(range(int(a) - 1, int(b or a)))
    return sorted(p for p in pages if 0 <= p < n)


def strip_running_lines(chunks: list[str]) -> list[str]:
    """Remove short lines (headers/footers) that recur on >40% of pages."""
    if len(chunks) < 4:
        return chunks
    def norm(line):
        return re.sub(r"\d+", "#", line.strip().strip("*_ ")).lower()

    def cand(line):
        # never treat images, table rows or headings as running headers: after digit
        # normalisation, every "![](images/x-0003-00.png)" line looks the same
        return 0 < len(line.strip()) < 90 and not line.lstrip().startswith(("![", "|", "#"))
    counts = collections.Counter()
    for c in chunks:
        lines = {norm(x) for x in c.splitlines() if cand(x)}
        counts.update(lines)
    bad = {k for k, v in counts.items() if v / len(chunks) > 0.4 and k not in ("", "#")}
    bad |= {"#"}  # bare page numbers
    out = []
    for c in chunks:
        out.append("\n".join(x for x in c.splitlines() if not (cand(x) and norm(x) in bad)))
    return out


def split_top_level(md: str):
    """Yield (title, text) per '# ' heading; text before the first heading is a preface."""
    parts = re.split(r"(?m)^(?=# )", md)
    for p in parts:
        if not p.strip():
            continue
        m = re.match(r"# (.+)", p)
        yield (m.group(1).strip() if m else "Front matter"), p


def run_marker(pdf: Path, raw: Path, images: Path, idx: str) -> str:
    out = raw / "marker"
    cmd = ["marker_single", str(pdf), "--output_dir", str(out), "--output_format", "markdown"]
    log("running OCR: " + " ".join(cmd) + " (this can take a while)")
    subprocess.run(cmd, check=True)
    mds = list(out.rglob("*.md"))
    if not mds:
        raise SystemExit("marker produced no markdown")
    md_path = mds[0]
    md = md_path.read_text(encoding="utf-8")
    for img in md_path.parent.iterdir():
        if img.suffix.lower() in (".png", ".jpg", ".jpeg"):
            new = f"{idx}-{img.name}"
            shutil.copy(img, images / new)
            md = md.replace(f"]({img.name})", f"](images/{new})")
    return md


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("book")
    ap.add_argument("pdf", help="path or http(s) URL")
    ap.add_argument("--pages", help="e.g. 1-20,25 (1-based)")
    ap.add_argument("--ocr", choices=["auto", "always", "never"], default="auto")
    a = ap.parse_args()

    book = Book(a.book)
    idx = book.next_index()
    raw = book.raw_dir(idx)
    images = book.root / "images"

    src = a.pdf
    if src.startswith(("http://", "https://")):
        from urllib.parse import urlparse
        pdf = raw / ((Path(urlparse(src).path).name or "source").removesuffix(".pdf") + ".pdf")
        if not download(src, pdf, timeout=180):
            raise SystemExit("could not download PDF")
    else:
        pdf = Path(src).resolve()

    doc = pymupdf.open(pdf)
    md_meta = doc.metadata or {}
    pages = parse_pages(a.pages, doc.page_count)
    sample = pages or range(min(doc.page_count, 30))
    chars = sum(len(doc[i].get_text()) for i in sample) / max(1, len(list(sample)))
    scanned = chars < SCANNED_CHARS_PER_PAGE
    title = (md_meta.get("title") or "").strip()
    low = title.lower()
    junk = low.endswith((".pdf", ".doc", ".docx", ".tex", ".dvi")) or low.startswith("microsoft word")
    if len(title) < 4 or junk:
        title = ""  # junk metadata; decided from the text below
    author = (md_meta.get("author") or "").strip() or None

    method = "pymupdf4llm"
    if a.ocr == "always" or (scanned and a.ocr == "auto"):
        if not shutil.which("marker_single"):
            raise SystemExit(
                f"PDF looks scanned ({chars:.0f} text chars/page) and marker_single (OCR) is not installed. "
                "Install marker-pdf, or use another OCR skill/tool, then pass the markdown to the build step.")
        md = run_marker(pdf, raw, images, idx)
        method = "marker OCR"
    else:
        chunks = pymupdf4llm.to_markdown(
            doc, pages=pages, page_chunks=True, write_images=True,
            image_path=str(images), image_format="png", dpi=150, show_progress=False,
        )
        texts = strip_running_lines([c["text"] for c in chunks])
        md = "\n\n".join(texts)
        # pymupdf4llm writes absolute/odd image paths: point them at images/
        md = re.sub(r"\]\(([^)]*/)?([^/)]+\.png)\)", lambda m: f"](images/{m.group(2)})", md)
        # prefix the image files with the source index to avoid collisions
        for f in images.glob(f"{pdf.name}-*.png"):
            new = images / f"{idx}-{f.name.replace(' ', '_')}"
            f.rename(new)
            md = md.replace(f"images/{f.name}", f"images/{new.name}")

    md = re.sub(r"\n{3,}", "\n\n", md)
    md = re.sub(r"(?m)^-{5,}\s*$", "", md)  # page separators
    if not title:
        title = first_heading(md) or pdf.stem.replace("_", " ")
    words = len(md.split())

    # One draft file per top-level heading (if there are several), else a single file.
    sections = list(split_top_level(md))
    names = []
    if len([s for s in sections if s[0] != "Front matter"]) >= 3:
        for n, (h, text) in enumerate(sections, 1):
            name = f"{idx}-{n:03d}-{slugify(h, 40)}.md"
            book.write_draft(name, tidy_markdown(text))
            names.append(name)
    else:
        name = f"{idx}-{slugify(title)}.md"
        body = f"# {title}\n\n" + shift_headings(tidy_markdown(md, title), top=2)
        book.write_draft(name, body)
        names.append(name)

    book.add_source(idx, {
        "type": "pdf", "url": src, "title": title, "creator": author,
        "date": pdf_date(md_meta.get("creationDate")), "pages": doc.page_count,
        "method": method, "scanned": scanned, "words": words, "draft_files": names,
    })
    log(f"[{idx}] {title!r}: {doc.page_count} pages, {words} words, method={method}, "
        f"{len(names)} draft file(s)")
    if words < 50:
        log("! almost no text extracted")
        sys.exit(2)


if __name__ == "__main__":
    main()
