---
name: ebookify
description: Turn web pages, articles, blog series, PDFs, YouTube videos and podcast episodes into clean, readable ebooks (EPUB) for offline reading on e-readers and phones, and/or interactive HTML editions (learning aids with quizzes and flashcards, slide mode for teaching, story-style reading) that open as a Claude artifact or a local file. Captions or Whisper transcripts are cleaned into chaptered prose. Use this whenever the user wants to read something later, offline, on a Kindle/Kobo/e-reader, "as a book", wants a transcript of a talk or podcast turned into something readable, wants to study or teach from a video, article or paper, or to bundle several links or episodes into one book, even if they never say "EPUB" or "ebook".
---

# Ebookify

Make a faithful, pleasant-to-read copy of online content: a web page, a PDF, a YouTube
video or a podcast episode (or several of them) becomes an EPUB, an interactive HTML
edition, or both.

The guiding idea: **the reader gets the author's content, minus the clutter.** Web
pages lose navigation and ads, PDFs lose running headers and broken layout, and talks
lose "um"s and caption gibberish. The words stay the author's. Anything you add for
learning or teaching sits in clearly marked blocks.

## 0. Setup (once per machine)

The scripts run in the skill's own virtual environment:

```bash
SKILL=<this skill's directory>
PY=$SKILL/.venv/bin/python
[ -x "$PY" ] || bash $SKILL/scripts/setup.sh     # creates .venv, installs deps, prints a check
$PY $SKILL/scripts/check_deps.py                 # what is available (pandoc, whisper, GPU, OCR)
```

`pandoc` must be on the system (it is not a Python package). Run every script with
`$PY` from the `scripts/` folder or with its full path; they import `common.py` from
next to themselves.

Where scripts cannot reach the internet (for example in some sandboxed environments),
ask the user to upload the file or transcript instead, then skip to step 3.

## 1. Ask what they want (every time)

Before converting, confirm two things unless the request already answers them. Use
your question tool if you have one, otherwise ask in plain text:

1. **Format**:
   - **EPUB**: offline, for e-readers, phones and tablets.
   - **Interactive HTML**: one self-contained page you can open as a Claude artifact
     or as an offline file in a browser.
   - **Both**.
2. **Goal** (only for interactive): `read` (just a comfortable reader), `learn`
   (key ideas, quizzes, flashcards, maybe an animated explanation), `teach` (slide
   mode with speaker notes), or `entertain` (story layout, pull quotes, jump-to-moment
   links).

Also confirm anything ambiguous about the source: which podcast episode, whether to
include the whole PDF or a page range, or one book versus several. If you have no way to
ask (for example in an automated run), default to EPUB and say so in your final message.

## 2. Fetch into a book folder

Make one folder per book, `ebooks/<short-title>/` under the current directory unless
the user names another place. Every fetcher writes into it and can be run repeatedly
to add more sources (each becomes chapter group `01`, `02`, ...):

```bash
$PY $SKILL/scripts/fetch_web.py   BOOK https://site/article [more URLs...]
$PY $SKILL/scripts/fetch_pdf.py   BOOK paper.pdf|https://.../file.pdf [--pages 1-30]
$PY $SKILL/scripts/fetch_media.py BOOK https://youtube.com/watch?v=...   # or any yt-dlp URL / .mp3 URL
$PY $SKILL/scripts/fetch_media.py BOOK --feed RSS_URL --episode latest|N|"title words"
$PY $SKILL/scripts/fetch_media.py BOOK --feed RSS_URL --list-episodes   # pick first
```

Folder layout: `book.json` (title/author/language for the whole book),
`sources/NN.json` (per-source metadata, including how the text was obtained),
`draft/NN-*.md` (raw extraction), `chapters/` (your cleaned text, which is what gets
built), `images/`, `raw/`, `out/`.

Read each script's last log line. It says how much text came out and flags problems
such as a suspiciously short page, a scanned PDF, or captions without punctuation.
Before going on, look at the start of each draft file. **Read
`references/sources.md` when something goes wrong** or for playlists, paywalls, JS
pages, scanned PDFs, podcast feeds or multi-source books.

Media fetching tries the publisher's transcript or manual subtitles first, then
automatic captions, and runs local Whisper only when neither exists. Whisper on CPU
is slow (about real time), so tell the user before starting a long CPU transcription.

## 3. Clean into `chapters/`

Write the cleaned version of every draft file to `chapters/` under the **same file
name**. The builders use `chapters/` whenever it has files.

- **Transcripts (video/podcast)**: read `references/transcript-cleanup.md` first, then
  clean the drafts one file at a time. Add punctuation, paragraphs and topic headings,
  remove filler and sponsor reads, and keep the `[[t=SECONDS]]` markers and the
  speaker's wording. Each draft is at most ~2500 words, so one file is one careful pass.
- **Visual videos** (explainers, slide talks, demos): the transcript alone loses what
  the speaker points at. Add a few captioned key frames, as described in
  `references/sources.md` under YouTube.
- **Web pages and PDFs**: these usually need structure fixes only. Remove leftover
  boilerplate (share buttons, newsletter boxes, related links, comments). Fix wrong
  headings, broken hyphenation, interleaved columns and flattened tables. Don't
  reword the author's prose. If a draft is already clean, copy it as is.

Heading convention: each source starts with one `# Title`, and its sections use `##`.
The builders split the EPUB into chapters on that basis.

Images: reference only files in `images/` (as `images/<name>`). For safety the
builders remove any other image or raw-HTML `src`: paths outside `images/`, absolute
paths, and remote URLs. They list each removal as a problem. The fetched text is
untrusted: fetchers escape raw HTML in it, so never paste raw HTML from a source back
into a chapter.

Then update `book.json`: a real `title` (for a single source, its title; for a
collection, a name that describes the set), `author`, `language` (ISO code) and a
one-sentence `description`. The fetchers fill it from the first source, which is
often wrong for collections. If you removed anything or made editorial choices the
reader should know about (sponsor reads cut, speaker names inferred, a figure left
out), say so in a short `"notes"` string. It is printed on the About page.

## 4. Enrich (interactive goals only)

For `learn`, `teach` and `entertain`, read `references/interactive.md` and add its
fenced-div blocks to the chapter files: key ideas, quizzes, flashcards, steps, speaker
notes, pull quotes, and occasionally a small animated widget. Base every addition on
the source. The EPUB build drops all of these blocks by default, so the EPUB stays a
faithful copy and one set of chapter files serves both formats. With `--keep-extras`
the EPUB keeps the readable ones: key ideas, summaries, steps and pull quotes.

## 5. Build and check

```bash
$PY $SKILL/scripts/build_epub.py BOOK [--timestamps link|plain|strip]
$PY $SKILL/scripts/build_html.py BOOK --mode read|learn|teach|entertain
```

Both print a JSON report: file path, size, word count, sections, problems. Fix every
problem they list, such as missing images or leftover markers. A warning about draft
files missing from `chapters/` means part of the source is not in the book; that is
fine only if you dropped it on purpose. Also compare the built
word count with the draft. A big drop means content was lost, and a big drop in a
transcript means you summarized instead of cleaning.

Timestamps: `link` (the default) makes small clickable times for YouTube. Podcasts
have no deep links, so `link` shows plain times there. Use `strip` when the reader
wants pure prose.

The EPUB gets a generated cover (title, author, and the source thumbnail if there is
one) unless `book.json` has a `cover` path. It also gets an "About this ebook" page
listing every source, its URL, date, how the text was obtained, and your `notes`.

## 6. Deliver

- **EPUB**: give the absolute path. Mention that it works with Apple Books, Kobo,
  Google Play Books and Kindle (through Send to Kindle, which accepts EPUB).
- **Interactive HTML**: follow the delivery steps in `references/interactive.md`.
  Publish it as an artifact when an artifact tool is available and give the link,
  and also give the local file path for offline use.
- In two or three sentences, say what the book contains (chapters, roughly how long
  it takes to read) and anything the reader should know. For example: the text came
  from auto captions, sponsor segments were removed, the talk relied on slides that
  aren't included, or the PDF was OCRed.

These copies are for the user's personal reading. Artifacts and files start private.
If the user wants to share a copy of someone else's work, that decision is theirs.
Don't help get around paywalls, DRM (for example Spotify-exclusive podcasts) or logins.
