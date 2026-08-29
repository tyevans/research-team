# The lesson slideshow

A second reading of an authored lesson: the same document, paced.

Written before any of it was built, because the whole of the design is one
question — *where do slides come from* — and answering it after writing a
renderer means the renderer picks the answer.

## 0. What I checked, and what I assumed

**Read in source, by me.** `research_team/application/components.py`'s parser
and projection; `frontend/src/domain/lesson/document.ts`;
`presentation/lesson/LessonDocument.tsx` and `widgets.tsx`;
`presentation/curriculum/{CourseFile,CourseUnit,CoursePage}.tsx`;
`presentation/routing/{routes.ts,use-route.ts}`;
`presentation/layout/OverlayHost.tsx`; `styles/{theme.css,tokens.css,index.css}`;
`scripts/check-deleted.mjs`.

**Measured, not reasoned.** The four lesson files this design is tested against
are **real authored output**, lifted from the `FileWritten` events in
`~/.research-team/sessions.db` on 2026-08-29 and checked in verbatim at
`frontend/src/domain/lesson/fixtures/`. Their shape is what the segmentation
rule is fitted to, and their shape is stated in §2. Nothing here was fitted to
a lesson I wrote myself, which is the failure CLAUDE.md's "checkpoints over
model output" section describes: a fixture written in the same hour as the rule
supplies the contract the rule was supposed to discover.

**Not verified.** How a deck *feels* to present from. One person read it in a
browser at 1440×900 and took the screenshots in `lesson-slideshow/`; that is one
machine and one pair of eyes.

**Found while building, and worth its own line because it is not about this
feature.** `renderMarkdown` adds a class to exactly one kind of node — links —
so `markdown.css`'s `.md-p`, `.md-quote`, `.md-list` and `.md-h` rules match
nothing that renderer produces. The first draft of `SlideView` styled through
them and every utility was silently inert. That is a whole family of dead rules
in a live stylesheet, and it is filed here rather than fixed: it is somebody
else's slice and it deserves a measurement of its own.

## 1. The decision: slides are derived, and nothing is authored

**A deck is a pure function of the already-parsed document.** No new syntax, no
new prompt, no field on the wire, no migration. Every lesson ever authored — the
three in `agent-interaction-log`, the three in `knowledge-graph`, everything a
`lesson-drafter` writes tomorrow — has a deck the moment this merges.

### What the alternative would have bought, and what it costs

Authoring slides explicitly (a `---` separator, a ````component:slide``` fence,
a `slides:` block in frontmatter) buys **better decks**: an author decides what
lands together, what gets a page of its own, and where the beat is. Derivation
cannot know that a paragraph is a punchline.

It costs four things, and the fourth is what settled it:

1. **A migration.** Every existing lesson is a lesson with no deck until
   somebody rewrites it. The catalog's realized courses are the only content
   this console has.
2. **A second contract with a language model**, of exactly the shape CLAUDE.md
   spends a section on. The renderer would assert on a marker; the prompt would
   have to demand the marker; the pair would have to be a constant and a test.
   Three of those pairs have already been got wrong in this repository, twice
   after the entry warning about it was written.
3. **A second source of truth for one document.** A lesson that reads well and
   presents badly is now two artifacts to keep in agreement, and the failure is
   silent — the deck is simply out of date with the prose beside it.
4. **It is not reversible in the direction that matters.** Deriving now does not
   forbid authoring later: an explicit marker, when someone wants one, becomes
   an *override* on a segmentation that already has a defined answer for every
   document. Authoring now does forbid deriving later in practice, because once
   authors are writing breaks the derived rule stops being tested by anything.

So: derive. State plainly what is given up — **the deck's pacing is a
mechanical consequence of the prose's shape, and a lesson written as one
unbroken argument will present as a small number of dense slides.** That is a
true rendering of that lesson rather than a flattering one, and the document
view is one keypress away.

### What was also rejected

- **A deck built from the course *outline*** (`CourseDetail.outline`, which is
  already headings plus summaries). It would make a beautiful deck of a
  document nobody is reading: the outline is the pitch that a realized course
  *replaces* — `CoursePage` says so, and deliberately shows one or the other.
  A deck of the outline beside a document of the lesson is exactly the "two
  descriptions of one course, disagreeing" that decision rejected.
- **Slide identity by component id.** Widgets have stable ids; prose does not,
  so half the deck would be unlinkable. Index it is, with the cost named in §4.

## 2. The material, as it actually is

From the four checked-in fixtures, which are four of the ~14 lesson and unit
files this system has ever produced:

- Frontmatter (`title`, `area`, `builds_toward`), which the server strips before
  the client sees it. **The client never receives the title**, so the deck's own
  title comes from the document's first `#` heading.
- **Three of the four fixtures open with an H1; one does not.**
  `agent-interaction-log-lesson-02.md` opens with prose and its first heading is
  an `##`. That was found by running the rule over the corpus rather than by
  reading it — the first draft of this section asserted every lesson has an H1,
  and the test that asserted it went red. So the deck's title is nullable, a
  deck without one simply has no title slide, and the view falls back to the
  lesson's file name for its accessible name. Nothing prompts for an H1 and
  nothing should start to on the strength of a slideshow.
- Two to seven `##` sections after that.
- Paragraphs that are genuinely long. Measured over the 44 prose paragraphs in
  the three lesson fixtures: median **379** characters, longest **725**,
  shortest 33. A slide budget tuned to bullet lists would put one paragraph on
  four slides.
- Blockquotes carrying a cited passage, usually alone in their paragraph.
  These are the pull-quotes; the prose around them says "here is the passage".
- Two to four `component:` fences, each under an H2 whose text introduces it
  ("Meet the material", "Check for understanding", "Retrieval practice").
- `[[src:…]]` citation references inline in the prose, expanded by `Markdown`.

## 3. The segmentation rule

`deckOf(document)` in `frontend/src/domain/lesson/slides.ts`. Pure, no React,
no DOM, no `window`. `slides.test.ts` runs it over the four fixtures.

1. **Walk the blocks in order.** A markdown block is scanned for ATX headings
   at the start of a line, *outside fenced regions* — a non-component fence
   survives inside a markdown block, and a `# ` inside a shell example is not a
   heading.
2. **A heading opens a section.** H1 opens the deck's title section; H2 and H3
   open a section each. H4 and below are content, not structure: nothing in the
   corpus uses them and promoting them would make a deck out of a footnote.
3. **A section's prose is packed into slides at a paragraph boundary and never
   inside one.** Paragraphs accumulate until the next one would take the slide
   past `SLIDE_BUDGET` (900 characters, argued below). A single paragraph over
   budget is its own slide, whole. **Prose is never cut mid-sentence**, which is
   the one rule here that is not a tuning parameter.
4. **A blockquote paragraph always starts a slide and ends it.** It is the
   pull-quote, and it is the one place the deck spends its display type. This
   is a real judgement about this corpus rather than a general rule: a cited
   passage is what these lessons are built on.
5. **A component block is always its own slide**, carrying the enclosing
   heading as its eyebrow. Never packed with prose — a quiz that shares a slide
   with the paragraph explaining it is a quiz whose answer is on screen.
6. **Continuation slides repeat the section heading, marked.** A section that
   takes three slides prints its heading once, at full weight, and the two
   continuations carry it small in the eyebrow. A reader who joins at slide 9
   still knows where they are.

**`SLIDE_BUDGET = 900`** was picked by running the rule over the four fixtures
at 600, 900 and 1,200 and reading the decks: 600 splits three-sentence
paragraphs' natural pairs apart, 1,200 puts two long paragraphs on one slide and
overflows the measure at 1440×900. It is a tuning constant, it is named, and
`slides.test.ts` asserts the *properties* that must hold at any budget (never
mid-paragraph, a component is always alone, every block reaches exactly one
slide) rather than a slide count that would freeze the number.

**Speaker notes are opt-in and nothing writes them today.** An HTML comment
`<!-- notes: … -->` in a markdown block is lifted out of the visible prose and
onto the slide it sits in. Stated plainly because it is the shape CLAUDE.md
warns about: **no prompt asks for this, so it is inert on every lesson that
exists.** It is not a checkpoint — a lesson with no notes renders a deck with no
notes and nothing fails — so the "half a contract" failure cannot happen here.
Teaching `lesson-drafter` to write them is a separate change in the authoring
workstream, and this is the reader half waiting for it.

**The rule is total.** A document with no headings is one section of packed
prose. A document of one component is one slide. An empty document is an empty
deck, which the view answers with an empty state rather than an error.

## 4. The route

`?deck=<path>&slide=<n>` on the hash, read by `useDeck()` — the precedent is
`?t=` and `useSeekSeconds()`, whose docstring makes the argument this reuses:
a query parameter that applies to one facet does not belong in the `Route`
union, because every other route's reader then has to guard a field that cannot
apply to it.

Deep-linkable, which is the requirement: `#/p/abc/course/knowledge-graph?deck=/course/areas/knowledge-graph/lesson-01.md&slide=7` opens
that lesson's deck at that slide. Navigation within the deck **replaces** rather
than pushes, for the reason scrubbing does: arrowing through thirty slides
should not leave thirty entries in the back stack, and the position must still
be in the URL.

**The cost of indexing by position, stated:** re-author a lesson and every link
into its deck moves. The alternative — a slug per slide derived from its
heading — moves too (headings get rewritten), costs a collision rule for two
sections with the same words, and is unlinkable for prose slides after the
first. An out-of-range index clamps to the last slide rather than failing the
route, because a stale link should land somewhere in the lesson.

## 5. The view, and the two things it must not break

**The deck is a modal `Overlay`, not a route that replaces the page.** That
gives it, from one primitive already in the tree: Escape to the topmost layer
only, focus moved in and given back on close, and the page behind marked
`inert`. Hand-rolling any of that is the defect `component-system-spec.md` §2
opens with.

**Accessibility.** The document view stays exactly as it is, and is the
baseline. The deck adds:

- Each slide is a `section` with an accessible name, inside a
  `role="group" aria-roledescription="slide"` region.
- **Every slide is in the DOM**, not just the current one. Off-slides are
  `hidden`, so a screen reader's virtual cursor gets the current slide's whole
  content and nothing else — rather than the whole lesson, which would defeat
  the pacing, or a live-region announcement of a slide the reader cannot then
  navigate.
- Arrows, `PageUp`/`PageDown`, Space, `Home`/`End`, `Escape`, and `o` for the
  overview. Every one of those also exists as a control: the rail is a real
  list of real buttons, so nothing is keyboard-only or pointer-only.
- The interactive widgets are the same components, mounted normally. A quiz on
  a slide is a quiz. This falls out of rendering the same `ComponentBlock`
  through the same registry, and `deck-widgets.test.tsx` holds it — a widget
  that renders but cannot be answered would pass a snapshot and fail a reader.
- Keyboard handling is on the deck container and skips events originating in a
  form control, so typing a space into a cloze input does not advance the
  slide. That is a browser-visible failure with a jsdom-visible cause, so it is
  asserted in jsdom.

**The cascade.** Per CLAUDE.md, and this surface is exactly where those entries
bite:

- **No new stylesheet.** `check-deleted.mjs` freezes the set of 21, and the
  stated policy is that stylesheets die with the screens they dress. The deck
  is Tailwind utilities throughout.
- **No raw `<button>`.** `tokens.css` gives bare `button` an unlayered
  background, colour and `font: inherit`, which beats every utility — the
  defect that painted every catalog card blank. Every control here is the
  `Button` primitive or an `<a>`.
- **Focus rings** use `.lay-ring-inward` where a ring would clip, rather than a
  `focus-visible:outline-offset-*` utility that the unlayered global
  `:focus-visible` would silently beat.
- **Directional borders** are written `border-0 border-l-2 border-solid`, never
  `border-solid` beside a directional width alone, and never `border-0 border`.
- **The type is set on `p`/`blockquote`, not on the `Markdown` element.** `.md`
  carries an unlayered `font-size`, `line-height` and `padding`, so a `text-` or
  `p-0` utility there is inert. The wrapper takes `.doc`, which
  `structure.css` turns into `display: contents`, and the type lands on the
  descendants where the only thing to beat is inheritance.
- **The measurements are browser tests.** `deck.browser.test.tsx` asserts the
  things jsdom cannot see: that a slide fills the viewport, that the rail's
  current tick is the accent and not the dim tone, and — with
  `document.elementFromPoint` rather than `getBoundingClientRect`, which is the
  correction CLAUDE.md's most recent entry makes — that the slide's own content
  is the thing painted at the centre of the deck rather than something opaque
  above it.

**The screenshots**, all at 1440×900 in Chromium on 2026-08-29, from the
Storybook stories in `Deck.stories.tsx`:

| | |
|---|---|
| `lesson-slideshow/deck-title.png` | the title slide and the rail |
| `lesson-slideshow/deck-prose.png` | a section, its heading at full weight |
| `lesson-slideshow/deck-quote.png` | the pull-quote, which is the risk |
| `lesson-slideshow/deck-question.png` | a live quiz on a slide |
| `lesson-slideshow/deck-overview.png` | the jump list |

## 6. Visual direction

The console's own vocabulary, spent in one place.

**The signature is the ledger rail.** A fixed left column, one row per slide,
drawn as this console draws an event log: a monospace index, a hairline tick,
and the section name printed once at the section's first slide. The current
slide's tick is the accent and full width; the rest are `--line`. It is
simultaneously the progress indicator, the jump list and a claim about what a
lesson is here — everything in this system is folded from an ordered log, and
the reader already reads a scrub bar for sessions. So the deck's progress
affordance is a **scrub**, not a row of dots.

That is also the rejection: reveal.js's centred text, bottom-centre dot row and
one-bullet-per-line are the shape being avoided, and a bottom progress bar would
have been the same idea with less information in it.

**Type.** Nothing new is introduced. `--sans` for prose at a 62-character
measure, left-aligned rather than centred — these are paragraphs, not bullets,
and centred paragraphs are unreadable. `--mono`, uppercased and tracked wide,
for every structural label: the eyebrow, the slide index, the component kind.
The one display voice is `--font-serif`, already in `theme.css` and used
nowhere, at the title slide and at pull-quotes only. Amber on near-black with a
Georgia pull-quote is not the cream-and-terracotta default; it is this console's
palette with its own unused third face finally spent.

**The risk taken:** the pull-quote slide sets its passage in serif at roughly
2.4× body with a hanging accent bracket in the rail's gutter and **no quotation
marks** — the citation beneath it in mono is what marks it as quoted. It is the
one slide kind that looks unlike the rest of the console, and it is the kind
that earns it: a cited passage is the load-bearing material of every lesson
here.

Everything else is disciplined: one accent, no gradients, no shadow except the
existing `--shadow-1` on the overview, no entrance animation. Both colour
schemes work because every value is a token.

## 7. What this does not do

- **It does not present the unit.** `unit.md` is a plan — enduring
  understandings, essential questions, knowledge and skills — and its deck
  would be a deck of a table of contents. `CourseFile` offers the deck for
  lessons; the unit renders as it does now.
- **It does not print or export.** A PDF path is a real want (`docs/deck/`
  holds an earlier experiment that went to `.pptx`) and it is a separate piece
  of work whose hardest part — a widget that cannot fetch — is exactly what
  `ComponentBlock.resolved` was kept for.
- **It does not remember where you were.** Reopening a deck starts at slide 1
  unless the URL says otherwise. Progress belongs to the attempt record, which
  already exists and is per-widget.
- **It has no presenter window.** Speaker notes are shown in place, toggled, on
  the presenter's own screen. A second-window presenter view needs a broadcast
  channel and a second layout for content nothing authors yet.
