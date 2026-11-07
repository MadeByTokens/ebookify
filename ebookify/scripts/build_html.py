"""Build a single-file interactive HTML reader from a book folder.

    python build_html.py BOOK --mode read|learn|teach|entertain [--out file.html]

Same inputs as build_epub.py (chapters/*.md, else draft/*.md). Images are downscaled
and inlined as data: URIs so the file works offline and as a Claude artifact
(artifacts cannot load remote images). Interactive fenced divs (.quiz, .flashcards,
.steps, .notes, .widget, .keyidea ...) are wired up by assets/reader_template.html;
see references/interactive.md for their syntax.
"""
from __future__ import annotations

import argparse
import base64
import html
import io
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

from build_epub import SAFE_MEDIA, about_section, assemble_markdown, filter_reports
from common import Book, log, safe_image_path, slugify

ASSETS = Path(__file__).resolve().parent.parent / "assets"
MAX_BYTES = 16 * 1024 * 1024  # Claude artifact limit


def inline_images(fragment: str, root: Path, max_px: int, quality: int) -> tuple[str, int]:
    from PIL import Image
    count = 0

    def repl(m):
        nonlocal count
        src = html.unescape(m.group(2))
        if re.match(r"data:image/(png|jpe?g|gif|webp);", src):
            return m.group(0)
        p = safe_image_path(root, src)  # never inline anything outside BOOK/images/
        if p is None:
            log(f"  ! image refused or missing: {src[:120]}")
            return m.group(1) + m.group(3)  # empty src
        if p.suffix.lower() == ".svg":
            data, mime = p.read_bytes(), "image/svg+xml"
        else:
            try:
                with Image.open(p) as im:
                    im.thumbnail((max_px, max_px))
                    buf = io.BytesIO()
                    if im.mode in ("RGBA", "LA", "P") and p.suffix.lower() in (".png", ".gif"):
                        im.save(buf, "PNG", optimize=True)
                        mime = "image/png"
                    else:
                        im.convert("RGB").save(buf, "JPEG", quality=quality, optimize=True)
                        mime = "image/jpeg"
                    data = buf.getvalue()
            except Exception:  # noqa: BLE001  not a readable image: do not embed it
                log(f"  ! not a valid image, skipped: {src[:120]}")
                return m.group(1) + m.group(3)
        count += 1
        return f'{m.group(1)}data:{mime};base64,{base64.b64encode(data).decode()}{m.group(3)}'

    out = re.sub(r'(<img[^>]*?\ssrc=")([^"]+)(")', repl, fragment)
    return out, count


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("book")
    ap.add_argument("--mode", choices=["read", "learn", "teach", "entertain"], default="read")
    ap.add_argument("--timestamps", choices=["link", "plain", "strip"], default="link")
    ap.add_argument("--out")
    ap.add_argument("--no-about", action="store_true")
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
    (build / "book-html.md").write_text(md, encoding="utf-8")

    r = subprocess.run(
        ["pandoc", str(build / "book-html.md"), "-f", "markdown+smart", "-t", "html5",
         "--section-divs", "--mathml", "--resource-path", str(book.root), *SAFE_MEDIA],
        capture_output=True, text=True)
    if r.returncode != 0:
        log(r.stderr)
        raise SystemExit("pandoc failed")
    frag = r.stdout

    # try progressively smaller images until the page fits the artifact size limit
    for max_px, q in ((1400, 82), (1000, 72), (720, 60)):
        body, n_img = inline_images(frag, book.root, max_px, q)
        if len(body.encode()) < MAX_BYTES * 0.95:
            break

    byline = " · ".join(x for x in [meta.get("author"),
                                    ", ".join(sorted({s.get("type", "") for s in book.sources()}))] if x)
    tpl = (ASSETS / "reader_template.html").read_text(encoding="utf-8")
    page = (tpl.replace("{{TITLE}}", html.escape(meta.get("title") or "Untitled"))
               .replace("{{LANG}}", html.escape(meta.get("language") or "en"))
               .replace("{{MODE}}", a.mode)
               .replace("{{BYLINE}}", html.escape(byline))
               .replace("{{CONTENT}}", body))
    out = Path(a.out) if a.out else book.root / "out" / f"{slugify(meta.get('title', 'book'))}.html"
    out.write_text(page, encoding="utf-8")

    size = out.stat().st_size
    problems = filter_reports(r.stderr)
    if size > MAX_BYTES:
        problems.append(f"{size/1e6:.1f} MB exceeds the 16 MiB artifact limit: fine as a local file, "
                        "too big to publish as an artifact (drop or shrink images)")
    if "[[t=" in page:
        problems.append("unrendered [[t=..]] markers")
    dropped = len(re.findall(r'<img[^>]*\ssrc=""', body))
    if dropped:
        problems.append(f"{dropped} image(s) not embedded: missing, not an image, remote, or outside images/")
    if book.uncleaned_drafts():
        log(f"warning: draft files not in chapters/ (left out of the book): {book.uncleaned_drafts()}")
    kinds = ("quiz", "flashcards", "steps", "keyidea", "summary", "notes", "widget", "pull")
    counts = {k: page.count(f'class="{k}') for k in kinds}
    print(json.dumps({"file": str(out), "bytes": size, "mode": a.mode, "images_inlined": n_img,
                      "sections": page.count("<section"), "blocks": counts, "problems": problems}, indent=2))
    sys.exit(1 if problems else 0)


if __name__ == "__main__":
    main()
