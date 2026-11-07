"""Turn a YouTube video or podcast episode into timestamped transcript drafts.

    python fetch_media.py BOOK https://www.youtube.com/watch?v=...      # any yt-dlp URL
    python fetch_media.py BOOK https://example.com/episode.mp3          # direct audio
    python fetch_media.py BOOK --feed https://feed.url/rss --episode latest|N|"title words"
    python fetch_media.py BOOK --list-episodes --feed https://feed.url/rss

Transcript priority (first that works wins):
  1. publisher transcript (podcast:transcript in RSS) or manual subtitles
  2. automatic captions (YouTube)
  3. local Whisper (faster-whisper) on the downloaded audio
Use --whisper to skip straight to 3, --lang to choose the language.

Output: draft/NN-MMM-<chapter>.md files (~2500 words max each) whose paragraphs start
with [[t=SECONDS]] markers, plus raw/NN/segments.json and sources/NN.json.
"""
from __future__ import annotations

import argparse
import html
import json
import re
import subprocess
import sys
from pathlib import Path

import defusedxml.ElementTree as ET  # feeds are untrusted: block XXE / entity bombs

from common import UA, Book, download, fix_image_ext, fmt_ts, log, neutralize_html, slugify, write_json

MAX_WORDS_PER_FILE = 2500
PODCAST_NS = "https://podcastindex.org/namespace/1.0"


# --------------------------------------------------------------------------- yt-dlp
def ytdlp(*args, capture=True):
    cmd = [sys.executable, "-m", "yt_dlp", "--no-warnings", "--user-agent", UA, *args]
    r = subprocess.run(cmd, capture_output=capture, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"yt-dlp failed: {r.stderr[-1500:] if capture else ''}")
    return r.stdout if capture else ""


def pick_sub_lang(tracks: dict, want: str | None, orig: str | None) -> str | None:
    if not tracks:
        return None
    keys = list(tracks)
    for cand in [want, orig, "en"]:
        if not cand:
            continue
        for k in keys:  # exact, then prefix (en-US, en-orig ...)
            if k == cand:
                return k
        for k in keys:
            if k.split("-")[0] == cand.split("-")[0] and "translated" not in k:
                return k
    return None


# --------------------------------------------------------------------------- parsers
def parse_json3(path: Path):
    data = json.loads(path.read_text(encoding="utf-8"))
    segs = []
    for ev in data.get("events", []):
        if "segs" not in ev:
            continue
        text = "".join(s.get("utf8", "") for s in ev["segs"]).replace("\n", " ").strip()
        if not text:
            continue
        start = ev.get("tStartMs", 0) / 1000
        segs.append({"start": start, "end": start + ev.get("dDurationMs", 0) / 1000, "text": text})
    return segs


def _ts(s: str) -> float:
    s = s.replace(",", ".")
    parts = [float(p) for p in s.split(":")]
    while len(parts) < 3:
        parts.insert(0, 0.0)
    return parts[0] * 3600 + parts[1] * 60 + parts[2]


def parse_vtt_srt(path: Path):
    """WebVTT or SRT. Handles YouTube-style rolling captions by dropping repeated lines."""
    text = path.read_text(encoding="utf-8", errors="replace")
    blocks = re.split(r"\n\s*\n", text)
    segs, last_line = [], None
    for b in blocks:
        m = re.search(r"([\d:.,]+)\s*-->\s*([\d:.,]+)", b)
        if not m:
            continue
        body = b[m.end():].split("\n", 1)[1] if "\n" in b[m.end():] else ""
        lines = []
        for line in body.splitlines():
            line = html.unescape(re.sub(r"<[^>]+>", "", line)).strip()
            if line and line != last_line:
                lines.append(line)
                last_line = line
        if lines:
            segs.append({"start": _ts(m.group(1)), "end": _ts(m.group(2)), "text": " ".join(lines)})
    return segs


def parse_podcast_transcript(path: Path, mime: str):
    if "json" in mime or path.suffix == ".json":
        data = json.loads(path.read_text(encoding="utf-8"))
        return [{"start": float(s.get("startTime", 0)), "end": float(s.get("endTime", 0)),
                 "text": s.get("body", "").strip(), "speaker": s.get("speaker")}
                for s in data.get("segments", []) if s.get("body", "").strip()]
    if any(x in mime for x in ("vtt", "srt", "subrip")) or path.suffix in (".vtt", ".srt"):
        return parse_vtt_srt(path)
    # html / plain text: no timings, one pseudo-segment per paragraph
    raw = path.read_text(encoding="utf-8", errors="replace")
    if "html" in mime:
        raw = re.sub(r"(?i)</p>|<br\s*/?>", "\n\n", raw)
        raw = html.unescape(re.sub(r"<[^>]+>", "", raw))
    return [{"start": None, "end": None, "text": p.strip()} for p in re.split(r"\n\s*\n", raw) if p.strip()]


# --------------------------------------------------------------------------- whisper
def _preload_cuda_libs():
    """ctranslate2 dlopen()s cuBLAS/cuDNN by soname. When they come from the
    nvidia-* pip wheels (installed by setup.sh) they are not on the loader path,
    so load them globally up front."""
    import ctypes
    import glob
    import os
    import site
    pats = ["nvidia/cuda_runtime/lib/libcudart.so.*", "nvidia/cublas/lib/libcublasLt.so.*",
            "nvidia/cublas/lib/libcublas.so.*", "nvidia/cudnn/lib/libcudnn*.so.*"]
    for sp in site.getsitepackages():
        for pat in pats:
            for f in sorted(glob.glob(os.path.join(sp, pat))):
                try:
                    ctypes.CDLL(f, mode=ctypes.RTLD_GLOBAL)
                except OSError:
                    pass


GAP_SECONDS = 8.0  # unexplained silence longer than this gets a second look without VAD


def _segments(model, audio, lang, **kw):
    segments, info = model.transcribe(str(audio), language=lang, beam_size=5, **kw)
    out = []
    for s in segments:  # lazy generator: CUDA errors surface here, not at load time
        if s.no_speech_prob > 0.6 and s.avg_logprob < -1.0:
            continue  # almost certainly music/noise hallucination ("Thank you.")
        out.append({"start": round(s.start, 2), "end": round(s.end, 2), "text": s.text.strip()})
        if len(out) % 200 == 0:
            log(f"  ... {fmt_ts(s.end)} transcribed")
    return out, info


def _plausible_speech(seg) -> bool:
    """Without VAD, Whisper hallucinates over music ("Hello, hello." stretched over
    10 s, "Thank you."). Real speech runs at ~2-3 words/s; keep segments above 1 w/s."""
    words = len(seg["text"].split())
    dur = max(0.1, seg["end"] - seg["start"])
    return words >= 3 and words / dur >= 1.0


def _find_gaps(segs, duration):
    gaps, prev = [], 0.0
    for s in segs + [{"start": duration, "end": duration}]:
        if s["start"] - prev > GAP_SECONDS:
            gaps.append((prev, s["start"]))
        prev = max(prev, s["end"])
    return gaps


def _run_whisper(audio, model_name, device, ctype, lang):
    from faster_whisper import WhisperModel
    log(f"whisper: model={model_name} device={device} (first run downloads the model)")
    model = WhisperModel(model_name, device=device, compute_type=ctype)
    segs, info = _segments(model, audio, lang, vad_filter=True)
    # Silero VAD sometimes discards real speech (speech over music, quiet voices).
    # Re-transcribe long unexplained gaps without VAD and merge what is found.
    gaps = _find_gaps(segs, info.duration)
    if gaps:
        clips = [round(x, 2) for g in gaps for x in g]
        extra, _ = _segments(model, audio, info.language, vad_filter=False, clip_timestamps=clips)
        extra = [e for e in extra if _plausible_speech(e) and any(a - 1 <= e["start"] < b for a, b in gaps)]
        if extra:
            words = sum(len(e["text"].split()) for e in extra)
            log(f"  recovered {words} words in {len(gaps)} gap(s) the VAD skipped")
            segs = sorted(segs + extra, key=lambda x: x["start"])
    return segs, info


def transcribe(audio: Path, model_name: str | None, lang: str | None, out_json: Path):
    try:
        import ctranslate2
        gpu = ctranslate2.get_cuda_device_count() > 0
    except Exception:  # noqa: BLE001
        gpu = False
    if gpu:
        _preload_cuda_libs()
        try:
            segs, info = _run_whisper(audio, model_name or "large-v3-turbo", "cuda", "float16", lang)
        except Exception as e:  # noqa: BLE001  missing CUDA libs, out of memory ...
            log(f"whisper on GPU failed ({str(e)[:200]}); retrying on CPU (slower)")
            gpu = False
    if not gpu:
        name = model_name if model_name and not model_name.startswith("large") else "small"
        segs, info = _run_whisper(audio, name, "cpu", "int8", lang)
    write_json(out_json, segs)
    return segs, info.language


# --------------------------------------------------------------------------- RSS
def load_feed(feed_url: str):
    import requests
    r = requests.get(feed_url, headers={"User-Agent": UA}, timeout=60)
    r.raise_for_status()
    root = ET.fromstring(r.content)
    chan = root.find("channel")
    if chan is None:
        raise SystemExit("not an RSS feed (no <channel>); Atom feeds are not supported, "
                         "pass the episode audio URL directly instead")
    show = (chan.findtext("title") or "").strip()
    show_img = None
    img = chan.find("{http://www.itunes.com/dtds/podcast-1.0.dtd}image")
    if img is not None:
        show_img = img.get("href")
    items = []
    for it in chan.findall("item"):
        enc = it.find("enclosure")
        trs = [{"url": t.get("url"), "type": t.get("type", "")} for t in it.findall(f"{{{PODCAST_NS}}}transcript")]
        ep_img = it.find("{http://www.itunes.com/dtds/podcast-1.0.dtd}image")
        items.append({
            "title": (it.findtext("title") or "").strip(),
            "date": it.findtext("pubDate"),
            "audio": enc.get("url") if enc is not None else None,
            "link": it.findtext("link"),
            "description": it.findtext("{http://purl.org/rss/1.0/modules/content/}encoded")
            or it.findtext("description") or "",
            "transcripts": trs,
            "image": ep_img.get("href") if ep_img is not None else show_img,
        })
    return show, items


def choose_episode(items, sel: str):
    if sel == "latest":
        return items[0]
    if sel.isdigit():  # 1 = newest
        n = int(sel)
        if not 1 <= n <= len(items):
            raise SystemExit(f"episode number must be 1..{len(items)}; use --list-episodes")
        return items[n - 1]
    words = sel.lower().split()
    hits = [i for i in items if all(w in i["title"].lower() for w in words)]
    if not hits:
        raise SystemExit(f"no episode matches {sel!r}; use --list-episodes")
    return hits[0]


def best_podcast_transcript(trs):
    order = ["json", "vtt", "srt", "subrip", "html", "text"]

    def rank(t):
        return next((n for n, k in enumerate(order) if k in t["type"]), len(order))
    return sorted(trs, key=rank)[0] if trs else None


# --------------------------------------------------------------------------- drafting
def to_paragraphs(segs):
    """Group segments into paragraphs: break on long pauses, speaker change, or length."""
    paras, cur, cur_start, cur_words = [], [], None, 0
    for i, s in enumerate(segs):
        if cur_start is None:
            cur_start = s["start"]
        cur.append(s["text"])
        cur_words += len(s["text"].split())
        nxt = segs[i + 1] if i + 1 < len(segs) else None
        gap = (nxt["start"] - s["end"]) if (nxt and nxt["start"] is not None and s["end"]) else 0
        ends_sentence = s["text"].rstrip().endswith((".", "?", "!", '"', "”"))
        speaker_change = nxt and nxt.get("speaker") and nxt.get("speaker") != s.get("speaker")
        if (nxt is None or gap > 2.0 or speaker_change or (cur_words > 90 and ends_sentence)
                or cur_words > 160 or s["start"] is None):
            paras.append({"start": cur_start, "text": " ".join(cur), "speaker": s.get("speaker")})
            cur, cur_start, cur_words = [], None, 0
    return paras


def write_drafts(book: Book, idx: str, title: str, paras, chapters):
    """Split paragraphs into one draft file per chapter (and ~2500-word parts).
    chapters: list of {title, start_time}. Returns draft filenames."""
    if not chapters:
        chapters = [{"title": title, "start_time": 0}]
    # the first chapter also takes anything said before its start time
    bounds = [float("-inf")] + [c.get("start_time") or 0 for c in chapters[1:]] + [float("inf")]
    single = len(chapters) == 1
    names = []
    for ci, ch in enumerate(chapters):
        cps = [p for p in paras if (p["start"] is None and ci == 0)
               or (p["start"] is not None and bounds[ci] <= p["start"] < bounds[ci + 1])]
        parts, cur, words = [], [], 0
        for p in cps:
            mark = f"[[t={int(p['start'])}]] " if p["start"] is not None else ""
            spk = f"**{p['speaker']}:** " if p.get("speaker") else ""
            cur.append(mark + spk + neutralize_html(p["text"]))  # transcript text is untrusted
            words += len(p["text"].split())
            if words >= MAX_WORDS_PER_FILE:
                parts.append(cur)
                cur, words = [], 0
        if cur:
            parts.append(cur)
        heading = "## (add topic headings while cleaning)" if single else f"## {ch['title']}"
        for pi, body in enumerate(parts, 1):
            name = f"{idx}-{ci + 1:03d}-{slugify(ch['title'], 40)}{f'-part{pi}' if pi > 1 else ''}.md"
            head = []
            if ci == 0 and pi == 1:
                head.append(f"# {neutralize_html(title)}")
            if pi == 1:
                head.append(neutralize_html(heading))
            book.write_draft(name, "\n\n".join(head + body))
            names.append(name)
    return names


# --------------------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("book")
    ap.add_argument("url", nargs="?")
    ap.add_argument("--feed", help="podcast RSS feed URL")
    ap.add_argument("--episode", default="latest", help="latest | N (1=newest) | words from the title")
    ap.add_argument("--list-episodes", action="store_true")
    ap.add_argument("--lang", help="transcript language, e.g. en, pt")
    ap.add_argument("--whisper", action="store_true", help="ignore captions, always transcribe")
    ap.add_argument("--whisper-model", help="default: large-v3-turbo on GPU, small on CPU")
    a = ap.parse_args()

    if a.list_episodes:
        show, items = load_feed(a.feed)
        print(show)
        for n, it in enumerate(items[:50], 1):
            tr = "transcript" if it["transcripts"] else ""
            print(f"{n:3d}. {it['title']}  [{it['date']}] {tr}")
        return

    book = Book(a.book)
    idx = book.next_index()
    raw = book.raw_dir(idx)
    segs, method, lang = None, None, a.lang
    meta = {"type": "podcast" if a.feed else "video"}
    chapters = []
    ts_url = None
    audio_url = None
    cover_url = None

    if a.feed:
        show, items = load_feed(a.feed)
        ep = choose_episode(items, a.episode)
        meta.update(title=ep["title"], creator=show, date=ep["date"], url=ep["link"] or ep["audio"],
                    feed=a.feed, description=re.sub(r"<[^>]+>", " ", html.unescape(ep["description"])).strip())
        audio_url, cover_url = ep["audio"], ep["image"]
        tr = None if a.whisper else best_podcast_transcript(ep["transcripts"])
        if tr:
            ext = {"json": ".json", "vtt": ".vtt", "srt": ".srt", "subrip": ".srt", "html": ".html"}
            suffix = next((v for k, v in ext.items() if k in tr["type"]), ".txt")
            p = download(tr["url"], raw / f"transcript{suffix}")
            if p:
                segs = parse_podcast_transcript(p, tr["type"])
                method = f"publisher transcript ({tr['type'] or suffix})"
    else:
        if not a.url:
            raise SystemExit("give a URL or --feed")
        info = json.loads(ytdlp("-J", "--no-playlist", a.url))
        (raw / "info.json").write_text(json.dumps(info, indent=1), encoding="utf-8")
        is_audio_only = info.get("vcodec") in (None, "none") and not info.get("width")
        meta.update(
            type="podcast" if is_audio_only else "video",
            title=info.get("title"), creator=info.get("uploader") or info.get("channel") or info.get("artist"),
            date=info.get("upload_date"), url=info.get("webpage_url") or a.url,
            description=info.get("description"), duration=info.get("duration"),
            extractor=info.get("extractor_key"))
        chapters = info.get("chapters") or []
        cover_url = info.get("thumbnail")
        lang = lang or info.get("language")
        if info.get("extractor_key") == "Youtube":
            ts_url = f"https://www.youtube.com/watch?v={info['id']}&t={{t}}s"
        if not a.whisper:
            for kind, flag in (("subtitles", "--write-subs"), ("automatic_captions", "--write-auto-subs")):
                code = pick_sub_lang(info.get(kind) or {}, a.lang, info.get("language"))
                if not code:
                    continue
                try:
                    ytdlp("--skip-download", "--no-playlist", flag, "--sub-langs", code,
                          "--sub-format", "json3/vtt/srt/best", "-o", str(raw / "subs.%(ext)s"), a.url)
                except RuntimeError as e:
                    log(f"  could not fetch {kind}: {e}")
                    continue
                files = sorted(raw.glob("subs.*"))
                if not files:
                    continue
                f = files[0]
                segs = parse_json3(f) if f.suffix == ".json3" else parse_vtt_srt(f)
                method = f"{'manual subtitles' if kind == 'subtitles' else 'automatic captions'} ({code})"
                lang = code.split("-")[0]
                break

    if not segs:
        log("no usable captions/transcript: downloading audio for Whisper")
        if a.feed or (a.url and re.search(r"\.(mp3|m4a|ogg|opus|wav|aac)(\?|$)", a.url or "", re.I)):
            src = audio_url or a.url
            dest = raw / ("audio" + (Path(src.split("?")[0]).suffix or ".mp3"))
            audio = download(src, dest, timeout=900, trusted=not a.feed)  # feed enclosures are untrusted
            if not audio:
                raise SystemExit("audio download failed")
        else:
            ytdlp("-f", "bestaudio/best", "-x", "--audio-format", "m4a", "--no-playlist",
                  "-o", str(raw / "audio.%(ext)s"), a.url, capture=True)
            audio = next(raw.glob("audio.*"))
        try:
            segs, lang = transcribe(audio, a.whisper_model, a.lang, raw / "segments.json")
        except ImportError as e:
            raise SystemExit("faster-whisper not installed and no captions exist: run scripts/setup.sh") from e
        method = "local Whisper transcription"

    write_json(raw / "segments.json", segs)
    if cover_url:
        p = download(cover_url, book.root / "images" / f"{idx}-cover.img")
        if p:
            meta["cover"] = f"images/{fix_image_ext(p).name}"

    paras = to_paragraphs(segs)
    names = write_drafts(book, idx, meta["title"] or "Transcript", paras, chapters)
    words = sum(len(p["text"].split()) for p in paras)
    meta.update(language=lang, transcript_method=method, timestamp_url=ts_url,
                chapters=[{"title": c["title"], "start": c.get("start_time")} for c in chapters],
                words=words, draft_files=names)
    book.add_source(idx, meta)
    punct = sum(s["text"].count(".") for s in segs) / max(1, words)
    warn = "; NO PUNCTUATION (auto captions) - cleanup must add it" if punct < 0.01 else ""
    log(f"[{idx}] {meta['title']!r}: {words} words via {method}; {len(chapters)} chapters; "
        f"{len(names)} draft file(s){warn}")


if __name__ == "__main__":
    main()
