# Cleaning transcripts into readable chapters

Raw transcripts read badly: automatic captions have no punctuation or capitals, Whisper
runs sentences together, and every talk is full of "um", "you know", false starts and
"so, yeah". The aim is text that reads like a well-edited interview transcript: **the
speaker's own words and voice, minus the noise of speech**. A reader should never
wonder "did they really say that?" and get the answer "no".

## What to change

- **Punctuation and capitals.** Add sentence breaks, commas, question marks, quotes.
  Auto captions (flagged by `fetch_media.py` as "NO PUNCTUATION") need this everywhere.
- **Filler and disfluency.** Remove um/uh/er, "you know", "like" used as filler,
  "sort of/kind of" when they carry no meaning, stutters ("the the"), and false starts
  ("we went to, we drove to the lab" -> "we drove to the lab").
- **Paragraphs.** One idea per paragraph, usually 3–7 sentences. The draft paragraphs
  are split by pauses, not by meaning; regroup freely.
- **Obvious mis-transcriptions.** Fix words that are clearly wrong from context,
  especially names and technical terms ("pie torch" -> "PyTorch"). Use the video
  title, description and chapter titles (in `sources/NN.json`) as a spelling guide.
  If you are unsure, keep the original and mark it `[?]`.
- **Headings.** Keep the creator's chapter titles when they exist. When there are none
  (the draft says "add topic headings while cleaning"), add a `##` heading at each real
  topic change, every ~800–2000 words; use short, descriptive titles, not clickbait.
- **Speakers.** For interviews/podcasts, label turns with `**Name:**` at paragraph
  start once you can tell who is speaking (from the intro, the description or the
  transcript's speaker field). If you cannot tell, use `**Host:**` / `**Guest:**`
  only when it is unambiguous; otherwise leave turns unlabeled.

## What not to change

- Do not summarize, condense, reorder arguments, or "improve" phrasing. Light cleanup
  keeps sentences; it does not rewrite them. If the speaker repeats a point, keep it.
- Do not add facts, explanations, or links that are not in the source. Additions for
  learning/teaching modes go in clearly marked blocks (see `interactive.md`), never
  mixed into the speaker's text.
- Drop only content that is not part of the talk: sponsor reads, "like and subscribe",
  Patreon shout-outs, housekeeping like "can everyone hear me". If you removed any,
  say so in `book.json` `"notes"` (for example "Sponsor reads and the Patreon thank-you
  were removed."); the About page prints it.
- Keep `[[t=SECONDS]]` markers. Leave the marker that begins each paragraph you keep
  (when you merge paragraphs, keep the first marker; when you add a heading, the next
  paragraph should still start with a marker). The builders turn these into small
  clickable timestamps, or strip them with `--timestamps strip`.

## Workflow

1. Read `sources/NN.json` (title, creator, description, chapters, transcript_method).
2. Process the `draft/NN-*.md` files **one at a time**, in order. For each, write the
   cleaned text to `chapters/<same filename>`. One file is ~2500 words, which fits
   comfortably in a single careful pass. Do not try to hold the whole transcript in a
   single output.
3. Keep the first file's `# Title` line. Part files (`-part2`) continue the previous
   chapter: do not repeat the chapter heading.
4. For very long material (more than ~10 draft files) and when subagents are available,
   you may hand out batches of files to parallel workers. Give each worker this file's
   path, the source json, and the list of names/terms you have already settled, so
   spelling stays consistent across chapters.
5. Spot-check: compare the word count of `chapters/` with `draft/`. Light cleanup
   usually removes 5–15% (mostly filler). Much more than 20% means you condensed.

## Example

Draft (auto captions):

```
[[t=372]] so um the thing about uh transformers is that they they don't really have a notion of order right so you have to add that in yourself and that's what positional encodings are for and
[[t=391]] the original paper used these sine waves which is kind of a neat trick
```

Cleaned:

```
[[t=372]] So, the thing about transformers is that they don't really have a notion of
order, right? You have to add that in yourself, and that's what positional encodings
are for. The original paper used these sine waves, which is kind of a neat trick.
```
