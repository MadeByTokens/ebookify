"""Measure objective properties of an eval run's outputs (EPUB / HTML) for grading.
usage: python tools/measure_outputs.py RUN_DIR   (RUN_DIR contains outputs/) -> prints JSON"""
import glob
import json
import re
import sys
import zipfile
from pathlib import Path

run = Path(sys.argv[1])
outs = run / "outputs"
res = {}


def strip(h):
    h = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", h)
    return re.sub(r"<[^>]+>", " ", h)


for ep in sorted(glob.glob(str(outs / "*.epub"))):
    r = {}
    with zipfile.ZipFile(ep) as z:
        names = z.namelist()
        r["mimetype_first"] = names[0] == "mimetype" and z.read("mimetype") == b"application/epub+zip"
        xh = [n for n in names if n.endswith((".xhtml", ".html", ".htm")) and "nav" not in n.lower()]
        html = " ".join(z.read(n).decode("utf-8", "ignore") for n in xh)
        nav = next((z.read(n).decode("utf-8", "ignore") for n in names if re.search(r"nav\.x?html$|toc\.ncx$", n)), "")
        text = strip(html)
        r["words"] = len(text.split())
        r["pre_blocks"] = html.count("<pre")
        r["headings"] = re.findall(r"<h[12][^>]*>(.*?)</h[12]>", html, re.S)[:40]
        r["headings"] = [re.sub(r"<[^>]+>", "", h).strip() for h in r["headings"]]
        r["toc_entries"] = len(re.findall(r"<navPoint|<li", nav))
        r["images"] = [n for n in names if n.lower().endswith((".jpg", ".jpeg", ".png", ".gif", ".svg"))]
        opf = next((z.read(n).decode("utf-8", "ignore") for n in names if n.endswith(".opf")), "")
        r["has_cover"] = bool(re.search(r'cover-image|name="cover"', opf))
        r["um_uh"] = len(re.findall(r"\b(um+|uh+)\b", text, re.I))
        r["ts_markers_left"] = text.count("[[t=")
        r["vtt_lines"] = len(re.findall(r"\d\d:\d\d[:.]\d\d[.,]\d{3}\s*-->", text))
        r["speaker_labels"] = len(re.findall(r"<(?:strong|b)>[^<]{2,40}:?</(?:strong|b)>:?", html))
        r["mentions"] = {k: k.lower() in text.lower() for k in
                         ["jvns.ca", "Julia Evans", "3Blue1Brown", "youtube.com", "The Daily", "simplecast",
                          "Voters Who Flipped Congress"]}
        ad = r"[^.]{0,80}(?:sponsor|support for this podcast|brought to you by|promo code)[^.]{0,80}"
        r["sponsor_hits"] = re.findall(ad, text, re.I)[:5]
    res[Path(ep).name] = r

for hp in sorted(glob.glob(str(outs / "*.html"))):
    h = Path(hp).read_text(encoding="utf-8", errors="ignore")
    r = {"bytes": len(h.encode())}
    srcs = re.findall(r'<(?:img|script|iframe)[^>]*\ssrc="([^"]+)"', h)
    r["remote_srcs"] = [s for s in srcs if s.startswith("http")]
    r["data_imgs"] = len(re.findall(r'<img[^>]*src="data:', h))
    r["inline_svgs"] = h.count("<svg")
    r["quiz"] = len(re.findall(r'class="[^"]*\bquiz\b', h))
    r["flashcards"] = len(re.findall(r'class="[^"]*\bflashcards?\b', h)) + len(re.findall(r"<dt", h))
    r["notes"] = len(re.findall(r'class="[^"]*\b(notes|speaker-notes|aside)\b', h)) + h.count("<aside")
    r["math"] = h.count("<math") + h.count("katex") + h.count("MathJax")
    r["raw_latex"] = len(re.findall(r"\\(frac|sqrt|mathrm|text)\{", strip(h)))
    r["sections"] = h.count("<section")
    r["keydown"] = "keydown" in h
    r["words"] = len(strip(h).split())
    res[Path(hp).name] = r

print(json.dumps(res, indent=1, ensure_ascii=False))
