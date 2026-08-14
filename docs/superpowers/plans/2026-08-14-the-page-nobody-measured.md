# The page nobody measured

A slice against `BACKLOG.md` B57 and `increment-c-plan.md` §6 open question 3,
written 2026-08-14 on branch `increment-d-scoping` off `origin/main` (2081660).

## 0. Why this is the next thing, when no document says so

**Increment C is complete and there is no increment D.** The overhaul corpus
defines increments only to C; everything past it is residue — backlog entries,
unowned audit findings, and four open questions. Nothing groups them.

So this slice is chosen rather than inherited, and the reason it is chosen
first is that it is the only candidate that is *measurement rather than
redesign*, needs **no backend budget** (so it does not compete with B58, B59
and §4's `GET /api/capabilities`, which all want the same one), and has been
deferred by four consecutive slices, each promising the next would do it.

## 1. What the survey found, which is worse than B57 says

B57 says the widths are "chosen, not measured". True, and secondary.

**The real finding: the project page has no layout between 821px and 1180px.**

- `Split.tsx:71,99` — `splitTemplate` returns `undefined` when `!wide`, so no
  inline `gridTemplateColumns` is written below `--bp-wide` (1181px). This is
  deliberate (`:95-98`): it hands the band to media queries.
- `layout.css:124-141` — the fallback is a bare `.lay-split { display: grid }`
  with no template, and the comment says outright that "a view with three panes
  declares its own middle arrangement -- the session view does, in
  `responsive.css`."
- `responsive.css:26` — the only rule in the 821–1180 band is
  `(width >= 821px) and (width < 1181px)`, **scoped to
  `.lay-split[data-split='session']`.**
- `ProjectView.tsx:278` renders `<Split id="project">` → `data-split="project"`
  (`Split.tsx:93`).

**The project view never declared its middle arrangement.** In that band the
three regions resolve to one grid column — three panes stacked, each still
drawing itself as a column — and a collapsed pane still asks for a 34px rail
(`Pane.tsx:105-108,126`, deliberately keyed on `stacked` not `!wide`) with no
grid track sized to give it one.

Below 821px `layout.css:144-159` finally makes the stack deliberate (flex
column, `.lay-pane-body` capped at `60vh`), so the broken band is bounded on
both sides by bands that work. That is why nobody found it: the failure is in
the middle.

**None of this is reasoned from CSS alone — it is what a measurement must
confirm or refute before anything is changed.** See §3.

## 2. The enabling fact, and the spike that must prove it

The browser suite's viewport is fixed for the whole run at 1440×900
(`vite.config.ts:288`), and `vite.config.ts:280-287` explains why that matters:
a media query reads the *viewport*, not the width of the wrapper a test renders
into. `layout.browser.test.tsx` failed on exactly that once.

`page.viewport(width, height)` exists in the installed `@vitest/browser`
(`^4.1.10`, `context.d.ts:816`, "Change the size of iframe's viewport").
**Zero tests in this repository use it**; all nineteen treat 1440×900 as fixed
and say so in prose.

So the first work of this slice is a spike, and it is allowed to kill the
slice's shape:

> Prove that `page.viewport()` re-triggers `matchMedia`, that `useWide`'s
> `useSyncExternalStore` subscription (`use-wide.ts:33-51`) observes the change,
> and that React has re-rendered before a measurement is taken.

If it does not work, the fallback is a second vitest project with a different
`viewport` — more config, more wall-clock, same coverage. **Report which one you
are on; do not quietly pick the fallback.**

Two hazards to handle rather than discover:

- **The viewport is global to the run.** No `afterEach` resets it anywhere
  today. A test that resizes and does not restore leaks into every sibling
  *in file order*, which is the kind of failure that looks like flakiness.
  Restore it, and say in a comment that you are doing so because nothing else
  will.
- **Awaiting the resize is not awaiting the re-render.** Measure through
  `expect.poll` or an explicit wait for the changed layout, never a bare
  `await page.viewport(...)` followed by a read.

## 3. Tasks

**These run one at a time, not in parallel.** `CLAUDE.md`: do not run two
vitest processes at once, and both A and B are browser-suite tasks. Task C
touches no test and may overlap either.

### Task A — the band (owns `responsive.css`, one new test file)

1. Do the §2 spike first. Report the outcome before building on it.
2. **Measure the 821–1180 band on the real `ProjectView`** before changing
   anything, and write down what it actually does. §1 is a reading of the CSS;
   the assertion belongs to the browser. If §1 is wrong, say so — that is a
   result, and it is worth more than the fix.
3. If it is broken as described, declare the project view's middle arrangement
   in `responsive.css`, scoped to `[data-split='project']`, mirroring how the
   session view declares its own.
   - **Which arrangement is your call, made against a measurement, not a
     preference.** My prior, offered to be overridden: HOLDER is the region
     that reads better wide and is the one a reader watches (per
     `use-project-panes.ts:21-41`); the two flanks are interchangeable. Two
     columns with a flank collapsed to its rail is the shape I would expect to
     survive. State what you chose and what you rejected.
   - The rail is the specific thing to check: `Pane` asks for a 34px rail in
     this band and no template grants it one.
4. New file `project-responsive.browser.test.tsx`. **Do not touch
   `ProjectView.browser.test.tsx`** — task B does not either, but the reason
   here is that its docstring `:34-36` correctly scopes the whole file to
   "above `--bp-wide`, the only band in which a `Split` writes a template at
   all", and that sentence stays true.
5. Prove each test red. A test that passes against the unfixed CSS is measuring
   the wrong thing.

**Out of scope, deliberately:** making the middle arrangement `Split`'s job
rather than each view's. Two views declaring it is the signal, three would be
the case; note it, do not build it. Changing the session view at all.

### Task B — the widths (owns `use-project-panes.ts`, one new test file)

Runs **after** A reports, because A may change what the page does.

1. `PROJECT_TRACKS` (`use-project-panes.ts:42-46`) is
   `queue 280/1`, `holder 320/1.5`, `material 280/1` — at ≥1181px the template
   is `minmax(280px,1fr) minmax(320px,1.5fr) minmax(280px,1fr)`, minima summing
   to 880px.
2. **Render all three regions with real content, including the graph** — the
   docstring defers to "the slice that gives each region its real content", and
   the graph is the widest thing the page has. That deferral is the one this
   slice is honouring.
3. Measure where each region *stops being usable*, which is the number the
   docstring says matters. Then either confirm the three numbers or change
   them.
4. **Rewrite the docstring either way.** It currently opens "**These numbers
   are chosen, not measured, and that is a known gap rather than a claim**" and
   points at plan §6.3. After this slice it must say what was measured, at what
   widths, on what date — in the shape `SESSION_TRACKS` already uses, since
   that one records its values as browser-confirmed and is the house precedent.
   **Confirming the existing numbers is a real result**; do not change them to
   have something to show.
5. New file `project-tracks.browser.test.tsx`.
6. **B56 is yours to decide, because you are the one with eyes on it.**
   `TruncatedText.tsx:127` writes three `focus-visible:` utilities that are all
   inert — they sit in `@layer utilities` and lose to `tokens.css`'s unlayered
   `:focus-visible`. B56 says "do it when someone can look at it, and decide
   then whether the intent was 2px or whether the utilities should simply go."
   Decide, and record the decision with what you saw. The offset it asks for is
   positive, so there is no clipping and no visible symptom — the defect is
   three utilities claiming to work.

### Task C — the record (owns `BACKLOG.md` and the two plan documents)

Touches no code and no test.

1. **B54 (the first one, `BACKLOG.md:23`) is stale and must be marked so.** Its
   premise is the half of `CLAUDE.md`'s border rule that **B55 withdrew on
   2026-08-13** by reading the committed built stylesheet — Tailwind v4 emits
   the style longhand with the width and registers `--tw-border-style` with
   `initial-value: solid`, so a directional width alone draws.
   `border-style-default.browser.test.tsx:53` proves it. B55 was filed on that
   premise and retracted; B54 was filed on the same premise and never updated.
   **Mark it in place with the house's correction convention — do not delete
   it**, and do not restate the correction where it has already been made.
   Check first whether it already has been.
   - Its line numbers are also stale: `GateReview.tsx:135`→`:143`,
     `AutonomyAllowAll.tsx:78,95`→`:101,:118`. `DecisionBar.tsx:44` is correct.
   - The *inverse* trap — `border-solid` **without** `border-0` giving three
     sides a width — remains real and is covered by
     `border-style-default.browser.test.tsx:73`. Do not retract that.
2. **`increment-c-plan.md` §6 question 3 and B57** get the outcome of tasks A
   and B. Wait for both. Q3 has been deferred five times; if this slice
   answers it, say so where the deferrals are recorded, not only in a report.
3. **Record that there is no increment D.** The corpus stops at C and the
   residue is ungrouped; the survey behind this slice found eight or so items
   with no owner. One short section naming them, in whichever of the two
   documents is the right home, is worth more than another slice discovering
   it. Do not invent an increment D to hold them — naming the residue is the
   deliverable, scoping it is not.

## 4. What this slice does not do

- **No backend.** B58, B59 and `GET /api/capabilities` all want the same
  budget and none of them is here.
- **`course.css`'s death.** Still unowned, still waiting on QUEUE's rail,
  roster, extraction pane and autonomy panel being rewritten.
- **Open question 5 — whether the picker deserves to be a page.** Slice 4
  declined it as a redesign rather than a slice. Unchanged.
- **The middle arrangement as a `Split` primitive.** §3 task A.

## 5. Verification

All four gates, plus — and this is the one slice where it is not optional —
`cd frontend && npm run test:browser`. The entire slice is computed styles and
measurements, which is the case the fifth command exists for.

Serially. Never two vitest processes.
