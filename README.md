# ebookify

An agent skill that turns web pages, PDFs, YouTube videos and podcast episodes into
**readable offline ebooks (EPUB)** and **interactive HTML editions** for learning,
teaching or just reading. The HTML editions work as Claude artifacts or as local files.

The idea is a faithful copy without the clutter. Web pages lose navigation and ads, PDFs
lose running headers and broken layout, and talks lose the "um"s and caption gibberish.
The words stay the author's. Anything the agent adds (key ideas, quizzes, speaker notes)
lives in clearly marked blocks, and the EPUB leaves them out by default.

## What it does

| Source | How text is obtained |
|---|---|
| Web page / blog post / series | [trafilatura](https://trafilatura.readthedocs.io) article extraction; images downloaded locally |
| PDF (paper, report, book) | [pymupdf4llm](https://pymupdf.readthedocs.io/en/latest/pymupdf4llm/); running headers removed; scanned PDFs go to [marker](https://github.com/VikParuchuri/marker) OCR if installed |
| YouTube (or any [yt-dlp](https://github.com/yt-dlp/yt-dlp) site) | manual subtitles → automatic captions → local Whisper; creator chapters become book chapters |
| Podcast (RSS feed or audio URL) | publisher transcript (`podcast:transcript`) → local [faster-whisper](https://github.com/SYSTRAN/faster-whisper) (GPU if available, with recovery of speech the VAD skipped) |

The agent cleans each draft by hand. Transcripts get punctuation, paragraphs, topic
headings and speaker labels, and lose filler and sponsor reads; web pages and PDFs get
structure fixes only. Then two builders produce the output:

- **EPUB 3** (`build_epub.py`): table of contents, a generated cover, an "About this
  ebook" provenance page, optional clickable timestamps back to the video, and basic
  validation (plus `epubcheck` if installed). Works with Kobo, Apple Books, Google Play
  Books, and Kindle via Send to Kindle.
- **Interactive HTML** (`build_html.py --mode read|learn|teach|entertain`): one
  self-contained file with a contents drawer, reading progress, remembered position,
  text size, light/dark theme, and slide mode with speaker notes. It also renders the
  agent's quizzes, flashcards, step-by-step walkthroughs, pull quotes and small
  animated widgets. Images are inlined, so the page meets the Claude artifact rules
  (no remote images, 16 MiB maximum).

## Install

Requirements: Python ≥ 3.10, [pandoc](https://pandoc.org) on the PATH, and ffmpeg for
audio. Optional: an NVIDIA GPU for fast Whisper, `marker_single` for OCR, and
`epubcheck` for strict validation.

```bash
git clone <this repo> ebookskill
bash ebookskill/ebookify/scripts/setup.sh        # creates ebookify/.venv and reports what is available
```

`setup.sh` uses `uv` when it is available and falls back to `python -m venv` + pip.
When `nvidia-smi` is present it also installs the cuBLAS/cuDNN wheels that
faster-whisper needs (about 1.5 GB). Set `EBOOKIFY_NO_CUDA=1` to skip them, and Whisper
will run on the CPU. Run `setup.sh --upgrade` when yt-dlp starts failing; YouTube
changes often.

### Use it with Claude Code

Link (or copy) the skill folder into your skills directory:

```bash
ln -s "$PWD/ebookskill/ebookify" ~/.claude/skills/ebookify
```

Then ask for what you want, for example:

- "make me an epub of this video for my kobo https://www.youtube.com/watch?v=…"
- "turn this paper into slides I can present from on Thursday: https://arxiv.org/pdf/…"
- "I want to study this article, make an interactive version with quizzes"
- "put the last three episodes of <podcast> into one book"

The agent asks which format (EPUB, interactive HTML, or both) and, for HTML, what the
edition is for, unless the request already says.

### Use the scripts directly

```bash
PY=ebookify/.venv/bin/python
$PY ebookify/scripts/fetch_web.py   ebooks/mybook https://example.com/article
$PY ebookify/scripts/fetch_pdf.py   ebooks/mybook paper.pdf
$PY ebookify/scripts/fetch_media.py ebooks/mybook https://www.youtube.com/watch?v=…
$PY ebookify/scripts/fetch_media.py ebooks/mybook --feed https://…/rss --list-episodes
# copy or clean draft/*.md into chapters/*.md, then:
$PY ebookify/scripts/build_epub.py  ebooks/mybook
$PY ebookify/scripts/build_html.py  ebooks/mybook --mode learn
```

Every script prints `--help`. The book folder layout is documented at the top of
`ebookify/scripts/common.py`.

## Repository layout

```
ebookify/                  the skill (this is what gets installed)
  SKILL.md                 workflow the agent follows
  references/              loaded on demand: transcript cleanup rules, interactive
                           block syntax and modes, per-source troubleshooting
  scripts/                 fetchers, builders, setup.sh, requirements.txt
  assets/                  EPUB stylesheet, pandoc Lua filters, HTML reader template
  evals/                   test cases (prompt + graders), `claude plugin eval` layout
tools/measure_outputs.py   measures EPUB/HTML outputs of an eval run for grading
```

`ebookify-workspace/` (eval runs) and `ebooks/` (your books) are git-ignored.

## Evaluating changes

`ebookify/evals/` holds four realistic tasks: a blog post to EPUB plus a study edition,
a YouTube explainer to EPUB, a podcast episode without a transcript (Whisper) to EPUB,
and a paper to a teaching slide edition. Each has graders that state checkable
properties. Run them with and without the skill, then compare. With Claude Code, from
inside `ebookify/`: `claude plugin eval . --allow-tools Write,Edit,Bash` (real, billed
model runs).
`tools/measure_outputs.py` extracts the objective numbers (word counts, code blocks,
headings, cover, inlined images, math, quizzes, notes) from a run's `outputs/`.

First benchmark (one run per configuration):

| | With skill | Without skill |
|---|---|---|
| Graded checks passed | 28/28 | 27/28 |
| Mean time | 224 s | 484 s |
| Mean tokens | 79k | 106k |

## Known limitations

- Transcripts lose visuals. For explainer videos the skill tells the agent to add a few
  captioned key frames, but picking them is manual.
- PDF equations that are drawn as images come out garbled and must be retyped as
  LaTeX. Complex tables and two-column layouts need hand fixes.
- Whisper does not tell voices apart. Speaker labels are inferred by the agent from
  context.
- Spotify-exclusive and other DRM-protected podcasts cannot be downloaded. Paywalled
  pages need the user's own access (render the page in a browser and pass the saved
  HTML).
- pandoc 2.9 renders `\mathrm{}` in MathML as italics in Chromium.

## Security

Everything fetched (page text, PDF text, captions, transcripts, feed URLs) is treated as
untrusted, because the output may be published:

- **Raw HTML.** Both builders run `assets/safe_media.lua` as the first filter, on
  pandoc's parsed document rather than on markdown text, so parser tricks don't get
  around it. Raw HTML/LaTeX is shown as plain text unless it is inside a
  `::: {.widget key="..."}` block whose key matches the random `widget_key` in
  `book.json`. Only the agent knows that key, so fetched text cannot create live
  widgets. In-document YAML metadata blocks are disabled, and the key is passed on the
  command line, which overrides anything in the text.
- **Embedded files.** Only files directly in `images/` and `data:image` URIs are
  embedded. Every other image, widget `src`/`srcset`/`poster`, and
  `<link>`/`<iframe>`/`<object>` tag is removed and reported, before pandoc fetches
  anything.
- **Links.** Only http(s), mailto and `#` targets survive; `javascript:`, `file:` and
  the like keep their text but lose the link.
- **Network.** URLs taken from content (feed enclosures and transcripts, page and cover
  images) must be http(s) and public. The address is validated at connect time, inside
  urllib3, and the connection goes to exactly the address that was checked, so DNS
  rebinding cannot swap it. Every redirect is checked, and a URL you typed stops being
  trusted once it redirects to another host. Set `EBOOKIFY_ALLOW_PRIVATE=1` to allow
  private addresses, for example behind a corporate proxy. RSS is parsed with
  `defusedxml`.
- **Reader page.** A content security policy allows only the page's own hashed inline
  scripts (hashed from the template and keyed widgets only, never from the assembled page)
  and cdnjs, with no `'unsafe-inline'`, and blocks network requests and
  remote images.
- Fetchers also escape raw HTML in fetched text as defense in depth. It only makes
  drafts read better; the filter above is what enforces safety.

## Legal

The skill makes personal reading copies. Copyright stays with the original authors.
Published artifacts start private; sharing a copy of someone else's work is the user's
decision and responsibility. The skill does not get around paywalls, DRM or logins.
