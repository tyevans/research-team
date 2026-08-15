# Task C — items 1 and 2

Branch `narrow-band`. Items 1 and 2 done; item 3 (closing B57/B60) waits on
tasks A and B and is untouched.

## Item 1 — two stale comments, both genuinely stale

Neither had been corrected already. Both verified before editing.

### (a) `frontend/src/styles/components.css:582`

**Verified stale.** `grep -n course frontend/src/styles/responsive.css` returns
exactly one hit, line 13, and it is prose in a comment — no course selector at
any breakpoint. `course.css:4-9` confirms `CourseView` and every rule about its
markup were deleted in one commit, including four counterparts in
`responsive.css`. So the claim "it is now one rule in `responsive.css`, at
`--bp-narrow`" names a rule that does not exist, and the cost it recorded ("two
columns between 821px and 900px") is a cost nobody pays.

**Changed.** Marked the correction in place per the house convention, kept the
half that is still true — `theme.test.ts` refuses a media query whose boundary
is not a `BREAKPOINTS` value, which is why the 900 could not simply move — and
kept the note in this file because this file is where the 900 lived.

### (b) `frontend/src/styles/layout.css:109`

**Verified stale, and worse than the brief said.** The comment explains a
`1180`/`1181` off-by-one and introduces `@media not all and (min-width: 821px)`.
`grep -rn '1180\|1181' frontend/src` shows no 1180 anywhere in `layout.css` at
all — the pair lives in `tokens.css:135-154` and `responsive.css:26,99`, the
wide band. And at 821 there is no off-by-one to explain: `layout-tokens.ts:31`
declares `narrow: 821` and the negated spelling uses that same literal, which is
the whole point of writing it that way.

**Changed.** Rewrote to describe the 821 rule it is actually attached to, marked
that it used to cite 1180/1181 and where that pair really lives. The idea — one
boundary, one literal, shared with `matchMedia` — survives unchanged.

Nothing else in either file was touched. No rule was changed in `layout.css` or
`responsive.css`.

## Item 2 — `BACKLOG.md` B62, filed as a question

`BACKLOG.md` B62, placed after B61 and before "The ask page". Next free number
(B61 was the highest).

Filed as a question with both outcomes, as instructed — no defect claimed. One
thing I did verify, and it corrects the brief's premise:

**Source order is not what decides this.** `frontend/src/styles/theme.css:85`
imports Tailwind's utilities as `layer(utilities)`, and `responsive.css`
contains no `@layer` (grepped: zero hits). So the contest is unlayered against
layered, not order against order, and an unlayered normal declaration beats a
layered one regardless of specificity — the rule `CLAUDE.md` records under the
inward focus ring and `theme.css:78-79` states in the same words. On that
reading the stylesheet wins and the drawer is full width below 820.

`Drawer.tsx:155-163` already carries a comment asserting exactly that outcome,
by exactly that reasoning. So the entry is not "which wins" so much as "this has
been reasoned twice and measured zero times", which is why it is still filed.
B62 records that jsdom cannot settle it (`getComputedStyle` there returns only
inline styles, so a passing assertion proves nothing) and names the measurement:
a drawer at 800×900 in `npm run test:browser`, reading
`getBoundingClientRect().width`.

---

# Item 3 — the record closed and extended

Written after reading `docs/reports/stacked-task-a.md` and
`stacked-task-b.md` in full. Every number below is quoted from one of them.

## B57 — closed

Rewritten as a closure. The three bands and the defect found in each:

- **≥1181** — fr shares 337/506/337, MATERIAL's 351px tab strip painting the
  Graph tab past the pane edge. Floors now 344/342/352.
- **821–1180** — no layout at all; three regions in one grid column, MATERIAL at
  **148px** with no scroller.
- **below 821** — `scrollHeight == clientHeight == 856` at every width from 820
  down to 375, MATERIAL at **112px**. Fixed by `flex: 0 0 auto` on `.lay-split`;
  after, **1128 / 856** and panes 578/401/148.

The closure also records the **refuted** candidate defect, so nobody re-derives
it: the unqualified 60vh cap does not clip a `regions` body, because each region
is `flex: 1 1 0%; min-height: 0` with its own scroller — HOLDER's body 362.9
under a 540 cap, both regions scrolling 88px, composer on screen. Adding the
`:not()` would have been justified by nothing.

**What I was careful not to let it read as.** The lead asked that this not sound
more complete than it is, and two things needed saying explicitly, both now in
the entry: the **350px** and **343px** clip points are *recorded, not fixed*
(with the reason — phone widths, and `.tabs` is shared by `Choices` and `TabList`
so a `flex-wrap` changes every tab row console-wide), and **the session view was
never swept below 700** — 821, 1000 and 700 are the only widths rendered there.

I did **not** simply delete B57's two undischarged items. The 46vh cap and the
weights were still open and are now **B65**, re-filed rather than buried inside a
closed entry. That is a departure from the brief's "close B57", and the reason is
that both would otherwise have been lost: they are exactly the kind of item
nobody would think to re-file, which is the argument B57's own previous close
made for keeping itself open.

B57 is kept as a stub rather than deleted, against this file's "closed entries are
deleted" convention, because `increment-c-plan.md` §8 and four reports cite the
number. Same reasoning B56 already uses two entries below.

## B60 — closed

Closed with the rule as ported and the red proof quoted whole:

```
× rails both session flanks when both are folded
  → AssertionError: expected 966 to be close to 34, received difference is 932,
    but expected 0.5
```

Recorded that the 966 was **measured in the session view**, not carried over —
the project view's identical 966 is the same 1000 − 34 arithmetic rather than a
coincidence — and that the claim asserts the two rectangles rather than the
template string, re-reading the first pane after the second fold. Also that B60's
closing paragraph (whoever merges the blocks "owes the session view this rule")
is now false and the project block's comment has been rewritten: the two blocks
differ only in their floors, 344/320 against 280/300.

## `increment-c-plan.md` §8 residue list — updated

B56, B57 and B60 each now say **"No longer residue"** in as many words, with B57
and B60 gaining a one-line statement of what was actually found. Added a bullet
for what *is* residue now — B61, B62, B63, B64, B65 — and, separately, a bullet
naming the 350px and 343px clips and the unswept session view below 700 as
**recorded and deliberately not fixed**, so a later reader does not re-file them
as new findings.

## Two new entries

**B63 — the research view below 821 is unmeasured.** Written as unmeasured, not
measured-and-fine, in those words. The entry contrasts it with the two views that
*were* measured (project, where the defect was found; session, red-proved by
removing A's declaration — `expected 856 to be greater than 856`) and notes that
a green suite establishes only that nothing asserted broke. It carries the two
fixture lessons forward, because they are what made the defect visible at all: a
real `Shell` rather than the older files' bare 900px flex column (which
reproduces the pinned height *by accident* and leaves no `.lay-surface` to ask),
and `height: 100vh` rather than a fixed pixel height (which detaches the shell
from the viewport `60vh` measures against).

**B64 — three files, three resize helpers, three versions of one bug.** Filed as
the repetition rather than as any instance. All three are stated: `widen()`'s
`gridTemplateColumns === ''` poll, already true at 1000px; task B's
`data-collapse-to === 'rail'` poll, already true at 1440, which read the 1440
layout — a `280px 320px 280px` template and an **880px conversation inside an
821px viewport**; and task A's third helper, written to avoid both.

The point the entry makes is the one the lead named: the plan spent two
paragraphs warning about the first, and the second reinvented the bug a task
later. **A warning in a plan does not survive into the next file; a shared helper
would.** It states what a shared version needs (poll a React-written attribute
*and* the resolved geometry — either alone is insufficient), says plainly it is
cheap to state and not cheap to do, and names the two things that make it more
than a lift: the three files' fixtures disagree, and `check-deleted.mjs` forbids
the identifier `gridTemplateColumns` under the session view, so the poll has to
be spelled `getPropertyValue('grid-template-columns')`.

## One thing I did not do

**`.view-head`.** Task B's §7 flags the plan's item 4 as dropped between the
lead's four items and the plan's four — `responsive.css:208-211` still styles a
class no element carries, and `tree.css:39,47,53` still define the family. The
progress ledger shows it re-dispatched to B as item 5. It is not in my scope
(`BACKLOG.md` and `docs/`) and I have not filed it, since it is being done rather
than deferred. **Resolved:** the dispatch landed — task B's item 5 deleted the
family from both files. Nothing owed here. (This paragraph said B66 was free for
it; B66 went to `.node-actions` instead, below.)

## Not run

No gates. This task touched `BACKLOG.md`, `docs/increment-c-plan.md` and two CSS
comments only; prettier does not cover `.md` here and the CSS comment edits were
made in place without reflowing to a different wrap width. Worth a
`npm run verify` on the merged branch regardless, since `components.css` and
`layout.css` are both in it.

---

# Item 4 — `.node-actions`, filed as suspected rather than dead

`BACKLOG.md` **B66**. Written after task B's item 5 section, which is where the
observation comes from.

**Filed as suspected-dead, and the entry is built around why that is not the same
claim as `.view-head`'s.** The two deletions would have rested on different kinds
of evidence, and the entry says so in as many words:

- `.view-head` had a **recorded cause** — `QueueHeader.tsx:84` names the commit
  that removed its last inbound link, and the stylesheet's own comment said it
  dressed the head "shared by the course and research views, which is all that
  still uses it", both of which are gone. The grep confirmed a story the
  repository already told.
- `.node-actions` has **the grep and nothing else**. Nothing records it being
  orphaned, and its comment still describes a live purpose (row buttons that were
  raw inline-block elements with no gap before it).

The sentence the entry turns on: *a deletion justified by "I could not find a
reference" is a weaker claim than one justified by a record of the reference
being removed* — a grep searches the spellings you thought of, a recorded cause
is evidence.

Recorded as instructed: the grep covered every `.tsx`, `.ts`, `.css`, `.mjs`,
`.js`, `.html`, `.json` and `.md` under `frontend/`, dated 2026-08-14; the only
hits are `node-actions-gap` (`ProjectList.tsx:354`, `ProjectCard.stories.tsx:173`),
a distinct single token with its own live rule directly below — not
`.node-actions` with a modifier. The rules are `tree.css:103-112`, five
declarations. What upgrades it: `git log -S 'node-actions'` over the deleted
views, or a reviewer's second look.

**`check-deleted.mjs`'s blind spot is in the same entry** rather than beside it,
because it is the reason `.view-head` lasted: the 35 `RULES` forbid named
patterns from coming back and none names this class, and `STYLESHEETS` freezes
**the set of files, not their contents** — its own docstring says so and names
the hole. So `tree.css` surviving means every rule that dies inside it is
invisible to the check. **Rot inside a living file is a class of decay no gate
here sees.** Written as a description of coverage, explicitly not a request to
change the script, with the reason a rule on a name this generic would be the
wrong fix.
