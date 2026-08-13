# The ask page, redrawn and taken apart

Date: 2026-08-13

## Why

`2026-08-12-project-ask-page-design.md` built the page. It works, and it
looks like a page assembled out of whatever was nearest: the head borrows
`.view-head` from `tree.css` and then fights it with two `!` overrides,
the thread is a bare flex column of Tailwind utilities with no measure cap,
and the composer is pulled out to the page edge with a negative margin while
the prose above it is not — so the two do not line up on any viewport.

Three specific faults, each visible in
`src/presentation/ask/__screenshots__/`:

1. **No measure.** An answer runs the full width of the surface. At 1440px
   that is a 1400px line of prose; the readable range is roughly 60–75
   characters and nothing here caps it. The head *is* capped, at 1100px by
   `.view-head` — which is why it was overridden to `max-w-none!`, making the
   page uniformly too wide rather than uniformly right.
2. **The speakers do not read as speakers.** A question is `font-semibold`
   with a 2px left rule; an answer is `--fg-dim` prose. On a long thread the
   two blur, because the only cue separating turn *n*'s answer from turn
   *n+1*'s question is a 16px gap.
3. **The facet links do not say where you are.** Course, Research and Ask are
   three states of one control, and the page renders two of them as quiet
   buttons and the third as nothing at all — the reader on Ask sees only the
   two places they are not.

And structurally: `AskView.tsx` builds the store *and* draws the page, so
nothing on this page can be put in Storybook without a container, a
repository fake and a `crypto.randomUUID`. `Turn` is a private const inside
`AskThread.tsx` — the most interesting component on the page and the one with
the most states, unreachable except through a whole transcript. There are no
stories at all.

## What changes

### 1. A stylesheet of its own

New `src/styles/ask.css`, imported from `index.css` after `composer.css`.
The page stops using `.view-head` entirely, which deletes both `!` overrides
and the browser test that exists only to defend them.

```
.ask                 the column; owns the viewport, does not scroll
.ask-head            full-bleed head: title + sub left, actions right
.ask-facets          Course / Research / Ask as one segmented control
.ask-thread          the one scroller
.ask-measure         the prose column: 72ch, centred — used by thread AND composer
.ask-turn            one exchange
.ask-question        the reader's words
.ask-answer          the model's
.ask-sources         the citation row
.ask-composer        bottom edge, full-bleed, inner content on .ask-measure
```

`.ask-measure` is the load-bearing one and the answer to fault 1. It is set
on the inner wrapper of both the thread and the composer, so the question box
sits under the column of prose rather than under the viewport. `72ch` against
`--sans`, not a pixel width — the cap should follow the font, and every
neighbouring cap in this repo (`1100px` in `tree.css`) is a pixel number
chosen for a tree rather than for prose.

Everything uses existing tokens. No new colours, no new spacing steps.

### 2. Speakers that read as speakers (fault 2)

The question gets a panel: `--bg-panel-2`, `--radius`, real padding, `--fg`
at normal weight. The answer stays unboxed prose but moves from `--fg-dim`
to `--fg` — dimming the *answer*, the thing the reader came for, was
backwards. The turn gains a top rule between exchanges rather than relying on
a gap.

The rejected alternative is chat bubbles alternating left and right. Two
speakers, one of whom is you, on a page that keeps nothing: bubbles buy a
speaker cue this page can get from a single panel, and cost it the full
measure on every answer.

### 3. The facet control (fault 3)

`Course / Research / Ask` become one `<nav>` of three links, Ask carrying
`aria-current="page"` and the current-state styling. Rendered by `AskHead`,
which takes `projectId` and nothing else. "New chat" moves out of that group
— it is an action, not a destination, and grouping it with three links was
the reason the group read as four unrelated buttons.

### 4. Components, taken apart

| File | Role |
|---|---|
| `AskView.tsx` | container only: builds the store, reads it, renders `AskPage` |
| `AskPage.tsx` | the whole page, presentational; props only |
| `AskHead.tsx` | title, subtitle, facet nav, new chat |
| `AskThread.tsx` | the scroller, the empty state, the map over turns |
| `AskTurn.tsx` | one exchange — question, activity, answer, error, pending, sources |
| `AskActivity.tsx` | the collapsed "looked at N things" fold, and `activityName` |
| `AskComposer.tsx` | unchanged props, restyled |
| `CitationList.tsx` | unchanged props, restyled |
| `ask-fixtures.ts` | turns and transcripts shared by stories and tests |

`AskPage` is the split that matters. Everything below it is a pure function
of props, so a story is `<AskPage {...args} />` with no container in scope —
which is what "storyable end to end" means and what the current file cannot
do at any price.

`ask-fixtures.ts` mirrors `course/course-fixtures.ts`, which exists for the
same reason: a transcript written out inline in five stories is five
transcripts that drift.

### 5. Stories

`AskPage.stories.tsx` — Empty, OneTurn, Streaming, Refused, LongThread.
`AskTurn.stories.tsx` — Answered, WithActivity, Streaming, Failed, NoCitations.
`AskComposer.stories.tsx` — Empty, Typed, Asking.
`AskHead.stories.tsx` — the facet control with Ask current.
`CitationList.stories.tsx` — None (renders nothing), One, Many.

`layout: 'fullscreen'` with a fixed-height decorator on `AskPage` and
`AskThread`, because the page's whole layout claim is that it fits a viewport
it does not choose — a story that lets it grow is showing something else.

## Testing

**`AskView.test.tsx` (jsdom) stays as it is.** It drives the real store
through the real repository port and asserts what a reader sees. It is the
guard that says this restructure changed drawing and not behaviour, and it is
worth more unmodified than rewritten. Its one coupling to markup —
`{ selector: 'article p' }` for the turn's error — survives, because a turn is
still an `<article>`.

**New `AskPage.test.tsx` (jsdom)** for what only the presentational split
makes reachable: that `aria-current` lands on Ask and not on Course, that
`onReset` fires from New chat, that an error banner and a failed turn are two
distinct nodes.

**`AskView.browser.test.tsx` (browser) is rewritten**, not deleted. Three of
its assertions are still the right ones and only their selectors move
(`div.overflow-y-auto` → `.ask-thread`, `form.composer` → `.ask-composer`).
The third test — "keeps the head full-bleed against the unlayered rule that
caps it" — is deleted with its subject: there is no `.view-head` on this page
any more and no `!` defending it, so the test would be asserting a rule
nothing sets.

In its place, the measurement this redesign actually makes a claim about:

- the thread's prose column is capped below the surface width and centred in
  it (fails today, where they are equal);
- the composer's inner column is left- and right-aligned with the thread's,
  within a pixel (fails today, where the composer is 40px wider each side).

Both are computed geometry, which is the stated bar for living in the browser
suite rather than in jsdom.

**Stories are exercised by the suite** through `composeStories`, per
`.storybook/main.ts`'s note that a story which compiles and throws is caught
by a test importing it and by nothing else.

## What is deliberately not done

- No streaming-cancel control. The store has no cancel and adding one is a
  store change wearing a styling change's clothes.
- No persistence, no scroll-to-bottom-on-new-answer, no copy button. Each is
  a feature; this is a redraw and a decomposition.
- `.composer` in `composer.css` is left alone. Ask stops using it, the session
  page still does, and rewriting a shared class from a page-specific redesign
  is how two pages come to disagree about what a composer is.

## Verification

All four gates, plus `npm run test:browser` — this change is a stylesheet and
a set of measurements, which is exactly the case `CLAUDE.md` names for the
fifth command.
