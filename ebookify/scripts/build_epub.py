"""Build an EPUB 3 from a book folder.

    python build_epub.py BOOK [--timestamps link|plain|strip] [--out file.epub]

Reads book.json, sources/*.json and chapters/*.md (falls back to draft/*.md),
adds a generated cover if book.json has none, an "About this ebook" page with
provenance, and runs basic validation (plus epubcheck if installed).
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import textwrap
import zipfile
from pathlib import Path

from common import TS_MARKER, Book, fmt_ts, log, slugify, split_code

ASSETS = Path(__file__).resolve().parent.parent / "assets"


def render_timestamps(text: str, ts_url: str | None, mode: str) -> str:
    """Turn [[t=SECONDS]] markers into small timestamp spans (linked when the
    source supports deep links), or remove them."""
    def repl(m):
        if mode == "strip":
            return ""
        t = float(m.group(1))
        label = fmt_ts(t)
        if mode == "link" and ts_url:
            return f"[{label}]({ts_url.format(t=int(t))}){{.ts}} "
        return f"[{label}]{{.ts}} "
    out = TS_MARKER.sub(repl, text)
    out = re.sub(r"(\{\.ts\}) +(?=[.,;:!?)])", r"\1", out)  # marker right before punctuation
    return re.sub(r"(?m)^ +", "", out) if mode == "strip" else out


def assemble_markdown(book: Book, ts_mode: str) -> str:
    parts = []
    for f in book.content_files():
        idx = f.name.split("-", 1)[0]
        src = book.source(idx)
        parts.append(render_timestamps(f.read_text(encoding="utf-8"), src.get("timestamp_url"), ts_mode))
    return "\n\n".join(parts)


# Book text is untrusted. Read markdown without in-document YAML metadata blocks (they
# could inject header-includes), and always run safe_media.lua first: it neutralizes raw
# HTML outside keyed widgets, restricts images to images/ and links to http(s)/mailto/#.
MARKDOWN = "markdown+smart-yaml_metadata_block"


def safe_media(book: Book) -> list[str]:
    return ["-M", f"ebookify_widget_key={book.widget_key()}", "--lua-filter", str(ASSETS / "safe_media.lua")]


def filter_reports(stderr: str) -> list[str]:
    return [line.split("] ", 1)[1] for line in stderr.splitlines() if line.startswith("[ebookify] removed")]


def about_section(book: Book) -> str:
    """Provenance page: every source, where it came from and how the text was made.
    Free-text editing notes come from book.json "notes" and sources/NN.json "notes"."""
    sources = book.sources()
    spoken = any(s.get("type") in ("video", "podcast") for s in sources)
    intro = "This is a personal, offline reading copy made from the source(s) below."
    if spoken:
        intro += (" Spoken audio was transcribed and lightly edited for readability "
                  "(punctuation, paragraphs, filler words, headings); the wording is the speaker's.")
    lines = ["# About this ebook {.unnumbered .about}", "", intro, ""]
    notes = book.meta().get("notes")
    if notes:
        lines += [notes if isinstance(notes, str) else " ".join(notes), ""]
    for s in sources:
        lines += [f"**{s.get('title') or 'Untitled'}**", ""]
        bits = []
        if s.get("creator"):
            bits.append(f"By {s['creator']}")
        if s.get("date"):
            bits.append(f"published {s['date']}")
        bits.append(s.get("type", "source"))
        if s.get("transcript_method"):
            bits.append(f"text from {s['transcript_method']}")
        if s.get("method"):
            bits.append(f"converted with {s['method']}")
        bits.append(f"retrieved {s.get('retrieved')}")
        lines.append(" · ".join(bits))
        if s.get("notes"):
            lines += ["", s["notes"] if isinstance(s["notes"], str) else " ".join(s["notes"])]
        if s.get("url"):
            lines += ["", f"<{s['url']}>"]
        if s.get("feed") and s.get("feed") != s.get("url"):
            lines += ["", f"Feed: <{s['feed']}>"]
        lines.append("")
    return "\n".join(lines)


def count_top_headings(md: str) -> int:
    return sum(len(re.findall(r"(?m)^# ", chunk)) for code, chunk in split_code(md) if not code)


# ------------------------------------------------------------------ cover
FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSerif-Bold.ttf",
    "/Library/Fonts/Georgia Bold.ttf", "/System/Library/Fonts/Supplemental/Georgia Bold.ttf",
    "C:/Windows/Fonts/georgiab.ttf",
]
FONT_REG = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    "/System/Library/Fonts/Supplemental/Arial.ttf", "C:/Windows/Fonts/arial.ttf",
]


def _font(cands, size):
    from PIL import ImageFont
    for c in cands:
        if Path(c).exists():
            return ImageFont.truetype(c, size)
    return ImageFont.load_default(size=size)


def make_cover(book: Book, meta: dict, dest: Path) -> Path:
    from PIL import Image, ImageDraw
    W, H = 1600, 2400
    bg, ink, accent = (24, 38, 52), (240, 236, 228), (120, 170, 200)
    img = Image.new("RGB", (W, H), bg)
    d = ImageDraw.Draw(img)
    y = 220
    # use the first source's own image (thumbnail / article image) as artwork if present
    art = next((s.get("cover") for s in book.sources() if s.get("cover")), None)
    if art and (book.root / art).exists():
        try:
            a = Image.open(book.root / art).convert("RGB")
            a.thumbnail((W - 240, 900))
            img.paste(a, ((W - a.width) // 2, y))
            y += a.height + 120
        except Exception:  # noqa: BLE001
            pass
    title = meta.get("title") or "Untitled"
    size = 130 if len(title) < 40 else 104 if len(title) < 80 else 84
    tf = _font(FONT_CANDIDATES, size)
    for line in textwrap.wrap(title, width=int(1250 / (size * 0.52))):
        d.text((120, y), line, font=tf, fill=ink)
        y += int(size * 1.2)
    d.rectangle([120, y + 40, 360, y + 52], fill=accent)
    af = _font(FONT_REG, 64)
    d.text((120, y + 110), meta.get("author") or "", font=af, fill=accent)
    types = sorted({s.get("type", "") for s in book.sources()})
    d.text((120, H - 200), " · ".join(t for t in types if t).upper(), font=_font(FONT_REG, 44), fill=accent)
    img.save(dest, quality=90)
    return dest


# ------------------------------------------------------------------ validation
def validate(epub: Path, warnings: list[str]) -> dict:
    report = {"file": str(epub), "bytes": epub.stat().st_size, "problems": []}
    with zipfile.ZipFile(epub) as z:
        names = z.namelist()
        if names[0] != "mimetype" or z.read("mimetype") != b"application/epub+zip":
            report["problems"].append("mimetype entry missing or not first")
        report["xhtml_files"] = sum(n.endswith(".xhtml") for n in names)
        report["images"] = sum(n.lower().endswith((".png", ".jpg", ".jpeg", ".gif", ".svg")) for n in names)
        text = " ".join(re.sub(r"<[^>]+>", " ", z.read(n).decode("utf-8", "ignore"))
                        for n in names if n.endswith(".xhtml"))
        report["words"] = len(text.split())
        if "[[t=" in text:
            report["problems"].append("unrendered [[t=..]] timestamp markers left in text")
    for w in warnings:
        if "Could not fetch" in w or "not found" in w.lower():
            report["problems"].append(w.strip())
    if shutil.which("epubcheck"):
        r = subprocess.run(["epubcheck", "-q", str(epub)], capture_output=True, text=True)
        report["epubcheck"] = "passed" if r.returncode == 0 else (r.stdout + r.stderr)[-2000:]
    return report


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("book")
    ap.add_argument("--timestamps", choices=["link", "plain", "strip"], default="link",
                    help="how [[t=SEC]] markers render (link only where the source supports deep links)")
    ap.add_argument("--out")
    ap.add_argument("--no-about", action="store_true")
    ap.add_argument("--keep-extras", action="store_true",
                    help="keep the agent's study blocks (key ideas, summaries, steps, pull quotes) in the EPUB; "
                         "quizzes, flashcards, speaker notes and widgets are always dropped")
    a = ap.parse_args()

    if not shutil.which("pandoc"):
        raise SystemExit("pandoc is required: install it (apt install pandoc / brew install pandoc)")
    book = Book(a.book)
    meta = book.meta()
    if not meta:
        raise SystemExit("book.json missing: run a fetch_* script first")

    md = assemble_markdown(book, a.timestamps)
    if not a.no_about:
        md += "\n\n" + about_section(book)
    build = book.root / "out" / ".build"
    build.mkdir(parents=True, exist_ok=True)
    (build / "book.md").write_text(md, encoding="utf-8")

    cover = meta.get("cover")
    cover_path = (book.root / cover) if cover else None
    if not cover_path or not cover_path.exists():
        cover_path = make_cover(book, meta, build / "cover.jpg")

    urn = f"urn:ebookify:{slugify(meta.get('title', ''))}-{meta.get('created')}"
    pmeta = {
        "title": meta.get("title"), "author": meta.get("author"), "lang": meta.get("language", "en"),
        "date": meta.get("date") or meta.get("created"), "description": meta.get("description") or "",
        "rights": "Personal offline copy. Copyright remains with the original authors.",
        "identifier": [{"scheme": "URN", "text": urn}],
    }
    meta_yaml = build / "meta.yaml"  # pandoc 2.x reads YAML; JSON is valid YAML
    meta_yaml.write_text(json.dumps(pmeta, ensure_ascii=False), encoding="utf-8")

    n_h1 = count_top_headings(md) - (0 if a.no_about else 1)
    chapter_level = "1" if n_h1 > 1 else "2"
    out = Path(a.out) if a.out else book.root / "out" / f"{slugify(meta.get('title', 'book'))}.epub"
    cmd = ["pandoc", str(build / "book.md"), "-f", MARKDOWN, "-t", "epub3", "-o", str(out),
           "--toc", "--toc-depth=2", f"--epub-chapter-level={chapter_level}",
           *safe_media(book), "--css", str(ASSETS / "epub.css"), "--epub-cover-image", str(cover_path),
           "--metadata-file", str(meta_yaml), "--resource-path", str(book.root), "--mathml",
           "--metadata", f"title={meta.get('title')}"]
    cmd += ["--lua-filter", str(ASSETS / ("strip_interactive.lua" if a.keep_extras else "strip_extras.lua"))]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        log(r.stderr)
        raise SystemExit("pandoc failed")
    warnings = [w for w in r.stderr.splitlines() if w.strip() and not w.startswith("[ebookify]")]
    report = validate(out, warnings)
    report["problems"] += filter_reports(r.stderr)
    report["chapter_split_level"] = int(chapter_level)
    if book.uncleaned_drafts():  # a warning, not a problem: dropping a draft can be deliberate
        report["warning"] = f"draft files not in chapters/ (left out of the book): {book.uncleaned_drafts()}"
    print(json.dumps(report, indent=2))
    sys.exit(1 if report["problems"] else 0)


if __name__ == "__main__":
    main()
