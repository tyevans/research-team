# Increment C, slice 3b — a stylesheet finally dies, and the fix that killed it was never applying

## The headline

**`research.css` is deleted, and `STYLESHEETS` goes from 22 to 21 — the first
entry to leave since the array was frozen.** Three slices in a row predicted a
stylesheet's death and three in a row failed, each for the same reason: what
remained belonged to a region the slice did not own. This slice owned all three
remaining families (the topic cluster, the graph, the seed form) and they were
the whole file, so the deletion is arithmetic rather than luck.

**The finding that matters more is not in the plan at all: slice 3a's inward
focus-ring fix has never applied, on any row, since the commit that shipped it.**
Two agents found it independently — one from the topic list, one from the graph
— and both measured it rather than reasoning about it.

`tokens.css`'s global `:focus-visible { outline-offset: 1px }` is **unlayered**.
Tailwind emits utilities into `@layer utilities`, and an unlayered normal
declaration beats a layered one regardless of specificity, so
`focus-visible:outline-offset-[-2px]` at (0,2,0) loses to a bare `:focus-visible`
at (0,1,0). The class was in the attribute, the rule was in the bundle, and the
computed offset was `+1px` everywhere. Measured in Chromium at 1440×900, the
ring's reach with the constant **absent** and with the constant **present** is
byte-identical: `-3..343 × 72.5..303` against a clip of `0..340 × 75.5..300.5`.

`DocumentBrowser.browser.test.tsx` was red on `main` — 3 of its 4 tests — and
slice 3a reported that measurement as carried across intact. It had not been
run. This is the second time in three slices that the *specific* hazard 3a
itself wrote down ("an unlayered rule beats `@layer utilities`") has bitten the
commit that wrote it.

The fix is `.lay-ring-inward` in `layout.css` — a rule, not a utility, at
(0,2,0) against the global's (0,1,0), both unlayered, so the cascade makes the
comparison it is meant to make. A trailing `!` also works and was rejected:
it leaves every future inward ring one forgotten character from the identical
silent failure, and gives the measurement nowhere to live. `CLAUDE.md` now
carries the general rule.

## What was rewritten

Five parallel tasks; each has its own report with the detail.

| Task | Files | Class names removed | Report |
| --- | --- | --- | --- |
| A — topic cluster | `TopicQueue`, `TopicDocuments`, `SubQuestions`, `TopicList` | 25 | `slice-3b-task-a.md` |
| B — `topic` facet + demodalisation | `ProjectView`, `TopicList`, `use-topic-queue`, `TopicManagePane` | 8 | `slice-3b-task-b.md` |
| C — graph cluster | `GraphPane`, `GraphCanvas`, `GraphDetail`, `GraphLegend` | 35 | `slice-3b-task-c.md` |
| D — seed form | `SeedForm` | 6 | `slice-3b-task-d.md` |
| rename | `TopicStatusDialog` → `TopicManagePane`, 14 files | — | `slice-3b-rename.md` |

Plus this task: the deletion, the `check-deleted.mjs` bookkeeping, and the gates.

## Three things the plan got wrong, all found by building it

1. **`sub-question-resolve` is dressed, not bare.** The plan called it one of
   four undressed names. It is the *first selector of a grouped rule*, and the
   grep that produced the list matches `^\.name {` — **a grouped selector's
   second-and-later members never match that shape**. So the method finds
   dressed names that are bare and calls dressed names bare, in both directions.
   Worth knowing because that grep will be run again.
2. **The count of undressed names was wrong in the other direction too**:
   `topic-documents` is a fifth the plan missed, and `TopicManagePane` wrote six
   class names where the brief named two.
3. **§5.2's "1px of slack, marginal rather than broken"** for the two graph
   scrollers was correct arithmetic on a false premise — it measured 4px of
   padding against a `-2px` offset that was never in force. Against the actual
   `+1px`, both were clipped by 2px per side. The recommendation was right
   anyway, for the wrong reason.

## Two decisions taken against the brief, and why

**z-index (task C).** The brief asked for a precedent to follow; there is none —
this is the first migrated element in the codebase that needs a stacking order.
Tailwind will generate `z-[var(--z-sticky)]`, which satisfies the letter of what
`stacking.test.ts` asks for and reopens the exact hole that test exists to close:
`SOURCES` is `readdirSync('src/styles')`, so a utility lands in an asset the
sweep never opens, and `z-[40]` in a `className` would be reachable again with a
green build. So the rewrite stopped one declaration short: `.lay-region-float` in
`layout.css` declares `z-index: var(--z-sticky)` and nothing else. **The honest
consequence: "`research.css` is dead" does not mean the graph is 100% utilities.
It is 35 rules replaced and one three-line rule that moved house.**

**Two spellings of the ring fix** existed briefly — task A's `!` and task C's
class. Unified on the class; the geometry was re-measured after the swap and is
identical (`0..340 × 75.5..300`).

## Demodalising the topic panel — what it cost

`TopicManagePane` is a `<section>` in the QUEUE column, not a `Drawer`. What is
lost is **modality, not the keyboard contract** — the hand-rolled focus trap was
already deleted in phase 1. The real cost, stated plainly: **the page can now
take a click while a half-written justification is on screen**, and a reader who
types two sentences then clicks another topic's Manage loses them. That is why
save moved behind a `Confirm`, which charges a second click on the irreversible
action only.

Escape and focus return both changed meaning and both were re-derived rather
than assumed: Escape is a `document` listener that acts only when the target is
inside the region (not `window` — that is the defect `GraphDetail` shipped
once), and focus return is now **conditional on focus still being inside**,
because a reader can tab out and carry on, and yanking them back to a row they
left is worse than doing nothing.

Task B also recorded two React findings that cost real time: a `focus()` made
during the mutation phase does not survive the commit (React restores the
pre-mutation focus afterwards), and its first version of the focus test **passed
with the assertion removed**, because `user.click` carries a focus change of its
own. Both are in its report.

## Verification

All four gates, on a machine under load average 21 (another worktree running a
job at 68% CPU), which is why this section is longer than it should be.

| Gate | Result |
| --- | --- |
| `uv run ruff check .` | passed |
| `uv run ruff format --check .` | 230 files already formatted |
| `uv run pytest` | 2370 passed, 9 deselected |
| `cd frontend && npm run verify` | 1030 passed (103 files); build, size, deleted, check:tailwind all pass |
| `npm run test:browser` | **57 passed (19 files), twice consecutively** |

**The jsdom suite failed twice before it passed, and neither failure was real.**
Run 1: 10 failures in 9 files. Run 2: 11 failures in 7 files — **a different
set**. Run 3: 1030/1030. Every named failure passed in isolation, and the three
files checked individually ran 26 tests in 3.66s against a 5s timeout. Different
set each time, all green alone, timeouts rather than assertions: that is the
load signature `CLAUDE.md` describes, and it is recorded here rather than
quietly re-run until green.

**One consequence worth stating**: `verify` chains, so aborting at
`test:coverage` meant `build`, `size`, `deleted` and `check:tailwind` never ran
on the first two attempts. They were run explicitly. `deleted` reports *"35
deletion rules hold, and 21 stylesheets stay frozen"* — 34 rules before, 21
stylesheets not 22, which is the deletion landing in the only place that can
prove it.

The browser suite was **52 passing with 5 failing when this slice started** and
is 57 passing now. Those 5 were the ring regression.

### The bundle

Gzipped (`-9`), each changed asset against `HEAD`:

| Asset | HEAD | Now | Δ |
| --- | --- | --- | --- |
| `app.js` | 59,363 | 60,596 | **+1,233** |
| `index.css` | 14,036 | 13,448 | **−588** |
| `GraphCanvas.js` | 1,386 | 1,411 | +25 |
| **net** | | | **+670 B (+0.65 kB)** |

Deleting 734 lines of CSS buys back roughly half of what the utility strings
cost, which is the same shape 3a measured and the same conclusion: a rewrite of
this kind is roughly size-neutral by construction. The `app` bucket is 72.7 kB
of its 80 kB budget — **7.3 kB of headroom, and this slice spent 1.2 of it.**
That is the number the next slice should read before it starts.

## What is still not measured

- **The three region widths, for the fourth slice running.** `PROJECT_TRACKS`'s
  numbers are still chosen rather than measured. Slice 2 deferred it to slice 3
  because the measurement wants a page with the graph on it; this is that page,
  and it was still not done. **It should stop being a deferral and become a
  backlog entry**, because four slices of "the next one will do it" is a
  prediction the record no longer supports.
- **Anything below `--bp-wide`.** Nothing here was rendered at any narrow
  layout, for the fourth slice running.
- **Anything by eye, in Storybook or otherwise.** Task A's one deliberate visual
  change — a 0-to-8px gap where `topic-filters` was dissolving into its parent —
  is reasoned from the stylesheet and asserted by no test.
- **`.extraction-merge-list`**, the second unpadded-scroller exposure §5.2
  names. It is QUEUE's markup but the extraction pane's, untouched here.
- **`TruncatedText`'s inert ring utilities** — filed as `BACKLOG.md` B56 rather
  than fixed, because the offset it asks for is positive, nothing is clipped,
  and "fixing" it is a blind 1px→2px visual change in a shared primitive.

## What is left of Increment C

**Slice 4 — the picker gets thinner.** Pure subtraction, and the only slice that
can be dropped without leaving anything half-built.

`course.css` survives, and will until QUEUE's rail, roster, extraction pane and
autonomy panel are rewritten. No slice in §2 does that, so **`course.css`'s death
is not currently anybody's job** — worth saying out loud, since three slices have
now predicted a stylesheet's death from a plan that did not allocate one.
