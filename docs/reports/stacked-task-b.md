# Task B — B60, the session's bottom edge, and the session below 821

2026-08-14, branch `narrow-band`. Scope: §3 task B of
`docs/superpowers/plans/2026-08-14-below-the-narrow-breakpoint.md`, plus the
fourth item the team lead added after task A reported.

Files touched: `frontend/src/styles/responsive.css` (one new rule, two comments)
and the new `frontend/src/presentation/session/session-responsive.browser.test.tsx`
(3 claims). Nothing else. `layout.css` was mutated twice for red proofs and
restored byte-identically, verified by md5 both times.

---

## 1. B60 — the both-flanks rule, ported

Added after the two single-collapse rules so it wins on source order, exactly as
the project block does:

```css
.lay-split[data-split='session']:has([data-pane='timeline'].is-collapsed):has(
    [data-pane='workspace'].is-collapsed
  ) {
  grid-template-columns: var(--rail-w) var(--rail-w);
}
```

**Proved red first**, against the block as it shipped, at 1000x900 — claim 1 of
the new file, written and run before the CSS was touched:

```
× rails both session flanks when both are folded
  → AssertionError: expected 966 to be close to 34, received difference is 932,
    but expected 0.5
```

966px where a rail is 34, under a rotated title. That is B60's predicted number
in the session view, measured rather than carried over: the project view's
equivalent was 966 too, which is the same arithmetic (1000 − 34) rather than a
coincidence.

The claim asserts the two rectangles rather than the template string, for the
reason the project view's claim gives — reading the template back would agree
with whichever rule won — and re-reads the first pane's width *after* the second
fold, since the defect is the second collapse undoing the first pane's track.

## 2. The project block's comment

Its last paragraph claimed the session block "has this bug … and is deliberately
left with it", and that whoever merges the two blocks "owes the session view
this rule". Both false as of item 1. Rewritten to say what is now true: the
session block has the rule, and the two blocks differ only in their floors —
344/320 in the project block against 280/300 in the session one.

## 3. The session's bottom edge — measured, and the 300 stays 300

**The finding is a negative result, and it took a measurement to get there.**
`responsive.css` writes `minmax(300px, …)` for `workspace` while
`SESSION_TRACKS` declares that pane's floor as 320 — a CSS floor below the
declared one, which is the shape of a real defect.

Measured in Chromium at 821x900, the band's own bottom edge and the only width
at which a floor there can bind:

```
grid-template-columns  342.078px 478.906px
timeline 342.078  workspace 478.906  conversation 820.984
```

`workspace` carries the 1.4 weight, so its narrowest share in the entire band is
821 × (1.4 / 2.4) = **478.9**, and the band only widens from there. **The 300
cannot bind at any width**, so raising it to 320 would change no pixel anywhere.
`timeline`'s 280 matches its declared floor and is equally unreachable at
342.078. Kept, and written down — the same resolution, and deliberately the same
argument, the project block already makes for HOLDER's unreachable 320.

**What the arithmetic does not establish is that 342 is wide enough**, and this
is where the session view differs from the project one: the project's 344 was
*measured* (QUEUE's 317px non-wrapping seeding form), whereas neither session
floor was ever derived from anything — `use-session-panes.ts` records that
`panes.css`'s numbers never took effect at all. So that half is measured
instead, with the previous slice's definition (`scrollWidth > clientWidth`, no
scroller, no ellipsis): **nothing clips at 821, in all three collapse states the
band can reach** — both flanks open, `timeline` railed, `workspace` railed.

Claim 2 asserts both floors against the numbers `SESSION_TRACKS` declares, so a
reweighting that made either reachable fails there rather than silently
clipping. It **passes against unfixed code** — it is the bottom edge's first
record, not a guard on anything in this slice — and its docstring says so.

**Its red proof is worth reading, because my first guess was wrong.** I
predicted `minmax(400px, 1fr)` would break it; it does not — 400 + 421 still
sums to 821 and both floors still clear. What breaks it is a floor large enough
to squeeze the *other* column onto its own, `minmax(600px, 1fr)`:

```
× clears both declared floors at the bottom of the band, and clips nothing
  → AssertionError: expected 300 to be greater than or equal to 320
```

That is precisely what the 300/320 mismatch becomes if the arrangement ever
changes: the CSS hands out 300 where the view declares 320. Unreachable today,
and now pinned.

## 4. Task A's `.lay-split` fix, checked on the session view

A's `flex: 0 0 auto` is on the shared primitive and reaches this view; A flagged
it as unmeasured here. **It is measured now, and the answer is that the fix was
needed here too and did not break anything.**

Claim 3 renders the session view at 700x900 inside a real `Shell`. After A's
change: surface **1063 / 856** — it scrolls — panes at 126.3 / 215.1 / 683.3,
each at its content's height under the 60vh cap, stacked full-width in order,
both `regions` bodies (`workspace`, `conversation`) showing all of themselves
rather than clipping, and nothing clipping horizontally.

**Proved red by removing A's declaration** (`flex: 0 0 auto` → `flex: 1 1 auto`
on `.lay-split` in `layout.css`'s below-821 block), at 700x900:

```
× stacks into a scrolling page below 821
  → AssertionError: expected 856 to be greater than 856
```

So the session view had the same defect A found in the project view, and A's fix
cures it here as well. `layout.css` was restored immediately and its md5 checked
against the pre-mutation copy (`63cdbe30…`, identical).

**No finding for the team lead.** Nothing about A's change is wrong on this view.

**The fixture change that made this measurable is worth recording**, because the
empty session hides the whole question: with no messages the session view is
shorter than the screen at every width, so the surface measured **856 / 856 —
flat, for the boring reason** — both before and after A's fix. The claim only
means something with 40 messages in the transcript.

## 5. Two traps, and one that was not in the brief

Both documented traps were avoided as briefed: `widen()` was not reused, and
`columns()` is not used below 821.

**A third cost me the first probe run, and it is the same trap from the other
side.** My first resize helper polled only `data-collapse-to === 'rail'` — which
is already true at 1440, the viewport every test starts from. A 1440 → 821
resize satisfied it on the first tick and the probe read the *1440* layout: a
template of `280px 320px 280px`, `Split`'s inline three-track style still on the
element, and a conversation 880px wide inside an 821px viewport. The plan warns
about this for `widen()` crossing downward; the attribute has the identical
defect crossing from above, because `'rail'` is what it says on both sides of
1181. The helper now polls the attribute **and** the resolved geometry, and its
docstring carries the failed reading.

**One thing the brief did not predict:** `check-deleted.mjs` forbids the
identifier `gridTemplateColumns` anywhere under the session view (phase A
deleted a hand-built session grid). My poll read it, and the check failed. Not
resolved by editing the rule — reading the browser's own answer is not what the
rule is about, but the rule cannot tell, and a rule loosened for a test is worth
less than one spelling. The helper uses
`getComputedStyle(...).getPropertyValue('grid-template-columns')`, and the
docstring says why. `check-deleted.mjs` is unmodified and passes: *"Nothing has
come back — 35 deletion rules hold, and 21 stylesheets stay frozen."*

## 6. Verification run

- `session-responsive.browser.test.tsx` alone — 3 passed.
- `npm run test:browser` — **24 files / 80 tests passed**, against the 23/77
  baseline task A left. No regression; the 3 are mine.
- `npx vitest run --project app src/presentation/session src/presentation/layout`
  — 15 files / 118 tests passed (the jsdom siblings nearest my change,
  `SessionView.test.tsx` and `breakpoints.test.tsx` among them).
- `node scripts/check-deleted.mjs` — clean.
- `npx tsc --noEmit` — clean.
- `npx eslint` on the new test file — clean.
- `npx prettier --check` on the test file and `responsive.css` — clean.

Never two vitest processes at once. Not run, per the brief: `npm run verify` and
the Python gates.

## 7. Left undone

- **Item 4 of the plan (the dead `.view-head` family) was not in my brief** and
  is not done. The team lead's four items replaced the plan's four, and this one
  was dropped between them: `responsive.css:208-211` still styles `.view-head`,
  which no element carries, and `tree.css:39,47,53` still define the family.
  Flagging it rather than doing it, since it is a deletion across a file I do not
  own.
- **`workspace`'s 300 was kept rather than raised.** Justified above and in the
  stylesheet, and the argument is "changes no pixel", not "is the better
  number". Anyone merging the two blocks into one primitive should raise it then,
  when the floors have to be reconciled anyway.
- **Only 821, 1000 and 700 were rendered.** No sweep below 700 for the session
  view — task A's sweep found the project view's first clip at 350, well under
  the ~561 the slice treats as worth effort, and the session view's narrow band
  has no equivalent of QUEUE's seeding form. Unmeasured rather than measured and
  fine.
- **The research view below 821 is still unmeasured**, and A's `.lay-split`
  change reaches it too. My brief covered the session view only.

---

# Item 5 — the dead `.view-head` family, deleted

Added after the fact: the team lead's four items had replaced the plan's four
and this one fell between them.

## What was confirmed dead, and how

Grepped for `view-head` across every `.tsx`, `.ts`, `.css`, `.mjs`, `.js`,
`.html`, `.json` and `.md` under `frontend/`, not just for the class name in
`className` position. **No element carries `.view-head` or
`.view-head-actions`.** Every hit is one of three things:

- `file-view-head` (`FileView.tsx:75`, `workspace.css:109`, `tokens.css`, two
  test/story files) — a distinct single token that `.view-head` does not match,
  and alive.
- prose about the class in `AskHead.tsx:18`, `AutonomyAllowAll.tsx:51`,
  `AskView.browser.test.tsx:124`, `QueueHeader.tsx:84`.
- the definitions themselves.

Nothing constructs the name dynamically, uses it in a `:has()` or an attribute
selector, or names it in a test.

The stylesheet's own comment was the confirmation: it said the rule was "the
head shared by the course and research views, **which is all that still uses
it**". Both views are deleted.

## What was deleted

- `responsive.css` — the `.view-head` rule in the below-820 block (4 lines).
- `tree.css` — `.view-head`, `.view-head h1`, `.view-head .sub` (19 lines), and
  `.view-head-actions` from the selector list it shared with `.node-actions`.

Removing that selector left two adjacent `.node-actions` blocks — the second
existed only because the four shared declarations were shared and the
`margin-top` was not. Merged, with a comment saying why there were two.

A comment stands where the family did, because a deletion with no trace is how
the next person re-adds it. It records what the rules were, that the two files
which deliberately *avoid* this class now describe a rule that is gone, and why
no `check-deleted.mjs` rule was added.

## `check-deleted.mjs`: checked, unmodified, passing

Read before touching anything. Two things it does, and neither obstructs this:

- The 35 `RULES` forbid patterns from *coming back*. None of them names
  `.view-head`.
- `STYLESHEETS` freezes the **set of files**, not their contents — its own
  docstring says so, and calls the resulting hole ("200 lines appended to an
  existing filename") out explicitly. `tree.css` and `responsive.css` both stay,
  so removing rules from them is invisible to it, correctly.

`node scripts/check-deleted.mjs` → *"Nothing has come back — 35 deletion rules
hold, and 21 stylesheets stay frozen."*

**No new rule was added, and that is a judgement rather than an oversight.** The
existing rules forbid names a reviewer might re-add to fix a surface that looks
undressed — `.chip-present`, `.topic-list`, `.autonomy-panel`, all specific
enough that a re-add is always the mistake. `.view-head` is a generic name a
future view head could legitimately want, and an anchored `^\.view-head\b` would
also catch nothing else while making that legitimate use a build failure. Say if
you want it and it is two lines.

## Two things I did not do

**1. `.node-actions` is dead too, and I left it.** The same grep: the only hits
under `src/` are `node-actions-gap` (`ProjectList.tsx:354`,
`ProjectCard.stories.tsx:173`), which is a distinct token with its own live rule
at `tree.css:110`. Nothing carries `node-actions`. That is `tree.css:103-112`,
five declarations. **Not deleted**, because it is not part of the `.view-head`
family, it was not in the brief, and its deadness is my grep rather than a
recorded cause the way `QueueHeader.tsx:84` is for `.view-head-actions`. Worth a
second pair of eyes and then one more deletion.

**2. Two comments in files I do not own are now stale**, both flagged by the
brief as worth reading — and neither *relies* on the rule's absence, so the
deletion disturbs nothing. Both merely describe it as existing:

- `AskHead.tsx:18` — "Not `.view-head`: that rule lives unlayered in `tree.css`
  and caps itself at 1100px". True until this commit. The reason the component
  owns its head outright is unchanged.
- `AutonomyAllowAll.tsx:51` — "Its only definition anywhere under `src/styles/`
  is `tree.css`'s `.view-head .sub`". Now false: `.sub` has no definition
  anywhere, which strengthens that comment's argument and contradicts its
  sentence.

`AskView.browser.test.tsx:124` is already past tense ("head **was** capped") and
needs nothing.

## Verification

- `node scripts/check-deleted.mjs` — clean.
- `npm run test:browser` — **24 files / 80 tests passed**, unchanged.
- `npx vitest run --project app` — **95 files / 951 tests passed** (the whole
  jsdom app project, not just the neighbours, since a deleted stylesheet rule
  has no local blast radius).
- `npx tsc --noEmit`, `npx eslint`, `npx prettier --check` on all three touched
  files — clean.

Still not run, per the brief: `npm run verify` and the Python gates.

---

# Item 6 — the two comments item 5 falsified

Comments only; no behaviour, no markup, no stylesheet rules in these two files.

## `AutonomyAllowAll.tsx` — the one that was false

It said `.sub`'s "only definition anywhere under `src/styles/` **is**
`tree.css`'s `.view-head .sub`". After item 5 there is no such definition, and
none anywhere else either.

Rewritten rather than deleted, because the paragraph's argument is the reason
three elements in that file carry `text-fg-dim` instead of `.sub` and it
survives the deletion intact — it is now *more* true. The correction: past tense
for the definition, the deletion named and dated, the conclusion drawn out
(`.sub` now has no definition anywhere at all), and one clause saying the
paragraph was written while the rule still existed and could still have been
mistaken for live. That last part is why the sentence read the way it did, and
without it the correction looks like the original author was careless.

## `AskHead.tsx` — the one that was stale

It said the `.view-head` rule "lives unlayered in `tree.css` and caps itself at
1100px". Tense corrected, and a short paragraph added saying the rule is deleted
as of 2026-08-14 and why the note is kept anyway: it is the recorded reason this
component owns its head outright rather than reaching for a shared one, and the
next person to write a shared head will want the same cap for the same page. A
deleted rule's cost is worth keeping where the decision it drove lives.

## `AskView.browser.test.tsx:124` — read, and correctly left alone

"the head **was** capped at 1100px by `.view-head` and overridden to
`max-w-none!` … **Before it**, these two were equal." Entirely past tense, and
about a state the redesign replaced rather than about a rule that exists. It
needed nothing and got nothing.

## One consequential edit back in `tree.css`

The tombstone comment item 5 left said of these two files: "Both comments now
describe a rule that is gone; they are correct about why their elements do not
use it and stale about it existing." True for about an hour. Corrected to say
both were fixed in the same change, and that the second one's argument gets
stronger — a note about stale comments going stale is the exact failure it was
written to prevent.

## Verification

- `npm run test:browser` — **24 files / 80 tests passed**, unchanged.
- `npx vitest run --project app src/presentation/ask src/presentation/course` —
  12 files / 81 tests passed.
- `node scripts/check-deleted.mjs` — clean.
- `npx tsc --noEmit`, `npx eslint` and `npx prettier --check` on both files (and
  `tree.css` for the third edit) — clean.

`.node-actions` left in place, as instructed. Still not run, per the brief:
`npm run verify` and the Python gates.
