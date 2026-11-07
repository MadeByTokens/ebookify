"""Extract the readable article from one or more web pages into a book folder.

    python fetch_web.py BOOK URL [URL ...]
    python fetch_web.py BOOK --html saved_page.html --url https://original/url

Each URL becomes one source (sources/NN.json) and one draft file (draft/NN-<slug>.md)
whose first line is "# <article title>". Images are downloaded into images/.
Use --html when the page needs JavaScript or a login: save the rendered HTML with a
browser tool first, then pass it here (with --url so relative links resolve).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import trafilatura
from trafilatura.settings import use_config

from common import UA, Book, localize_images, log, neutralize_html, shift_headings, slugify, tidy_markdown, write_json

MIN_WORDS = 150  # below this the extraction probably failed (paywall, JS app, cookie wall)


def fetch_html(url: str) -> str | None:
    import requests
    try:
        r = requests.get(url, headers={"User-Agent": UA, "Accept-Language": "en,*;q=0.5"}, timeout=60)
        r.raise_for_status()
        r.encoding = r.encoding if r.encoding and r.encoding.lower() != "iso-8859-1" else r.apparent_encoding
        return r.text
    except Exception as e:  # noqa: BLE001
        log(f"! download failed for {url}: {e}")
        return None


def extract(book: Book, html: str, url: str) -> dict:
    idx = book.next_index()
    raw = book.raw_dir(idx)
    (raw / "page.html").write_text(html, encoding="utf-8")

    cfg = use_config()
    cfg.set("DEFAULT", "EXTRACTION_TIMEOUT", "0")
    md = trafilatura.extract(
        html, url=url, output_format="markdown", include_images=True, include_tables=True,
        include_links=True, include_formatting=True, favor_recall=True, config=cfg,
    ) or ""
    meta = trafilatura.extract_metadata(html, default_url=url)
    title = (meta.title if meta and meta.title else None) or url
    author = meta.author if meta and meta.author else (meta.sitename if meta and meta.sitename else None)
    date = meta.date if meta else None
    site = meta.sitename if meta else None
    lang = (meta.language if meta and getattr(meta, "language", None) else None)
    cover_url = meta.image if meta and getattr(meta, "image", None) else None

    md = localize_images(md, url, book.root / "images", f"{idx}")
    md = neutralize_html(shift_headings(tidy_markdown(md, title, url), top=2))
    words = len(md.split())

    byline = " · ".join(dict.fromkeys(x for x in [author, site, date] if x))
    head = f"# {neutralize_html(title)}\n\n"
    if byline:
        head += f"*{neutralize_html(byline)}*\n\n"
    head += f"*Source: <{url}>*\n\n"
    name = f"{idx}-{slugify(title)}.md"
    book.write_draft(name, head + md)

    cover = None
    if cover_url:
        from common import download, fix_image_ext
        p = download(cover_url, book.root / "images" / f"{idx}-cover.img")
        if p:
            cover = f"images/{fix_image_ext(p).name}"

    book.add_source(idx, {
        "type": "web", "url": url, "title": title, "creator": author, "site": site,
        "date": date, "language": lang, "cover": cover, "words": words,
        "draft_files": [name],
    })
    status = "OK" if words >= MIN_WORDS else "SUSPICIOUSLY SHORT - check it (paywall/JS/cookie wall?)"
    log(f"[{idx}] {title!r}: {words} words -> draft/{name}  {status}")
    return {"index": idx, "title": title, "words": words, "draft": name, "ok": words >= MIN_WORDS}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("book")
    ap.add_argument("urls", nargs="*")
    ap.add_argument("--html", help="local HTML file (already rendered page)")
    ap.add_argument("--url", help="original URL of --html (for links/images/metadata)")
    a = ap.parse_args()
    book = Book(a.book)
    results = []
    if a.html:
        results.append(extract(book, Path(a.html).read_text(encoding="utf-8", errors="replace"), a.url or ""))
    for url in a.urls:
        html = fetch_html(url)
        if html is None:
            results.append({"url": url, "ok": False, "error": "download failed"})
            continue
        results.append(extract(book, html, url))
    write_json(book.root / "raw" / "last_fetch_web.json", results)
    sys.exit(0 if all(r.get("ok") for r in results) else 2)


if __name__ == "__main__":
    main()
