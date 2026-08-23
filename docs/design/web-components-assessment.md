# Moving the console to WebAwesome and web components

Written 2026-08-23, against `main` at 5b08f66. Every number below was
measured in this checkout, not estimated.

## The ask

Move the console to WebAwesome and web components. Centralise on Storybook.
Improve maintainability and visual design. Restructure around the use cases.

## What is here now

| Measure | Count |
|---|---|
| Components (`.tsx`) | 295 |
| Test files | 187 |
| Browser-mode tests | 36 |
| Tests that read `getComputedStyle` | 35 |
| Tests that query by role or `screen` | 140 |
| Stories | 29 |
| `className` attributes | 1010 |
| Files that use Tailwind utilities | 57 |
| Class rules in `src/styles/*.css` | 402 |
| Stylesheet lines | 6031 |
| Radix primitives in use | 5 |

The frontend has a hexagonal structure: `domain`, `application`,
`infrastructure`, `presentation`. Only `presentation` holds markup.

## The finding

**A full port to web components is not the correct next step. Three
measurements say so.**

### 1. Shadow DOM stops Tailwind at the boundary

WebAwesome components are Lit based. Lit renders into shadow roots. A
Tailwind utility class is a document-level rule. It does not cross a shadow
boundary.

This repository has 1010 `className` attributes and 402 stylesheet rules.
Both groups apply from the document. Each component that moves into a shadow
root loses all of them. It must then get its style from WebAwesome custom
properties instead.

The design tokens survive. CSS custom properties **do** inherit through a
shadow boundary, so `--accent`, `--fg-dim` and the rest keep working. The
utilities and the 402 class rules do not.

### 2. The test suite queries the light DOM

140 test files query by role or through `screen`. Testing Library does not
pierce a closed shadow root, and it treats an open one inconsistently across
queries. A component that moves into a shadow root makes its own tests
either fail or need a rewrite.

35 files read `getComputedStyle`. `CLAUDE.md` records why: jsdom lays nothing
out, so a computed style is only trustworthy in browser mode. Those 35 are
the tests that hold the geometry the console was corrected on. They are the
most expensive tests here to re-derive.

### 3. The cascade knowledge in `CLAUDE.md` is build-specific

`CLAUDE.md` holds five separate entries about this build's cascade:
`border-solid` beside a directional width; `border-0` beside a bare `border`;
the unlayered `:focus-visible` rule in `tokens.css` that beats any utility;
the `--tw-border-style` registration; the `.lay-ring-inward` fix.

Each was measured in Chromium, and each cost a defect to learn. All five are
about Tailwind v4 and the document cascade. None of them transfer to a
shadow-DOM build. The replacement knowledge does not exist yet and would be
paid for the same way.

## What the port would cost

The work is not "swap a Button". It is:

1. Re-express 402 stylesheet rules as WebAwesome custom properties or as
   `::part()` rules.
2. Rewrite the queries in some part of 140 test files.
3. Re-take 35 computed-style measurements in the new build.
4. Re-measure the bundle budget. WebAwesome adds Lit plus each component.
   The current budget is set per chunk and is deliberately tight.
5. Replace 5 Radix primitives. Radix supplies focus management and the
   dismissable-layer stack that `Popover.tsx` documents. WebAwesome supplies
   its own. The two do not compose.

None of that is impossible. All of it is a rewrite of the layer that holds
the most measured knowledge in the repository.

## What is worth doing instead

The parts of the ask that do not need the port:

**Storybook coverage.** 29 stories for 295 components. Storybook is the
place a visual change can be judged, and today it shows about 10% of the
console. This is the highest-value item and it carries no architectural
risk. It also makes any future port safer, because a story is the before
picture.

**Primitive consolidation.** `primitives.tsx` is 154 lines and holds Button
and Chip. The comments in it record that the console had "three subtly
different empty states and four spellings of the same chip" before it
existed. More of the console can move behind that door. This is the same
maintainability gain the port promises, at a fraction of the cost.

**Design tokens as the seam.** If a port ever happens, custom properties are
the one thing that survives it. Work that moves a literal into a token is
never wasted.

## A smaller version of the ask, if the port is still wanted

Do not port the console. Port one leaf.

Pick a component with no children, few tests and no computed-style
assertion. Build it twice: as it is now, and as a WebAwesome-based custom
element. Measure the bundle change, the test rewrite and the token
coverage. Then decide with numbers instead of with this document.

`Chip` is the correct candidate. It is 40 lines, it is rendered by 17 files,
and its styling is already split into a shape constant and a dress constant.

## What was done instead, and what it showed

Storybook coverage and primitive consolidation -- the two items above that
need no decision. Landed as #245 and #248.

Nine components that had no story now have one, chosen by call-site count
rather than by convenience: `primitives`, `Drawer`, `Choices`, `VirtualList`,
`ConnectionBadge`, `DerivedFromLine`, `Mcq`, `ScrubBar`, `SessionForest`.

**Writing them found five defects, which is the evidence for the
recommendation above.** None needed a new framework:

1. Two button implementations, sharing no substring so no grep found them.
   `.cmp-btn` differed from `.btn` by 1px of padding, one colour tier, and an
   accent outline against an accent fill for the primary action. Merged.
2. The loading skeleton was 84px against a row estimated at 108, so a pending
   landing page moved about 96px -- the exact jump the skeleton exists
   instead of.
3. The material tab strip's real gate lives in the browser suite, which CI
   does not run, so a twelfth tab merged green. A tripwire now runs in CI.
4. `main` was red on an unrelated authoring-restart race, blocking every
   pull request. Fixed in #246.
5. A story fixture gave five sessions the same id prefix, so the gallery
   taught that the id column carries nothing. Found by screenshotting the
   page -- the only one of the five that came from looking rather than
   measuring.

**And the look was checked rather than assumed.** Buttons, chips, the session
rows, a three-deep fork lineage and a graded question were screenshotted
through vitest's browser mode. Nothing needed redrawing. The lineage view
reads clearly at three levels of nesting, the chips carry state without
colouring the rows they sit on, and the amber-on-dark palette holds. That is
worth stating plainly in a document about a UI overhaul: **the console does
not need one.** It needed the coverage and it needed the skeleton to be the
right height.

Which is the argument for the leaf experiment above rather than against it.
If a port is still wanted, `Chip` is where to find out what it costs -- and
there is now a story to compare the result against.
