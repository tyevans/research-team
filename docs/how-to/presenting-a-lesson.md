# Present a lesson

Every authored lesson has a deck. This page shows you how to open it, move
through it, and link somebody to one slide.

You do not have to prepare anything. Slides are derived from the lesson's own
prose, so a lesson written before the slideshow shipped has a deck too.

## Open the deck

1. Open a project's course page in the console.
2. Open any lesson file.
3. Press **Present this lesson**.

The deck opens over the page you were on. Closing it lands you exactly where
you were, including any filter the page carried.

A lesson with no parsed blocks has no button. It renders as ordinary markdown,
exactly as it did before.

## Move through it

| Key | Effect |
|---|---|
| `→`, `↓`, `Page Down`, `Space` | Next slide |
| `←`, `↑`, `Page Up` | Previous slide |
| `Home` | First slide |
| `End` | Last slide |
| `O` | Toggle the overview |
| `Escape` | Close the deck |

**A widget owns its own keys.** Space inside a cloze blank types a space, and
the arrow keys inside a flashcard belong to the flashcards. The deck only acts
on a key when you are not typing.

## Link to one slide

The deck is in the URL:

```
#/p/<project>/course/<area>?deck=/lesson-01.md&slide=7
```

Slides are numbered from 0. The first slide omits `slide=` entirely, so it has
one spelling rather than two.

Moving between slides replaces the history entry rather than adding one, so
`Back` leaves the deck instead of walking back through every slide you saw.

**A slide number is a position, not a name.** If the lesson is re-authored, an
old link lands at whatever is now in that position. A number past the end
clamps to the last slide rather than failing — a stale deep link into a
re-authored lesson should land somewhere in it.

## What you get, and what it costs

A slide is one of four kinds, and the kind is a decision the segmenter already
made rather than a hint the view interprets:

- **title** — the H1, with any prose before the first heading.
- **prose** — packed paragraphs.
- **quote** — a blockquote alone in its paragraph. These lessons are built on
  cited passages, and this is the one place the deck spends display type.
- **component** — an mcq, cloze, flashcard or one of the graph-resolving
  widgets, on a slide of its own.

Headings become sections. A section spanning three slides prints its heading at
full weight once and small twice, so a reader who joins at slide 9 still knows
where they are.

**The cost of deriving rather than authoring**: pacing is a mechanical
consequence of the prose's shape. A lesson written as one unbroken argument
presents as a few dense slides, and there is no way to override that from the
lesson file. What is bought is that there is one source of truth for what a
lesson says, no new syntax, no new prompt, and no migration.

Presenter notes are read from `<!-- notes: ... -->` comments. **Nothing writes
them yet.** Every lesson that exists today has none. This is the reader half
waiting for the writer half.

## Where to read more

[`docs/design/lesson-slideshow.md`](../design/lesson-slideshow.md) argues where
slides come from and lists the alternatives that were rejected.
`frontend/src/domain/lesson/slides.ts` is the segmentation rule itself, kept
out of the React tree so it can be tested against four real authored lessons
without rendering anything.
