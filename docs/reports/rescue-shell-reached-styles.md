# Rescuing the shell-reached styles

Implements findings 1–4 of `docs/reports/stylesheet-orphan-sweep.md`. Findings
5–9 are deliberately untouched and stay with task #51.

## The hazard

Four sets of rules in *view-scoped* stylesheets were written by components the
shell renders on **every route**. The route merge deletes `course.css` first,
and deleting it would have unstyled things still on screen with nothing
failing — jsdom applies no stylesheet, so no test could see it, and a class
that resolves to nothing raises no error. It was found by a sweep, not by a
failure, because there is no failure to have.

## What changed, and why each fix is the one it is

**1. `.drawer*` (`course.css`) → utilities on `presentation/common/Drawer.tsx`.**
The largest one: `position: fixed`, the right-anchored 42vw box, the surface,
the border, the flex column and the body inset. Values carried across
unrounded — `w-[42vw]`, `max-w-[640px]`, `min-w-[360px]`, `px-[12px]`,
`pb-[16px]` are arbitrary because 42vw, 640, 360, 12 and 16 are on no scale in
this project (3/6/10/14/20/28). Task #42's measurement (the body's horizontal
inset is the head's 12px, with the x=743/x=1280/x=755 figures) moved verbatim
into the component rather than being paraphrased.

`Drawer` still writes `drawer` as a **class**, now a hook rather than a rule:
`responsive.css` narrows the panel below 820px and is a shared stylesheet that
survives the merge.

*An incidental behaviour change, stated because it is one.* That narrow
override did not previously apply. `index.css` imports `responsive.css` **above**
`course.css`, both selectors were `0-1-0`, and the later file won — so the
drawer stayed 42vw below 820px. With the base as `@layer utilities`, the
unlayered `.drawer` in `responsive.css` now wins and the panel goes full width
as that rule always intended. This is a fix, at one breakpoint, in the
direction the rule already stated. It is not covered by a test: the browser
suite's viewport is 1440px, set in `vite.config.ts`.

**2. `.chip` base (`tree.css`) → `CHIP_SHAPE`/`CHIP_DRESS` in `primitives.tsx`.**
The severity tones (`course.css`) → `SEVERITY_DRESS` in `GateReview.tsx`.

**3. `.autonomy-warn` / `.autonomy-error` → utilities on `AutonomyAllowAll.tsx`.**
The rules **stay in `course.css`** for `AutonomyPanel`, which is a genuine
course-page surface and dies with the file. The old argument for leaving them —
"they are shared, so converting them would be the forbidden port" — was the
wrong test: sharing is not what makes a port forbidden, dying with the wrong
screen is. The cost is one duplicated look until `course.css` is deleted.

**4. `.btn-quiet` → moved to `shell.css`, not converted. This is the one
deviation from the brief, and the reason is a cascade fact rather than a
preference.**

`Button` renders `.btn`, and `.btn` in `shell.css` sets `background`,
`border-color` and `color` **unlayered**. Tailwind's utilities are imported into
`layer(utilities)`. Unlayered beats layered regardless of specificity, so
`bg-[transparent]` on a `.btn` loses outright. Making utilities win needs
`!important` on four declarations plus two hover states — a fight with `.btn`
written into every quiet button forever. The alternative considered and rejected
was dropping `.btn` for quiet buttons and dressing them wholly in utilities;
that duplicates `.btn`'s padding, radius, transitions, disabled and
`aria-pressed` states and guarantees the fifth tone drifts from the other four.

The move is not the relocation the standing policy forbids. `.btn-quiet` was in
`composer.css`, which dies with the session composer, while `.btn`,
`.btn-accent`, `.btn-danger`, `.btn-ghost` and `.btn-sm` have always been in
`shell.css`. A tone of a primitive filed apart from the primitive was the
accident; this closes the split. `shell.css` dies with the shell, and so does
`.btn`. `shell.css` carries the argument at the rule; `check-deleted.mjs`
forbids the name anywhere else under `src/styles/`, `composer.css` included.

## The Chip-tone design decision

`Chip`'s public API keeps `tone?: string` working, untouched, for the view tones
still coming from stylesheets (`chip-fork`, `chip-done`, `chip-run-bad`, …). A
second optional prop, `dress?: string`, takes utility dressing that **replaces**
the default colour trio.

Replacement rather than override is the load-bearing part. Two utilities setting
the same property both land in `@layer utilities`, where the winner is
Tailwind's own sort order and **not** the order of the class attribute — so a
base `text-fg-dim` sitting beside a `text-k-failure` is a coin toss that would
be discovered visually. Passing one string or the other has one answer.

The map lives in `GateReview.tsx` because `severity` is the reviewer prompts'
own free string and the mapping from it to a look is knowledge that component
already owns. A severity the map has never seen gets the default dressing —
which is exactly what an unknown `chip-${severity}` class already produced.

Hexes are named where a token exists (`#241417` is `--color-tint-fail`,
`#45272a` is `--color-tint-fail-line`, `#241d10` is `--color-tint-held`,
`#1a1630`/`#3a3060` are the session tints). `critic_gate`'s `#2b3a42` and
`#121b20` have no token and stay arbitrary rather than being rounded.

## The `.sub` decision

**Given the dressing it was meant to have, on three of four elements; dropped
outright on the fourth.**

`.sub`'s only definition under `src/styles/` is `tree.css`'s `.view-head .sub`,
which needs an ancestor the decision bar has never provided — so the dimmed
secondary text `AutonomyAllowAll` has been asking for since it moved has been
rendering at full `--fg` all along. The intent is unambiguous (every `.sub`
there is a subordinate line beside a `<strong>` or under a heading), so those
three carry `text-fg-dim` now. `.view-head .sub`'s `font-size` and `margin-top`
are deliberately not carried: that is the landing view's heading rhythm and this
control is not a view head.

The exception is the scope warning, which also carried `.autonomy-warn`, whose
whole point is `color: var(--fg)`. It is the loudest line in the panel, not a
subordinate one, so `.sub` is simply gone there.

## `check-deleted.mjs`

`STYLESHEETS` is unchanged — no stylesheet was added or deleted. Three rules
were added and one existing `why` corrected:

- top-level `.drawer {`, `.drawer-head|title|spacer|body`, `.chip {` and the
  five severity tones, forbidden anywhere under `styles`. The patterns are
  anchored with `^…/m` and that is doing real work: `responsive.css`
  legitimately keeps an indented `.drawer` inside a media query, and a pattern
  that could not tell it from a base rule would fail on correct code.
- `.btn-quiet`, forbidden under `styles` **except** `shell.css`, via
  `only: /^styles\/(?!shell\.css$)/`.
- `autonomy-warn` / `autonomy-error` in `AutonomyAllowAll.tsx` only, via
  `only:` on the single filename — the directory also holds `AutonomyPanel.tsx`,
  which must go on using them.
- the existing phase-5 `.autonomy-allow*` rule's `why` said those two classes
  were absent from the list because they are shared. That reasoning is now
  wrong; it is corrected to point at the new rule.

## Tests

`src/presentation/common/shell-reached-dressing.browser.test.tsx`, five cases,
all asserting computed style. jsdom would return `''` for every one of them.

The last case is the one that matters and expresses the hazard directly: it
removes from the live document **every rule `course.css`, `tree.css` and
`composer.css` contribute** and re-measures. The selector list is read from the
three files with `?raw` rather than written out, so it cannot go stale silently,
and the helper asserts it removed more than 50 rules so the simulation cannot
rot into a passing no-op.

`sheet.disabled` was tried first and does not work here — measured, not assumed:
Vite compiles the whole `index.css` chain into **one** stylesheet of 777 rules,
Tailwind's `@layer utilities` block and `theme.css`'s tokens included, so
disabling it takes the utilities and the palette with it and proves nothing.

`.btn-quiet` has no browser case, deliberately: it did not become utilities, so
what holds it is the `check-deleted` rule, not a measurement. Said here rather
than left as a silent gap.

`Drawer.test.tsx`'s flush case moved from `.drawer-body` / `is-flush` class
queries to `[data-drawer="body"]` / `data-flush`. Keeping a class name after its
rule is gone would be the `.sub` orphan all over again.

## Every command run, with its real result

From the worktree root:

```
uv run ruff check .          → All checks passed!
uv run ruff format --check . → 230 files already formatted
uv run pytest -q             → 2370 passed, 9 deselected, 3 warnings in 505.73s
cd frontend && npm run verify → passed end to end (format:check, lint,
                                typecheck, test:coverage 1003 tests,
                                build, size 284.5 kB of 512 kB,
                                deleted "30 deletion rules hold, and 22
                                stylesheets stay frozen", check:tailwind)
cd frontend && npm run test:browser → 13 files, 38 tests, all passed
```

Two things worth recording rather than smoothing over.

**The first `npm run verify` failed with three timeouts** — `Composer.test.tsx`
"sends on Ctrl+Enter and clears the draft", `App.test.tsx` "opens a dialog…",
`Menu.test.tsx` "moves between items with the arrow keys" — all `Test timed out
in 5000ms`, on surfaces this change does not touch, in a run whose environment
setup took 835s. Re-run alone the three files gave 24 passed in 27.75s, and the
whole `verify` chain then passed end to end. Load, per CLAUDE.md's rule, and
recorded here rather than deleted.

**`typecheck` failed once on real grounds** and was fixed rather than worked
around: `exactOptionalPropertyTypes` rejects `dress={SEVERITY_DRESS[severity]}`
against `dress?: string`, because a `Record` lookup may miss. The prop is
`dress?: string | undefined`, with a comment saying absent and looked-up-and-
missing mean the same thing here.

## Proved red before trusted green

Each rescued family was neutralised, the suite re-run, and the failure recorded.

| Neutralisation | Cases that went red | What the browser reported |
| --- | --- | --- |
| `Drawer`'s box utilities stripped to `className="drawer"` | the fixed-panel case, the route-merge case | `expected 'static' to be 'fixed'` (both) |
| `Drawer`'s body inset utilities removed | the inset case, the route-merge case | `expected '0px' to be '10px 12px 16px'` (both) |
| `CHIP_SHAPE` and `CHIP_DRESS` emptied | the chip-shape case, the tone-override case, the route-merge case | `expected '13px' to be '10.5px'`; `expected '0px' to be '3px'`; `plain: expected '0px' to be '3px'` |
| `tree.css`'s `.chip-fork { color }` set to `unset` | the tone-override case | `expected 'rgb(215, 222, 231)' to be 'rgb(167, 139, 250)'` |

## The cascade assumption, and what checking it actually showed

The change rests on: unlayered stylesheet rules beat `@layer utilities`, so the
view chip tones still in `course.css` and `tree.css` go on overriding a
utility-based `.chip` base exactly as they overrode the stylesheet base. That
outcome is confirmed in Chromium by the tone-override case — `.chip-fork` still
draws `rgb(167, 139, 250)` on `--tint-session`, while radius and font size come
from the utilities.

One attempt to prove that case red is worth recording because it **failed to go
red**, and the reason is instructive. Wrapping `.chip-fork` in
`@layer utilities` inside `tree.css` did not flip the colour: both rules are
then in the same layer at equal specificity, and `tree.css` is imported after
`theme.css`, so it still wins on order. The layering claim is therefore not
directly falsifiable by that edit; what the test actually pins is the *outcome*,
and the `unset` edit above is what proves it can fail.

## What I could not verify

- **Appearance below 820px.** The browser suite runs at one viewport (1440x900,
  set in `vite.config.ts`), so the `responsive.css` behaviour change described
  above is reasoned from the cascade and unmeasured.
- **`.btn-quiet` pixels.** No computed-style case covers it; it is a stylesheet
  rule moved between two files without an edit, and its guard is
  `check-deleted.mjs`.
- **The doubled `background` in `.btn-quiet`** (`#24151700` then `#241517`) is
  a leftover, not a fallback. It was preserved verbatim rather than cleaned up,
  because deleting it in a filing commit would be an unrequested pixel change.

## Found in passing, out of scope, not fixed

`GateReview.tsx` also renders `<Chip tone="fail">blocked</Chip>` in its header,
and `.chip-fail` is in **`tree.css`**. That is the same hazard as finding 2 on
the same component — a shell-reached chip whose tone dies with the landing view
— and it is not among findings 1–4, so it was left alone rather than folded in
silently. It belongs with task #51, or with whatever takes `tree.css`.
