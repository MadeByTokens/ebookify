"""Shared helpers for the ebookify scripts.

Book folder layout (every fetcher writes into it, every builder reads from it):

    BOOK/
      book.json          title, author, language, description, cover, created
      sources/NN.json    one per ingested source (type, url, title, creator, ...)
      draft/NN-*.md      raw extraction, one or more files per source
      chapters/NN-*.md   cleaned text: this is what gets built (the agent writes these)
      images/            all images, referenced as images/<name>
      raw/NN/            captured html, subtitles, audio, segments.json ...
      out/               built .epub / .html
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import ipaddress
import json
import mimetypes
import os
import re
import socket
import sys
import unicodedata
from pathlib import Path
from urllib.parse import urljoin, urlparse

UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/128.0 Safari/537.36")

TS_MARKER = re.compile(r"\[\[t=(\d+(?:\.\d+)?)\]\]")


def log(*a):
    print(*a, file=sys.stderr, flush=True)


def slugify(text: str, maxlen: int = 50) -> str:
    text = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode()
    text = re.sub(r"[^a-zA-Z0-9]+", "-", text).strip("-").lower()
    return (text[:maxlen].rstrip("-")) or "untitled"


def fmt_ts(seconds: float) -> str:
    s = int(seconds)
    h, rem = divmod(s, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def today() -> str:
    return _dt.date.today().isoformat()


def read_json(path: Path, default=None):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default


def write_json(path: Path, data) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def short_description(text: str | None, limit: int = 300) -> str:
    """First paragraph of a (YouTube/podcast) description, without links, capped."""
    # drop link lines and link labels ("Help fund future projects:") before picking
    lines = [ln for ln in (text or "").splitlines()
             if not re.search(r"https?://|www\.", ln) and not ln.strip().endswith(":")]
    para = next((p.strip() for p in re.split(r"\n\s*\n", "\n".join(lines)) if p.strip()), "")
    para = re.sub(r"\s+", " ", para).strip()
    return para if len(para) <= limit else para[:limit].rsplit(" ", 1)[0] + "…"


def split_code(md: str):
    """Yield (is_code, chunk) for a markdown string, separating fenced code blocks
    (``` or ~~~) so text repairs never touch code."""
    out, buf, fence = [], [], None
    for line in md.split("\n"):
        m = re.match(r"^\s*(`{3,}|~{3,})", line)
        if fence is None and m:
            if buf:
                out.append((False, "\n".join(buf)))
            buf, fence = [line], m.group(1)
        elif fence is not None and line.strip().startswith(fence):
            buf.append(line)
            out.append((True, "\n".join(buf)))
            buf, fence = [], None
        else:
            buf.append(line)
    if buf:
        out.append((fence is not None, "\n".join(buf)))
    return out


def outside_code(md: str, fn) -> str:
    """Apply fn to the non-code parts of md only."""
    return "\n".join(fn(chunk) if not code else chunk for code, chunk in split_code(md))


def chapter_sort_key(p: Path):
    """'x.md' (part 1) must come before 'x-part2.md'; plain sorted() puts '-' before '.'."""
    m = re.match(r"(.*?)(?:-part(\d+))?\.md$", p.name)
    return (m.group(1), int(m.group(2) or 1)) if m else (p.name, 0)


class Book:
    def __init__(self, root: str | Path):
        self.root = Path(root).resolve()
        for sub in ("sources", "draft", "chapters", "images", "raw", "out"):
            (self.root / sub).mkdir(parents=True, exist_ok=True)

    # --- sources -----------------------------------------------------------
    def next_index(self) -> str:
        nums = [int(p.stem) for p in (self.root / "sources").glob("*.json") if p.stem.isdigit()]
        return f"{(max(nums) + 1) if nums else 1:02d}"

    def raw_dir(self, idx: str) -> Path:
        d = self.root / "raw" / idx
        d.mkdir(parents=True, exist_ok=True)
        return d

    def add_source(self, idx: str, meta: dict) -> None:
        meta = {"index": idx, "retrieved": today(), **meta}
        write_json(self.root / "sources" / f"{idx}.json", meta)
        book = self.meta()
        if not book:
            book = {
                "title": meta.get("title") or "Untitled",
                "author": meta.get("creator") or "Unknown",
                "language": meta.get("language") or "en",
                "description": short_description(meta.get("description")),
                "cover": meta.get("cover"),
                "created": today(),
            }
            write_json(self.root / "book.json", book)

    def sources(self) -> list[dict]:
        return [read_json(p) for p in sorted((self.root / "sources").glob("*.json"))]

    def source(self, idx: str) -> dict:
        return read_json(self.root / "sources" / f"{idx}.json", {}) or {}

    def meta(self) -> dict:
        return read_json(self.root / "book.json", {}) or {}

    # --- files -------------------------------------------------------------
    def write_draft(self, name: str, text: str) -> Path:
        p = self.root / "draft" / name
        p.write_text(text.rstrip() + "\n", encoding="utf-8")
        return p

    def uncleaned_drafts(self) -> list[str]:
        """Draft files with no counterpart in chapters/ (only meaningful once chapters/ is used)."""
        done = {p.name for p in (self.root / "chapters").glob("*.md")}
        if not done:
            return []
        return sorted(p.name for p in (self.root / "draft").glob("*.md") if p.name not in done)

    def content_files(self) -> list[Path]:
        """chapters/*.md if the agent has written any, else draft/*.md."""
        files = sorted((self.root / "chapters").glob("*.md"), key=chapter_sort_key)
        if files:
            return files
        log("note: chapters/ is empty, building from draft/ (uncleaned text)")
        return sorted((self.root / "draft").glob("*.md"), key=chapter_sort_key)


# --- images ------------------------------------------------------------------
def check_url(url: str, trusted: bool = False) -> None:
    """Raise ValueError unless url is http(s) and, for untrusted URLs (taken from fetched
    content: feeds, pages, transcripts), resolves only to public addresses. Blocks
    content from steering requests at localhost, the LAN or cloud metadata endpoints.
    Set EBOOKIFY_ALLOW_PRIVATE=1 to allow private addresses."""
    u = urlparse(url)
    if u.scheme not in ("http", "https") or not u.hostname:
        raise ValueError(f"refusing non-http(s) URL: {url[:100]}")
    if trusted or os.environ.get("EBOOKIFY_ALLOW_PRIVATE"):
        return
    port = u.port or (443 if u.scheme == "https" else 80)
    for info in socket.getaddrinfo(u.hostname, port, proto=socket.IPPROTO_TCP):
        ip = ipaddress.ip_address(info[4][0])
        if not ip.is_global:
            raise ValueError(f"refusing {u.hostname}: resolves to non-public address {ip}")


def download(url: str, dest: Path, timeout: int = 60, trusted: bool = False) -> Path | None:
    """Stream url to dest. trusted=True only for URLs the user typed; anything taken
    from fetched content must stay untrusted (see check_url). Redirects are followed
    manually so every hop is checked."""
    import requests
    tmp = dest.with_name(dest.name + ".part")
    try:
        for _ in range(6):
            check_url(url, trusted)
            r = requests.get(url, headers={"User-Agent": UA}, timeout=timeout, stream=True,
                             allow_redirects=False)
            if r.is_redirect and r.headers.get("location"):
                url = urljoin(url, r.headers["location"])
                r.close()
                continue
            break
        else:
            raise ValueError("too many redirects")
        with r:
            r.raise_for_status()
            with open(tmp, "wb") as fh:  # stream: podcast audio can be hundreds of MB
                for chunk in r.iter_content(chunk_size=1 << 16):
                    fh.write(chunk)
    except Exception as e:  # noqa: BLE001
        log(f"  ! could not download {url[:200]}: {e}")
        tmp.unlink(missing_ok=True)
        return None
    tmp.replace(dest)
    return dest


IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg")


def safe_image_path(root: Path, src: str) -> Path | None:
    """Resolve an image reference from book text. Only files inside BOOK/images/ with an
    image extension are allowed: text comes from untrusted sources, and a reference like
    ../../.ssh/id_rsa must never be embedded into a book that may be published."""
    if re.match(r"^[a-z][a-z0-9+.-]*:", src, re.I) or src.startswith(("/", "\\")):
        return None
    images = (root / "images").resolve()
    p = (root / src).resolve()
    if not p.is_relative_to(images) or p.suffix.lower() not in IMAGE_EXTS or not p.is_file():
        return None
    return p


def neutralize_html(md: str) -> str:
    """Make fetched (untrusted) text inert before it reaches pandoc, which passes raw HTML
    straight into the reader page. Outside code: drop comments, turn <br>/<sup>/<sub> into
    markdown, escape every other tag. Everywhere: strip pandoc raw attributes ({=html})."""
    md = re.sub(r"(`+)\{=[A-Za-z0-9_-]+\}", r"\1", md)

    def prose(chunk):
        pieces = re.split(r"(`+[^`]*?`+)", chunk)  # keep inline code spans as they are
        for i in range(0, len(pieces), 2):
            t = re.sub(r"(?s)<!--.*?-->", "", pieces[i])
            t = re.sub(r"(?i)<br\s*/?>", " ", t)
            t = re.sub(r"(?i)</?(?:span|div|font|center|p)\b[^>]*>", "", t)
            t = re.sub(r"(?i)</?(?:b|strong)>", "**", t)
            t = re.sub(r"(?i)</?(?:i|em)>", "*", t)
            t = re.sub(r"(?is)<sup>(.*?)</sup>", lambda m: "^" + m.group(1).replace(" ", "\\ ") + "^", t)
            t = re.sub(r"(?is)<sub>(.*?)</sub>", lambda m: "~" + m.group(1).replace(" ", "\\ ") + "~", t)
            pieces[i] = re.sub(r"<(?=[A-Za-z/!?])", r"\\<", t)
        return "".join(pieces)
    return outside_code(md, prose)


def localize_images(md: str, base_url: str, images_dir: Path, prefix: str) -> str:
    """Download every remote markdown image and rewrite links to images/<file>."""
    pattern = re.compile(r"!\[([^\]]*)\]\(\s*<?([^)\s>]+)>?(?:\s+\"[^\"]*\")?\s*\)")
    cache: dict[str, str] = {}

    def repl(m):
        alt, src = m.group(1), m.group(2)
        if src.startswith("data:"):
            return m.group(0)
        absu = urljoin(base_url, src)
        if absu not in cache:
            ext = Path(urlparse(absu).path).suffix.lower()
            if ext not in IMAGE_EXTS:
                ext = ".img"
            name = f"{prefix}-{hashlib.sha1(absu.encode()).hexdigest()[:10]}{ext}"
            dest = images_dir / name
            if not dest.exists() and not download(absu, dest):
                cache[absu] = ""
            else:
                cache[absu] = fix_image_ext(dest).name
        if not cache[absu]:
            return f"*[image: {alt}]*" if alt else ""
        return f"![{alt}](images/{cache[absu]})"

    return pattern.sub(repl, md)


def fix_image_ext(path: Path) -> Path:
    """Give the file a real extension; convert webp/unknown to png/jpg for e-readers."""
    from PIL import Image
    if path.suffix == ".svg":
        return path
    try:
        with Image.open(path) as im:
            fmt = (im.format or "").lower()
            if fmt in ("jpeg", "png", "gif") and path.suffix in (".jpg", ".jpeg", ".png", ".gif"):
                return path
            # many e-readers do not render webp: convert
            out = path.with_suffix(".jpg" if im.mode in ("RGB", "L") else ".png")
            im2 = im.convert("RGB") if out.suffix == ".jpg" else im.convert("RGBA")
            im2.save(out, quality=88)
    except Exception:  # noqa: BLE001
        return path
    if out != path:
        path.unlink(missing_ok=True)
    return out


def guess_mime(path: Path) -> str:
    return mimetypes.guess_type(str(path))[0] or "application/octet-stream"


def shift_headings(md: str, top: int = 2) -> str:
    """Shift ATX headings (outside code) so the highest-level one becomes `top`."""
    prose = "\n".join(c for code, c in split_code(md) if not code)
    levels = [len(m.group(1)) for m in re.finditer(r"(?m)^(#{1,6})\s", prose)]
    if not levels or min(levels) == top:
        return md
    delta = top - min(levels)

    def shift(chunk):
        return re.sub(r"(?m)^(#{1,6})(?=\s)",
                      lambda m: "#" * max(1, min(6, len(m.group(1)) + delta)), chunk)
    return outside_code(md, shift)


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", unicodedata.normalize("NFKD", s or "").lower())


def tidy_markdown(md: str, title: str | None = None, base_url: str | None = None) -> str:
    """Repair common extraction artefacts without touching the prose or code blocks:
    multi-line headings, links/bold inside headings, same-page anchor links,
    a leading heading that repeats the title, runs of blank lines."""
    def heading_fix(chunk):
        # "####   \n   [Heading text](url)\n   " -> "#### Heading text"
        chunk = re.sub(r"(?m)^(#{1,6})[ \t]*\n[ \t]*(\S[^\n]*?)[ \t]*\n(?=[ \t]*\n)", r"\1 \2\n", chunk)

        def clean_heading(m):
            text = m.group(2)
            whole = re.fullmatch(r"\[(.*)\]\(\S*\)", text)  # whole heading is one link
            text = whole.group(1) if whole else re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)
            text = text.replace("**", "").replace("__", "").strip(" *_")
            return f"{m.group(1)} {text}" if text else ""
        chunk = re.sub(r"(?m)^(#{1,6})[ \t]+(.*?)[ \t]*$", clean_heading, chunk)
        if base_url:
            # links to an anchor on the same page are dead offline; extractors often
            # resolve them as "https://host#anchor" or "https://host/path#anchor"
            u = urlparse(base_url)
            site = re.escape(f"{u.scheme}://{u.netloc}")
            path = re.escape(u.path.rstrip("/"))
            chunk = re.sub(rf"\[([^\]]+)\]\((?:{site}(?:{path})?/?)?#[^)]*\)", r"\1", chunk)
        return re.sub(r"\n{3,}", "\n\n", chunk)

    md = outside_code(md, heading_fix)
    if title:
        lines = md.split("\n")
        for i, line in enumerate(lines[:40]):  # only near the top: title repeated as first heading
            if line.startswith("#"):
                if _norm(line.lstrip("# ")) == _norm(title):
                    del lines[i]
                break
        md = "\n".join(lines)
    return md.strip() + "\n"


def first_heading(md: str) -> str | None:
    m = re.search(r"(?m)^#{1,6}[ \t]+(.+?)[ \t]*$", md)
    return m.group(1).replace("**", "").strip(" *_") if m else None
