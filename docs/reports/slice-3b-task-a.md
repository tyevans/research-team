# Slice 3b, task A — the topic-list cluster onto utilities

## The headline

The mechanical rewrite is done and is the least interesting part. **The
finding is that the ring fix slice 3a shipped does not work, and did not work
then either.** A `focus-visible:outline-offset-[-2px]` utility loses to
`tokens.css:339`'s unlayered `:focus-visible`, because an unlayered normal
declaration beats a layered one whatever the specificity — and Tailwind's
utilities are in `@layer utilities`. The class is in the attribute, the rule is
generated, the computed offset is still `+1px`.

The cost is one character (`!`) and the reason it was not caught for a slice is
that slice 3a ran no test locally. `DocumentBrowser.browser.test.tsx` is red on
this branch today: 3 of its 4 tests fail. That is a shipped regression in
someone else's file and is reported rather than fixed — see "what I could not
do".

## What was rewritten

| File | Class names removed | Notes |
| --- | --- | --- |
| `TopicQueue.tsx` | `topic-browser`, `topic-filters`, `topic-search`, `topic-focus`, `topic-focus-tab` (+`.is-on`), `topic-focus-count`, `topic-dispatch-bar`, `topic-list`, `topic-dispatch-button`, `topic-dispatch` (+`-queued`/`-running`/`-failed`/`-done`) | 14 |
| `TopicDocuments.tsx` | `topic-documents`, `topic-document-list`, `topic-document-tab` (+`.is-on`) | 3 |
| `SubQuestions.tsx` | `sub-questions`, `sub-question-list`, `sub-question`, `sub-question-resolved`, `sub-question-text`, `sub-question-answer`, `sub-question-resolve`, `sub-question-add` | 8 |
| `TopicList.tsx` | none | It writes no class at all; it is a container. The brief lists it and there was nothing in it to do. |

`research.css` is untouched, as instructed. Twenty-five names are now dead
rules waiting for task E.

Three shared constants carry what a grouped or repeated rule carried:
`FOCUS_TAB` and `CHIP` in `TopicQueue.tsx`, `DOCUMENT_TAB` in
`TopicDocuments.tsx`, `FIELD_ROW` in `SubQuestions.tsx`.

**One convention applied throughout and worth stating**: where a rule set a
base colour and a modifier overrode it, the utility version sets the colour
*per branch* rather than base-plus-override. Two `text-*` (or two `border-*`)
utilities on one element resolve in Tailwind's emission order, not the
attribute's, so "dim unless chosen" written that way is a coin toss. This is
the same class of hazard as slice 3a's per-edge border colours.

## The four undressed class names, decided

The plan named four. **Three of the four are as described, one is wrong, and
there is a fifth the plan missed.**

1. **`topic-filters` (`TopicQueue.tsx:152`) — dissolved, not dressed.** It was a
   grouping wrapper with no rule, so it laid out as a plain block: the search
   box and the focus tabs sat flush against each other while every other pair in
   `.topic-browser`'s column had 8px between them. Making its two children
   direct items of the column gives them that 8px. **This is a deliberate visual
   change and the only one in this task** — it is the gap the wrapper was
   hiding. Dressing it instead would have meant inventing a second, smaller gap
   for no reason a reader could see.

2. **`topic-dispatch-button` (`:254`) — dropped, no replacement, always meant
   bare.** `Button` already dresses it, and `shell.css:202`'s
   `.btn[aria-disabled='true']` already draws the off state this button spends
   most of its life in (it is `aria-disabled` rather than `disabled` so the
   tooltip explaining *why* can open). There was nothing left for the name to
   declare. Same argument slice 3a made for `.artifact-missing`: a class with no
   rule cannot be told from one whose rule was lost.

3. **`topic-dispatch-queued` (in `DispatchChip`) — dropped, deliberately
   bare.** Queued and cancelled are the two states that are not happening, and
   they share the base `--fg-dim`; the three that are toned (running, failed,
   done) are the three a reader has to act on. Keeping a modifier name for
   "looks like the default" told a reader of the markup that a queued chip had a
   look of its own, and it did not.

4. **`sub-question-resolve` (`SubQuestions.tsx:141`) — the plan is wrong about
   this one. It has a rule and always did.** It is the *first* selector of the
   grouped rule at `research.css:306`:

   ```css
   .sub-question-resolve,
   .sub-question-add { display: flex; flex-wrap: wrap; align-items: center;
                       gap: 6px; margin-top: 4px; font-size: var(--t-xs);
                       color: var(--fg-dim); }
   ```

   Translating it as bare would have flattened both the resolve row and the add
   row into unaligned stacks. It is `FIELD_ROW` now, shared by both, which is
   the same saving in the same place. The mechanism of the plan's error is worth
   recording because it will recur: the four-name list matches the shape
   `^\.name {`, and **a grouped selector's second-and-later members never match
   that shape** — so this grep finds dressed-looking names that are bare and
   also calls dressed names bare, in both directions.

5. **`topic-documents` (`TopicDocuments.tsx:104`) is a fifth undressed name the
   plan did not list.** `research.css` declares `.topic-documents-section` and
   nothing for `.topic-documents`. Dropped rather than dressed: the list below
   it carries its own bottom margin and the pane around it supplies the padding,
   so the wrapper was occupying a name and doing nothing. (The `<div>` stays
   because the list and the selected document need one parent.)

## The focus ring — what was actually measured

`.topic-list` had `padding: 0` and `overflow-y: auto`, so its padding box and
its border box are the same rectangle, and the global ring's three outward
pixels are on the far side of its own clip. Chromium makes a scroll container
focusable with no `tabIndex`, so it is a real tab stop as soon as the queue is
longer than the rail.

Measured in Chromium at the 1440x900 viewport `vite.config.ts` sets (not the
wrapper's width — that trap is in `CLAUDE.md` and it is real), 24 topics in a
340x300 column, list 340 wide, clip (padding box) `0..340 x 75.5..300.5`:

| `RING_INWARD` | Ring reaches | Verdict |
| --- | --- | --- |
| absent — what shipped | `-3..343 x 72.5..303` | outside the clip on all four sides; nothing visible |
| present, no `!` | **`-3..343 x 72.5..303`** | identical. The utility lost. |
| present, with `!` | `0..340 x 75.5..300` | flush with the border box, inside the clip on every side |

The middle row is the finding. `outline-offset: -2px` with `outline-width: 2px`
gives an outward reach of exactly 0, which is why the fixed ring sits flush with
the border box rather than strictly inside it — worth knowing before someone
reads `>=` in the assertions as slack.

The ring is *drawn* in all three rows (`outline-style: solid` throughout), so
the defect is purely positional. Every assertion in the new file is geometry and
none is presence alone.

`src/presentation/research/topic-list-ring.browser.test.tsx` is new, three
tests, modelled on `FileList.browser.test.tsx`, and **proved red twice** — once
with the constant absent and once with it present but unimportant, which is the
pair that makes the finding legible. It asserts its own precondition
(`scrollHeight > clientHeight`) and that `:focus-visible` actually matched after
the programmatic `focus()`, both for the reason `FileList` gives: without them
every assertion passes against the defect.

## Borders

Two places, both `border-0` plus a directional width-and-style, both halves:

- `SubQuestions.tsx`'s section top edge: `border-0 border-t border-solid border-line`
- `SubQuestionRow`'s urgency left edge: `border-0 border-l-2 border-solid border-l-line`

The three all-four-sides cases (`FOCUS_TAB`, `DOCUMENT_TAB`, the dispatch bar)
are `border border-solid border-<colour>`, which needs no zero.

## Tests

Green, run under `flock /tmp/rt-vitest.lock` throughout:

- `TopicQueue.test.tsx` 7, `TopicList.test.tsx`, `TopicDocuments.test.tsx`,
  `SubQuestions.test.tsx` — 37 across the four.
- `topic-list-ring.browser.test.tsx` 3, `TopicQueue.browser.test.tsx` 2.
- The whole of `src/presentation/research/` and
  `src/presentation/entity/topic/`: 17 of 19 files pass; the 2 failures are
  `DocumentBrowser.browser.test.tsx` and `graph-dressing.browser.test.tsx`,
  neither mine — see below.
- `tsc --noEmit`, `eslint` and `prettier --check` clean over every file touched.

**No class-name assertion was lost, because there was only one and it is not
mine**: `TopicList.test.tsx:228` asserts `toHaveClass('needs-attention')`, which
`TopicRow` writes and `entity.css` declares. Coverage added rather than removed:
one jsdom test guarding `data-topic-scroll`, which is what the browser test
finds the scroller by — a rename would otherwise make that file fail as a broken
test rather than as a caught defect. Its docstring says it fails with the change
reverted, because the attribute is new.

## What I could not do, and what I touched outside the brief

- **`DocumentBrowser.browser.test.tsx` is red on this branch and I did not fix
  it.** 3 of 4 tests, `expected 35 to be greater than or equal to 38`. Cause is
  the `!` above; `DocumentBrowser.tsx` is slice 3a's file. Reproduced on repeat
  runs, not load-related. Someone has to own it before task F, and the fix is
  one character.
- **`graph-dressing.browser.test.tsx` (task C, being written concurrently) fails
  with `expected 1 to be -2` on `ring.offset`** — same cause. Messaged the lead
  to relay.
- **`topic-documents-section` and `topic-section-heading` are still written**,
  by `TopicStatusDialog.tsx:145-146`, which the brief puts out of scope. The
  brief lists both among the names to remove; their only writer belongs to task
  B. Task E cannot delete `research.css` until task B translates them.
- **I edited one file outside the four**: `entity/topic/Topic.stories.tsx:97`
  wrote `topic-dispatch topic-dispatch-running` into a `TopicRow` slot. Left
  alone it becomes an undressed chip in the workbench the moment task E deletes
  the stylesheet, with nothing failing — exactly the `Tooltip.stories.tsx` case
  slice 3a fixed. The utility strings are copied rather than imported, for the
  reason 3a gives: a story that imported a component's private dressing stops
  being a sample of the markup and becomes a second renderer of it. Flagging it
  because it is not on my list.
- **Nothing was rendered below `--bp-wide`**, and nothing was opened in
  Storybook by eye. The gap-0-to-8px change in item 1 is reasoned from the
  stylesheet and asserted by no test.
- **`npm run verify` was not run**, per the brief.

## What the plan got wrong

1. `sub-question-resolve` is dressed, not bare. §2's task-A paragraph and the
   brief both repeat it. Mechanism above.
2. `topic-documents` is a fifth undressed name and is not in the list of four.
3. §2's task A says the ring fix is "free" at the point of rewrite. It is
   nearly free, but only because this task measured it — the obvious spelling
   of the fix is inert, and the plan's framing (three previous fixes have paid
   for it, apply the same one) is what would have produced the inert spelling.
   The three precedents it cites (`workspace.css`, `research.css`,
   `agents.css`) are all *stylesheet* rules, which is why they worked; this is
   the first time the fix has been attempted as a utility.
