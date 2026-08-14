# Task B — the widths, measured

Branch `increment-d-scoping`, worktree `gate-review-tooltip`, 2026-08-14.
Scope: plan §3 task B of `docs/superpowers/plans/2026-08-14-the-page-nobody-measured.md`,
with the lead's two corrections.

Files changed:

- `frontend/src/presentation/project/use-project-panes.ts` — three floors, and the docstring
- `frontend/src/presentation/project/project-tracks.browser.test.tsx` — new, 4 tests
- `frontend/src/presentation/common/TruncatedText.tsx` — B56: three inert utilities deleted
- `frontend/src/presentation/common/TruncatedText.browser.test.tsx` — one case, holding the B56 measurement

Not touched: `responsive.css`, `project-responsive.browser.test.tsx`,
`ProjectView.browser.test.tsx`, `BACKLOG.md`, anything under `docs/` but this file.

## 1. The headline: the numbers were not merely unmeasured, they shipped a defect

**At 1181px — the narrowest viewport where a `Split` writes a template at all —
MATERIAL got 337px for a tab strip that is 351px wide and does not shrink. The
Graph tab was painted past the pane's right edge: present, and unclickable.**
QUEUE's seeding form went the same way 14px later.

It is the same shape as the topic row's unreachable verbs that
`entity.css:208-222` records, and it survived four slices for the reason B57
guessed: the page had only ever been looked at at 1440, and 1440 was never the
width that was wrong.

So: **changed, not confirmed** — but the change is three `min` values and
nothing else, and the page at 1440 is pixel-identical to before.

## 2. The fixture

The deferral this task was honouring is "the slice that gives each region its
real content", so:

| region | what it holds |
| --- | --- |
| QUEUE | four stages (`StageList`) and four topics with real-length questions, three of them long enough to clip |
| HOLDER | scrub bar, event log, an eight-message transcript, pinned composer |
| MATERIAL | five tabs; six documents with long titles; a twelve-node / eleven-edge graph |

Twelve container ports against `ProjectView.browser.test.tsx`'s nine — `topics`,
`documents` and `graphs` are the three added, and they are exactly the three
that give QUEUE and MATERIAL something to be too narrow for.

**The graph canvas really mounts, and checking that changed the file.** My first
version measured MATERIAL holding the string "loading the graph canvas…" —
`GraphCanvas` is `React.lazy` over `react-force-graph-2d` and had not resolved.
Probing for `canvas` elements returned `canvas=0 graphbrowser=0`. The test now
waits for the canvas before measuring. This is the trap task A hit from the
other side, and I hit it too; it is worth saying that the fixture being "real"
is a thing to assert, not to intend.

## 3. The measurements

A floor is defined mechanically, because "stops being usable" needs an
assertion: **a region is below its floor when something in it has `scrollWidth`
past `clientWidth` with no scroller and no ellipsis to answer for it** — content
painted outside a box that clips it and offers no way to reach it. Three
exclusions, each a decision:

- scroll containers (`overflow-x: auto|scroll`) — they are meant to overflow;
- `text-overflow: ellipsis` — truncation with a `TruncatedText` behind it is a feature;
- `.ent-topic-facts` — `entity.css:208-222` clips it **on purpose**, and that
  rule's comment already measured what it costs. Counting it would have made the
  QUEUE floor a function of how many chips my topic fixture happened to have.

The 1px slack is `TruncatedText`'s, for the same reason: integer `scrollWidth`
rounded from fractional layout.

Swept by driving the split's container width (viewport ≈ container on this page —
`.lay-shell` and `.lay-surface` are both column flex, so nothing takes
horizontal chrome off the split):

| pane width | queue | holder | material |
| --- | --- | --- | --- |
| 320 | — | `.scrub-bar` 341 in 319 | — |
| 337 | seeding form 317 in 310 | clean | `.tabs` 351 in 337 |
| 340 | — | `.scrub-bar` 341 in 339 | — |
| 341 | form 317 in 314 | clean | 351 in 341 |
| 342 | — | **clean** | — |
| 343 | **clean** (by the 1px slack) | clean | 351 in 343 |
| 349 | clean | clean | 351 in 349 |
| 350 | clean | clean | **clean** (by the 1px slack) |
| 352 | clean | clean | **clean** |

**Chosen: `queue 344`, `holder 342`, `material 352`.** Each a pixel or two above
what first measured clean, because 343 of QUEUE and 350 of MATERIAL clear the
check only by spending the slack, and slack is not clearance.

What sets each floor:

- **MATERIAL — 351px of tab strip.** Five labels declared in
  `ProjectView.tsx:119-125`, no wrap, no scroller. The only floor here that no
  data can move; it is a product constant.
- **QUEUE — 317px of seeding form**, plus 27px of the pane's own chrome.
- **HOLDER — 341px of `.scrub-bar`.**

## 4. The decision: floors, not weights — and why that is the whole fix

`minmax(min, 1fr)` takes the floor **only where the fr share falls under it**.
Measured, before and after:

| viewport | queue | holder | material |
| --- | --- | --- | --- |
| 1181, old floors | 337 | 506 | 337 |
| 1181, new floors | 344 | 485 | 352 |
| 1440, old floors | 411 | 617 | 411 |
| 1440, new floors | 411 | 617 | 411 |

So raising three minima by 64, 22 and 72 pixels changes the page at the bottom
of the band and **nowhere else**. Rejected: reweighting. Giving MATERIAL ≥351 at
1181 through its weight needs a share of ~0.30 against today's 0.286, and that
buys the same clearance by reshaping every width above 1181 — a redesign of the
page to fix its narrowest 60px.

**HOLDER's 342 never binds** and is written down anyway: 1.5 of 3.5 at 1181 is
506, and even with both flanks on their floors it gets 485. It is a measurement
that does nothing today and starts mattering the day a fourth region arrives.
The docstring says so rather than implying it is load-bearing.

The weights are **still reasoned rather than observed**, and the docstring now
says which half is which. `1 / 1.5 / 1` is a claim about attention — HOLDER is
what a reader watches, the flanks are interchangeable — and nothing here
measures it. The floors say where a region breaks; they say nothing about where
it is *good*, and no test can tell the difference. That is the honest residue of
this task, and it is smaller than the gap it replaces.

## 5. Red proofs, with output

All against the restored `280/320/280`, same fixture, 1181x900.

Claim 1 — nothing painted outside its region:

```
× paints nothing outside its region at the narrowest wide viewport
AssertionError: expected [ Array(3) ] to deeply equal []
+   "div.lay-pane-body 351 in 337",
+   "div.flex min-h-0 flex-1 flex-col 351 in 337",
+   "div.tabs 351 in 337",
```

and with MATERIAL's assertion moved out of the way, QUEUE fails on the same run
at `+ "form.flex items-center gap-[8px] 317 in 310"`. **HOLDER stays green under
the inversion** — which is the evidence for §4's claim that 342 never binds.

Claim 2 — the floors bind at 1181, 1440 unchanged:

```
× binds the floors at 1181 and leaves 1440 alone
AssertionError: expected 337 to be 344
```

The 1440 half passes under that inversion, deliberately: it is the assertion
that would catch someone "fixing" this with weights.

Claim 3 — MATERIAL fits its tab strip:

```
× keeps MATERIAL wide enough for the tab strip it always has
AssertionError: expected 337.421875 to be greater than or equal to 351
```

Claim 4 — the fixture is loaded, proved red by `documents.list → []`:

```
× measures a page with all three regions loaded
AssertionError: expected '◂Collapse MaterialMaterialArtifactsWo…' to contain
'A very long document title'
Received: "…ArtifactsWorkspaceFindingsDocumentsGraphNo documentsNothing has
been stored in this corpus yet."
```

**Claims 1–3 all stayed green under that inversion**, which is the argument for
claim 4 existing: an emptied MATERIAL still has its tab strip, so the floor
assertions go on passing against a region with nothing in it.

### One finding that is not a floor

Claim 1 **polls** rather than reading once, and the reason is a real property of
the page. `GraphCanvas` sizes its canvas from a `ResizeObserver`, and an
observer fires after the layout it observed. Measured: immediately after
narrowing to 1181 the graph container's border box is already 352 while the
`<canvas>` inside it is still the 411 it was handed at 1440 — seven boxes
reporting `411 in 352`, all the canvas or an ancestor. It settles within a few
frames. A single read there fails against correct code, which is precisely the
failure `CLAUDE.md` warns gets filed as flakiness. It is transient and I am not
calling it a defect; a reader who resizes sees a stale canvas for a frame or
two.

## 6. B56 — decided: the three utilities are gone

**What I saw**, measured in Chromium on 2026-08-14 with
`focus-visible:outline-2 focus-visible:outline-offset-2
focus-visible:outline-accent` **still on the span**, on a genuinely clipped
`EntityRef` label at 200px:

```
outlineStyle  'solid'
outlineWidth  '2px'
outlineOffset '1px'     <- the utility asks for 2px
```

and with the three utilities deleted: **identical**. The offset is the tell —
the utility names 2px and the element draws the global rule's 1px, because
`tokens.css`'s `:focus-visible` is unlayered and beats `@layer utilities`
regardless of specificity. The width and colour agree only because the global
rule already gives exactly what the utilities asked for.

**Deleted, not repaired.** The house fix for a real override is a named class in
a stylesheet (`.lay-ring-inward` is the precedent), and here that would buy one
pixel more offset on every truncated label and detail in the console — a visual
change to a shared primitive, made blind, to honour a declaration nobody wrote
for a reason. B56 asked for that call to be made by someone looking at it. The
ring the console gives every other focus stop is the right ring for this one.

`clsx` went with them — it had no other use in the file. The argument is
preserved in a comment where the utilities were, so the *absence* is documented
rather than looking like an omission.

The measurement lives in a new case in `TruncatedText.browser.test.tsx`, which
asserts the ring is there and visible and asserts none of the numbers the
deleted utilities named. **It would have passed before the deletion too — that
is the point of it, and it is why the deletion is safe rather than why the test
is weak.** It is stated that way in its docstring rather than left as
reassurance.

## 7. Verification

Serially, never two vitest processes.

- `npx vitest run --project browser src/presentation/project/project-tracks.browser.test.tsx` — 4 passed
- `npx vitest run --project browser src/presentation/common/TruncatedText.browser.test.tsx` — 5 passed
- `npm run test:browser` — **22 files, 68 tests, all passed** (was 21/63; +1 file, +5 tests, no regression)
- `npx vitest run src/presentation/common/TruncatedText.test.tsx src/presentation/entity src/presentation/project/ProjectView.test.tsx` — 53 passed
- `npx vitest run src/presentation/layout src/presentation/project` — 50 passed
- `npx tsc --noEmit` — clean
- `npx eslint` on all four files — clean
- `npx prettier --check` on all four files — clean

Not run, per the brief: `npm run verify`, the full jsdom suite, the Python gates.

## 8. Left undone, and one thing for the lead

- **A stale comment in task A's file, which is A's to fix or the lead's.**
  `responsive.css:76-78` argues against three columns in the 821–1180 band by
  saying "`PROJECT_TRACKS` floors sum to 880px". They now sum to **1038**. The
  argument is strengthened, not weakened — three columns fit that band even less
  well — but the number is wrong. I did not edit A's file.
- **Task A's vacuous 46vh assertion.** As the brief predicted, this fixture
  would make it measurable: MATERIAL here holds six documents and a graph and
  would exercise the cap. `project-responsive.browser.test.tsx` is A's file and
  I did not touch it. The fixture in my file is copyable as-is.
- **Seeding the collapsed set** so a flank starts railed in the 821–1180 band —
  A rejected the lead's prior on the grounds that it cannot be done from CSS and
  needs `use-project-panes.ts`, my file. It was not in my brief's five items and
  I did not do it. It remains available and cheap.
- **The weights are unmeasured**, as §4 says. Measuring them means deciding what
  "reads better wide" means well enough to assert, which is a research question
  rather than a test.
- **Nothing below 1181 was measured here.** That band is task A's, and my file's
  every claim is at or above `--bp-wide`.
- **The graph canvas's stale frame after a resize** (§5) is recorded and not
  filed. If anyone wants it in `BACKLOG.md`, that is Task C's file.
