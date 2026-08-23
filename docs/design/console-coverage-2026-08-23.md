# What the console's first Storybook pass found

Written 2026-08-23. An index to #245–#251, so the findings are readable
without reading seven pull requests.

## The brief, and what happened to it

The ask was a UI overhaul: move to WebAwesome and web components, centralise
on Storybook, improve maintainability and design, restructure around use
cases.

**The port is not recommended, and the reason is a measurement rather than
caution.** `web-components-assessment.md` has the numbers: shadow DOM stops
all 1010 `className` attributes and 402 stylesheet rules at the boundary; 140
test files query the light DOM; 35 read `getComputedStyle`; the five cascade
entries in `CLAUDE.md` are Tailwind-v4 specific and do not transfer. Design
tokens are the one thing that survives, because custom properties inherit
through a shadow root.

**The restructure was largely already done.** `facets-and-use-cases.md`
records that its own first draft was wrong: it proposed a `FACET_GROUPS`
constant before finding that `regionOf` already groups every facet and is
already asserted against `FACETS` itself. What was missing was one tripwire,
not a new grammar.

**The look was checked, not assumed.** Buttons, chips, session rows, a
three-deep fork lineage and a graded question were screenshotted through
vitest's browser mode. Nothing needed redrawing. The lineage view reads
clearly at three levels of nesting, chips carry state without colouring the
rows they sit on, and the amber-on-dark palette holds.

So the work became coverage. 29 story files became 53 and the test count went
from about 187 files to 216, chosen by call-site count first and later by
which components had states nothing had ever constructed.

## What that found

Seven defects, none of which needed a new framework.

| | what | where |
|---|---|---|
| 1 | **Two button implementations.** `.btn` everywhere, `.cmp-btn` in six lesson call sites. No shared substring, so no grep found them. Differed by 1px padding, one colour tier, and fill-versus-outline for the primary action. | #245 |
| 2 | **`main` was red**, blocking every PR — an authoring-restart test raced its own precondition. | #246 |
| 3 | **The loading skeleton was 84px** against a row estimated at 108, so a pending landing page moved ~96px — the exact jump the skeleton exists to prevent. | #248 |
| 4 | **The tab strip's width gate is in the browser suite**, which CI does not run, so a twelfth tab merged green. | #248 |
| 5 | **The accent stayed on a disabled button.** Introduced by fixing (1): `.btn-accent` fills where `.cmp-btn.primary` outlined, so after grading the loudest control was the dead one. | #248 |
| 6 | **A story fixture gave five sessions one id prefix**, teaching that the id column carries nothing. | #248 |
| 7 | **`.toast` was the one animation without a reduced-motion guard** — and it is the console's only *unrequested* motion. | #250 |
| 8 | **A toast makes five of the eleven material tabs unclickable**, and the ask route's header buttons too. Hit-tested, not eyeballed. Filed as B144: every corner collides with something on some route, so there is no one-line fix. | B144 |

| 9 | **A checklist told readers their ticks were saved on surfaces that save nothing.** `persist` is the author's request; `AttemptsApi.saveChecklist` is the surface's capability, left `undefined` on purpose so a widget can tell them apart. The widget read only the first. | #252 |
| 10 | **The compaction pane had three AA contrast failures**, two of them caused by an `opacity` that also contradicted the pane's own sentence about nothing being deleted. | #258 |
| 11 | **The timeline was an invalid grid** whenever a turn failed with content — the discarded block sat inside `role="grid"` as a bare sibling of the row. | #259 |
| 12 | **Scrubbed-past timeline rows sit at 1.7:1.** Recorded as debt rather than fixed: it is the only signal a row is in the future. B145. | B145 |

Findings 8 and 12 are the ones that needed something a gallery cannot give.
8 needed the *running application*: every toast story renders the stack over a
page, and this is the stack over the project page's **navigation** — no story
arrangement would have produced it. It was found by creating a project through
the browser and clicking the obvious next thing.

12 needed a *state* no test had ever constructed. So did 10 and 11: the
compaction pane and a failed turn's discarded content are both conditional
branches nothing had rendered, and each held a real defect the moment a story
reached it.

**That is the pattern worth carrying, and it is narrower than "write more
stories".** The yield came from reaching states nothing had constructed, not
from coverage as such — two of the last four components picked purely for
having many branches turned out clean.

Two of those — (5) and (6) — were found by *looking at the page*, not by any
assertion. That is the argument for the gallery, made against the gallery's
own output.

## The one that matters most

**A pull request merged with four green gates and left the browser suite
red.** #249's `Toasts` stories turned `a11y.browser.test.tsx` red with eight
contrast violations, and nothing said so.

The violations were phantoms — axe sampling a toast mid-fade, which the
drifting colour values gave away — and that is deliberately not the point. The
suite was red across four merged commits while every gate reported green, and
would have stayed that way until somebody ran `npm run test:browser` by hand.

This is B140, and it is no longer a prediction. **It is the one thing here
that wants a decision from you**, and it was left as a backlog entry rather
than taken: `CLAUDE.md` gives real reasons the browser suite is out of CI (a
minute against a second, a Chromium download, 923 jsdom tests competing for
the same budget), and reversing that on one instance is a bigger call than the
evidence supports. A middle option is noted — run it only on changes touching
`src/styles/**` or `presentation/layout/**`.

## The checklist bug, generalised — and the audit that followed

The checklist defect had a shape worth naming, because it is the only kind
here that a reviewer cannot catch by reading the component: **a UI that states
a capability without asking whether the capability is present.**

`AttemptsApi.saveChecklist` is optional *on purpose* — `use-attempts.ts`
leaves it `undefined` rather than a no-op so a widget can tell "the author
wants this saved" from "this surface can save". The component called it with
`?.` (correct) and rendered "saved as you go" unconditionally (not). Nothing
throws, the tick lands, and the label is the only thing that is wrong.

**So the whole console was swept for the same shape, and it is the only
instance.** Recorded as a negative result so the search is not repeated:

- **Optional members on application ports** — `saveChecklist` is the only
  capability-shaped one. The rest (`start`, `end`, `limit`, `entityType`,
  `from`, `to`) are data fields on query objects, not capabilities.
- **Optional calls in `presentation`** — four sites. Three are plain callbacks
  with no rendered claim attached (`onRefuse`, `onDismiss`, `onCreated`); the
  fourth was the checklist.
- **Optional props that gate a control** — `GraphDetail`'s `onRemove` and
  `showInGraphHref` are the pattern done right: both are rendered behind a
  presence check, and both docstrings say which caller supplies them and why
  the other does not.
- **Unconditional reassurance strings** — "saved as you go" was the only one.
  Every other status wording in the console derives from a state value
  (`status === 'running'`, `queued`, `not saved: …`) rather than asserting.

What that leaves is a rule rather than a fix: **an optional member on a port
is a question the consumer has to ask.** If a component renders anything that
would be false when the member is absent, presence is part of the condition.

The other defect in the table generalises too, and that sweep is also clean.
The accent-on-a-disabled-button bug was not "an accent button is disabled" --
that is ordinary and correct, and most primaries in the console are disabled
while busy or until a form is valid, because a reader still needs to see where
the action is. It was **an accent on a dead control while a different control
was the live one.** Every `tone="accent"` in `presentation` was checked against
that: each is either the sole action of its form or one-per-row (`ProjectList`
renders `Resume` plain beside an accent `New session`, or a single accent
`Open`). The lesson widgets were the only place the condition arose, and it
arose because this series put it there.

## One surface is unstoryable by design, and that is the right answer

An attempt to give `Approvals` a story was reverted, and the reason is worth
recording because it looks like a coverage gap and is not one.

`check-deleted.mjs` phase 3 forbids importing `Approvals` from anywhere but
`DecisionBar`. The rule is not fussiness: approvals used to be rendered per
session from three call sites -- the conversation footer, the worker drawer,
and the course page through that drawer -- and each showed only the approvals
of the session already on screen, so **"is anything waiting on me?" had a
different answer on every page** and the honest way to find out was to open
every session in turn. One bar subscribed to the whole feed replaced them.

And `DecisionBar` itself is in the story allowlist, because it renders from
`useApprovalFeed` and returns `null` when nothing is pending -- a story is
either a mock of the feed or a blank page.

So the surface has no gallery entry, from both directions at once. **Weakening
the deletion rule to admit a story was considered and rejected**, on the
grounds that it would contradict the allowlist argument written earlier in
this same pass: if a mock-driven `DecisionBar` story is "a story about the
mock", then a story that reaches around the bar to render its component
directly is worse -- it is a picture of an arrangement the console is
forbidden to have.

The general form, since it will come up again: **a deletion rule that forbids
an import is a statement about the component's only legitimate caller.** A
story is a caller. Where the two collide, the rule wins, and the absence is
documented rather than engineered around.

## Conventions the pass settled on

Worth knowing before adding to any of this, because they are why the tests
read the way they do.

**A story that cannot be trusted on sight gets a companion test.** The axe
sweep globs stories and catches one that *throws*; a story rendering an empty
div passes it. `VirtualList` is the worked example — its failure mode is a
correctly sized box with nothing in it, so a story reproducing the bug looks
exactly like a story of an empty list.

**Assert differences, not presences.** "The historical bar says time travel"
passes on a build where the live bar says it too — and that build is the
defect. Every mode marker, every empty-state wording and every accent is
asserted as a pair.

**Say what a test cannot see.** Several of these files carry an explicit
paragraph naming what they do not cover — the dialogue glow's colour, the
legend's swatches, the ontology tree's nesting. A test named after a hazard it
cannot detect is worse than no test.

**Run the browser suite before pushing.** Not after merging. That is (4) and
the #249 incident, learnt twice.

## What a clean sweep looked like, twice

Worth recording because it is the half nobody writes down. `FileList` and
`Artifacts` were both picked as likely defect-bearers — one for its ARIA
claim, one for having the most unexercised branches of any props-only
component — and both came back clean under axe and under their own rules.

`Artifacts` in particular has four bespoke chip dresses with arbitrary hexes
that no token holds, and all four clear AA. That is a real result about the
console's colour discipline rather than an absence of one.

## What is left, and where

B140 (browser suite in CI), B141 (nothing ranks the material tabs, so a
twelfth has nothing to displace), B142 (the story gate covers four of thirteen
directories, with counts and a suggested order), B144 (a toast makes five
material tabs unclickable; every corner collides with something on some
route), B145 (scrubbed-past rows at 1.7:1).

**Three of those want a decision rather than an implementation**, and they are
the reason this document exists rather than a longer branch: B140 trades CI
time against a suite that caught two real defects CI did not; B144 has three
fixes that each give something up; B145's dimming is the only signal a row is
in the future. Each has a documented rationale on the other side, which is
what makes them somebody's call rather than mine.

One shape behind B142 worth naming: **`presentation/research` has 29
components and only 9 take props alone.** The rest fetch. That is the
directory's real coverage ceiling, and it is what `entity/project` already
fixed — `ProjectCard` was deliberately prised apart so everything that fetched
became a slot, which is what made its stories possible at all.
