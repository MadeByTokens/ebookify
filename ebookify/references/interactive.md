# Interactive HTML editions

`build_html.py BOOK --mode MODE` produces one self-contained HTML file: reading column,
contents drawer, reading-progress bar, remembered position, text-size control, light
and dark theme, and a **Slides** button that shows one section per screen (arrow keys,
`N` toggles speaker notes, `Esc` exits). The same file works offline in any browser and
can be published as a Claude artifact.

What you add on top of the cleaned source text depends on the reader's goal. Write the
additions as pandoc **fenced divs** inside `chapters/*.md`; the template turns them into
interactive components. `build_epub.py` drops all of these blocks by default, so the
EPUB stays a faithful reading copy (`--keep-extras` keeps key ideas, summaries, steps
and pull quotes).

## Keep the source and your additions apart

The reader must always be able to tell the author's words from yours. Additions live
only inside the blocks below, never woven into the source paragraphs. Never present a
summary or quiz answer that the source does not support.

## Modes

| Mode | Purpose | What to add (in this order of value) |
|---|---|---|
| `read` | Comfortable reading | Nothing. Just the cleaned text. |
| `learn` | Study and remember | A `.keyidea` at the top of each chapter (1–3 sentences), 2–4 `.quiz` questions at the end of each chapter, a `.flashcards` glossary for terms of art, `.steps` for any process, a `.summary` at the end. Optionally one `.widget` where an animation really explains something better than text (a sorting algorithm, an orbit, a signal being filtered). |
| `teach` | Present to a group | Keep chapters short enough for one screen; split long chapters into several `##` sections (one per slide). Add `.notes` (speaker notes: what to say, questions to ask the room, timing) to each slide-sized section, a `.keyidea` per section, `.steps` for processes the presenter will walk through, and a few `.quiz` questions to ask the audience. |
| `entertain` | Enjoy it as a story | Drop caps happen automatically. Add a few `.pull` quotes (the most striking sentences, verbatim), and where the source is a video/podcast keep `[[t=..]]` links so readers can jump to the moment. No quizzes. |

## Block syntax

Key idea, summary, tip, plain note:

```markdown
::: keyidea
Attention lets every token look at every other token, so order has to be added
separately.
:::
```

Quiz (`answer` is the 1-based number of the correct option; `.explain` is shown after
answering, cite the chapter or timestamp):

```markdown
::: {.quiz answer="2"}
Why do transformers need positional encodings?

1. To reduce memory use
2. Because attention by itself ignores word order
3. To speed up training

::: explain
Attention treats its input as a set; the speaker explains this at [[t=372]].
:::
:::
```

Flashcards (pandoc definition list; one card per term):

```markdown
::: flashcards
Positional encoding
:   A vector added to each token embedding that tells the model where the token is.

Self-attention
:   Each token computes a weighted mix of all tokens in the sequence.
:::
```

Steps (shown in full at rest; a "Walk through step by step" button reveals them one by one):

```markdown
::: steps
1. Embed each token.
2. Add the positional encoding.
3. Compute queries, keys and values.
:::
```

Speaker notes (hidden while reading; shown in slide mode with `N`):

```markdown
::: notes
Ask the room: who has seen a sine wave used as a clock? Spend ~2 minutes here.
:::
```

Pull quote (entertain mode; verbatim from the source):

```markdown
::: pull
"We didn't set out to build a language model. We set out to fix translation."
:::
```

Widget: a small self-contained animation or interactive diagram. **Raw HTML only works
inside a widget block that carries this book's key**: `::: {.widget key="KEY"}`, where KEY
is `widget_key` from `book.json`. Everywhere else, raw HTML is shown as plain text,
because the book's text comes from untrusted sources. (So write formatting in markdown,
such as `^2^`, `~x~` and `*em*`, never `<sup>` or `<br>`.) The builders strip the key
from the output.

The reader page has a strict content security policy. Scripts run only if they are
inline `<script>` blocks in the page (the build hashes each one) or loaded from cdnjs
(pin an exact version). Inline event attributes like `onclick=` never run, so attach handlers
with `addEventListener`. Images load only as `data:`/`blob:`, and fetch/XHR to any host
is blocked. Rules: draw with canvas or inline SVG,
read colors from the CSS variables (`var(--accent)`, `var(--ink)`, `var(--paper)`)
via `getComputedStyle` so it works in light and dark themes, respect
`prefers-reduced-motion`, start in a visible, meaningful state (not a blank canvas
waiting for a click), and keep it under ~80 lines. Give ids a unique prefix.

```markdown
::: {.widget key="WIDGET_KEY_FROM_BOOK_JSON"}
<canvas id="w1-wave" width="640" height="160" aria-label="Sine waves of increasing frequency"></canvas>
<button type="button" id="w1-play">Pause</button>
<script>
(function () {
  /* draw using getComputedStyle(document.documentElement).getPropertyValue('--accent');
     document.getElementById("w1-play").addEventListener("click", ...) */
})();
</script>
:::
```

Only build a widget when it teaches something the text cannot; one good widget beats
five decorative ones. For charts follow the user's charting conventions if any.

## Delivering the HTML

1. Run `build_html.py`, read its JSON report (size, number of blocks, problems).
2. Open the file once (e.g. a single browser screenshot if a browser tool is available)
   and fix anything visibly broken. Do not loop on polishing.
3. **As a Claude artifact**: if a tool for publishing artifacts is available (for
   example `publish_files` from the claude-artifacts server, or the built-in artifact
   feature in the Claude apps), publish the HTML file with the book title as the title
   and a short generic icon word such as `book`. Read that tool's guide first if it has
   one. Artifacts start private to the user; say so, and remind them that sharing a copy
   of someone else's work is their call. Artifacts load only from the allowed CDNs
   (cdnjs, jsdelivr, unpkg, Google Fonts); remote images do not load, which is why
   `build_html.py` inlines everything. Limit: 16 MiB.
4. **As a local file**: the `.html` in `BOOK/out/` works offline (fonts fall back to
   Georgia/system fonts without a connection). Give the user its absolute path.
