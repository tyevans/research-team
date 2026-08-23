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

So the work became coverage. 29 stories became 44, chosen by call-site count
rather than convenience.

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

## What is left, and where

B140 (browser suite in CI), B141 (nothing ranks the material tabs, so a
twelfth has nothing to displace), B142 (the story gate covers four of thirteen
directories, with counts and a suggested order).

One shape behind B142 worth naming: **`presentation/research` has 29
components and only 9 take props alone.** The rest fetch. That is the
directory's real coverage ceiling, and it is what `entity/project` already
fixed — `ProjectCard` was deliberately prised apart so everything that fetched
became a slot, which is what made its stories possible at all.
