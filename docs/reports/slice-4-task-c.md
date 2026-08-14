# Increment C, slice 4 — task C report

Markdown only. `git diff --stat` at the end shows `BACKLOG.md` as this task's
only change; the two `frontend/src/presentation/tree/` files in the same diff
belong to task A, working in the same worktree.

## 1. The §4.1 correction was already made, and the brief's location is wrong

**Nothing was edited for item 1, because there is nothing left to correct.**

Two things about the brief's premise:

- **There is no §4.1 in `docs/increment-c-plan.md`.** That document's §4 is
  "§6.3's one backend change". The `L-F17`/`L-F18` rows live in
  `docs/unified-ui-proposal.md` §4.1 ("Landing page (L-F1 – L-F48)"), which the
  plan refers to throughout as *"Proposal §4.1"* — `increment-c-plan.md:624`
  uses exactly that phrasing.
- **The proposal already carries the correction, in the house convention, in
  four places**, and `increment-c-plan.md` carries its own `[audit 5]` note:

| Where | What it now says |
|---|---|
| `unified-ui-proposal.md:19-20` | in the front-matter list of "the four corrections that change what gets built next": "**§4.1's `DROPPED` verdict on L-F17/L-F18 is withdrawn** — acting on it would re-open a regression #176/#177 closed" |
| `unified-ui-proposal.md:389-401` | §3.5's original sentence ("It loses the two destination buttons (L-F17, L-F18), because there is one destination") is **left standing**, with a `**[corrected]**` paragraph under it giving the re-pointing, both line references, the `App.tsx:138` intercept, and "the overflow slot is the only non-typed-URL door to the ask page" |
| `unified-ui-proposal.md:447-448` | the two §4.1 table rows now read **PICKER, re-pointed**, each note opening "was `DROPPED — one destination`" |
| `unified-ui-proposal.md:689-692` | the §8 wrap-up records "Also no longer dropped: **L-F17 and L-F18 were re-pointed rather than deleted**", above the preserved "As originally written: … Explicitly dropped … L-F17, L-F18" |
| `increment-c-plan.md:617-634` | §2.4's own `**[audit 5]**` note, quoting what the section used to read and stating that "correcting it is the first thing a slice-4 implementer should do" |

That is the convention the brief asked for — original text kept, marked note
saying what it used to claim and why it was wrong — applied already. Rewriting
it would have been churn, and re-marking an already-marked correction would have
made the record read as if it had been wrong twice.

`grep -rn "one destination" docs/` finds no surviving assertion that the buttons
are dropped: the only other hits are `increment-c-plan.md:205,858,860`, which
are about `Breadcrumbs.tsx` offering two names for one destination — unrelated.

## 2. Line references verified against the current tree

All checked at `dbb0b65` + the working tree, by reading the files:

| Reference as written | Verdict |
|---|---|
| `ProjectList.tsx:371-379` (Project → `projectHref(id)`) | **correct** — `Tooltip` opens at `:371`, `key="project"` at `:373`, the `Button` at `:376-378`, closing `</Tooltip>,` at `:379` |
| `ProjectList.tsx:387-398` (Ask → `#/p/<id>/ask`) | **correct** — `Tooltip` at `:387`, `key="ask"` at `:389`, `navigate(projectHref(project.id, { facet: 'ask', id: null }))` at `:394`, closing at `:398` |
| `App.tsx:138` intercepts `ask` | **correct line, incomplete path.** The file is `frontend/src/app/App.tsx`, not `frontend/src/App.tsx`; `:138` is `if (selection?.facet === 'ask') return <AskView key={id} projectId={id} />`. The docs cite it bare as `App.tsx`, which is the repository's habit and matches how the plan cites every other file |
| `workers.py:296-303` (`detail="autonomous run"`, `started_at=None`) | **correct** — `research_team/application/workers.py`, `Worker(` at `:296`, `kind="run"` at `:297`, `detail="autonomous run"` at `:299`, `started_at=None` at `:302`, closing at `:303` |

One cosmetic drift, not corrected because it is in a code comment and this task
touches no code: `ProjectList.tsx:383` says `App.tsx` "renders `AskPage`". It
renders `AskView`. Both components exist in `presentation/ask/`; `AskView` is
the one the router reaches, so the comment is one hop short rather than wrong.

## 3. The backlog entry: **B58**

`BACKLOG.md`, added at the end of the UI cluster that runs B54–B55, immediately
above `## The ask page`. Next free id: the file's highest is B57, and ids are
not otherwise dense (B54, B48 and B36 each appear twice already, so B58 is the
first genuinely unused number).

> ### B58. The roster's run worker carries no rounds and no start time, so the picker chip says less than it used to

It records all four things the brief required — that this is a **backend**
change, that §4 of the increment is titled "the one backend change" so taking it
spends that title, that slice 4's §2 answered (a) deliberately before any code
was written rather than discovering the degradation mid-slice, and what a reader
loses meanwhile (the round count, one click away on the project page; plus an
elapsed time the chip never promised elsewhere).

## 4. What I found that the brief did not say

**"Widen `Worker` so a `run` kind carries `rounds`" is the wrong shape, and the
entry says so.** `Worker.detail`'s docstring (`workers.py:95-98`) states that
the string is *already composed* server-side "so two front ends [do not]
disagree about how to say the same thing". A `rounds` integer sitting beside a
composed `detail` hands the front end a second way to say the same thing, which
is the arrangement that docstring exists to prevent. The honest shape is to
compose `round N` into `detail` where the roster is folded, and to pass the
run's real start time through as `started_at`. B58 records the field addition as
the plan phrased it *and* this objection, so whoever picks it up does not have
to rediscover the docstring.

**Task A has already landed the change B58 is the counterpart to.**
`ProjectActivity.tsx:45-70` in the working tree is the single-roster version,
with the run-outranks-everything ordering decision written into a comment. B58's
"the chip is degraded in the meantime" is therefore describing shipped code, not
a prediction — which is the stronger version of the entry.
