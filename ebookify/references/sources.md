# Source-specific notes and troubleshooting

## Web pages (`fetch_web.py`)

- Multiple URLs in one call become consecutive chapters of one book (in the order given).
  For a series or blog archive, collect the article URLs first, then pass them all.
- "SUSPICIOUSLY SHORT" means extraction probably hit a paywall, cookie wall or a
  JavaScript-rendered page. Look at `raw/NN/page.html`. If the article is not in it,
  render the page with a browser tool (Playwright, the built-in browser, Chrome),
  save the rendered HTML to a file, then run
  `fetch_web.py BOOK --html saved.html --url ORIGINAL_URL`.
  Remove the failed source first (delete its `sources/NN.json` and `draft/NN-*.md`).
- Do not bypass paywalls or logins the user has no access to. If the user is logged in
  through a browser tool, using the page they can see is fine.
- Cleanup for web drafts is usually small: remove leftover "Share this", newsletter
  boxes, "Related posts" lists, comment sections, and duplicated title/byline lines.
  Do not edit the author's prose.
- Multi-page articles ("Page 2 of 5"): fetch each page URL and merge the drafts into one
  chapter file.

## PDFs (`fetch_pdf.py`)

- Papers and reports: one draft file. Books with real `#` chapter headings: one file per
  chapter (decided automatically).
- Check the draft for: headings detected from font sizes (sometimes a bold sentence
  becomes a heading, or real headings are missed); hyphenated line breaks
  ("elec- tricity"); footnote numbers glued to words; tables flattened into text;
  two-column layouts interleaved. Fix structure, never wording.
- Academic papers: keep the abstract, put references at the end under `## References`,
  keep equations (LaTeX `$...$` renders as MathML in both EPUB and HTML).
- Equations set as images in the PDF come out as garbled "picture text" blocks
  (lines ending in `<br>` followed by `<!-- End of picture text -->`). Retype each one
  as LaTeX from the garbled text and the figure image, and delete the garbled block.
- Check that every figure in `images/` is referenced from the draft and sits next to
  its caption. Small decorative images can be dropped.
- Scanned PDFs are detected automatically (very little text per page) and sent to
  `marker_single` OCR if installed. OCR output needs a closer proofread.
- Very large PDFs: use `--pages` to test on a slice first.

## YouTube (`fetch_media.py URL`)

- Captions are preferred: manual subtitles, then automatic captions in the video's
  original language (`--lang` to choose). Whisper runs only when neither exists, or
  with `--whisper`. Whisper quality is noticeably better than auto captions for
  technical talks; offer `--whisper` if the auto-caption draft is very garbled.
- Chapters from the video description become chapters of the book.
- Playlists: list the video URLs (`python -m yt_dlp --flat-playlist --print url PLAYLIST`
  with the venv python), then run `fetch_media.py` once per video. Each video becomes
  one source and one or more chapters.
- If yt-dlp fails with "Sign in to confirm you're not a bot" or format errors, update it
  (`bash scripts/setup.sh --upgrade`) and retry once. Do not try to evade blocks.
- Visuals: a talk or explainer that relies on slides, diagrams or animation loses them
  in a transcript, and the text then says "this", "here" and "as you can see". For
  such videos, add a handful of key frames (about 1 per chapter, more for dense
  visual explanations): download a small copy
  (`$PY -m yt_dlp -f "bv*[height<=480]" -o raw/NN/video.%(ext)s URL`), grab candidates with
  `ffmpeg -ss <seconds> -i raw/NN/video.* -frames:v 1 images/NN-frame-<seconds>.jpg`
  at the moments the speaker refers to, look at them, and insert the useful ones as
  figures with a one-line caption (`![Caption](images/NN-frame-512.jpg)`). Keep the
  speaker's words unchanged; the figure supplies what "this" refers to. Mention in
  `notes` that frames were added.

## Podcasts (`fetch_media.py --feed RSS` or an episode/audio URL)

- Find the RSS feed: on the show's website (look for "RSS"), or the Apple Podcasts page
  (yt-dlp also handles Apple Podcasts episode URLs directly). Spotify-exclusive shows
  are DRM-protected and cannot be downloaded; say so.
- `--list-episodes` shows the newest 50 episodes and which have publisher transcripts.
  Publisher transcripts (Podcasting 2.0 `podcast:transcript`) are used automatically and
  often include speaker names.
- Episode show notes are kept in `sources/NN.json` (`description`); useful for speaker
  names, spelling of guests, and links. Put useful links from show notes in a short
  "Links from the show notes" section at the end of the episode, marked as such.
- Whisper runs with voice-activity detection, which sometimes skips real speech. The
  fetcher re-transcribes long unexplained gaps without it and logs "recovered N words".
  If the drafts still have a suspicious jump in `[[t=..]]` markers (more than ~30 s
  with no ad break), mention it to the user.
- An hour of audio is ~9,000–10,000 words. Whisper on a GPU (large-v3-turbo) takes a few
  minutes per hour; on CPU (small model) expect roughly real time or slower, so warn
  the user before transcribing long episodes on CPU.

## Several sources in one book

Run the fetchers in order against the same `BOOK` folder. Then edit `book.json`:
give the collection a real title ("Talks on Transformers, 2024"), set `author` to the
creators (or "Various"), and update `description`. Every source should start with its
own `# Title` line so each one is a chapter.
