# Frontend library adoption for the console reimagining

A decision record, not a survey. Every entry names the package, the version
checked, what it replaces, what it costs gzipped, and what this repository has
to give up to take it.

Written because `console-reimagining-roadmap.md` carries a standing constraint
— *"lean hard on frontend libraries where they cut effort and improve
maintainability, rather than hand-rolling"* — and that is a deliberate reversal
of this console's current default. A reversal stated as one sentence is not a
thing three agents can build against consistently.

Versions were checked against the npm registry and the web on **2026-08-27**.
Anything here older than that should be re-checked before it is pinned.

## Take these first

1. **`class-variance-authority` — already installed, used in exactly one
   file.** Free maintainability, zero bundle delta.
2. **Light/dark via `light-dark()` and `@custom-variant` — no library.** It
   collapses the double palette instead of tripling it.
3. **`@tanstack/react-virtual` — already installed, three consumers.** The
   catalog and index pages are the two surfaces that most need it.
4. **`cmdk@1.1.1` — yes, but only `Command`, never `Command.Dialog`.**
5. **`motion@13.1.1` behind `LazyMotion` and `m`.** ~4.6 kB initial, and it
   needs a `prefers-reduced-motion` bridge this repo does not have today.

Items 1-3 cost nothing in bundle size. Items 4-5 are the only two new
dependencies this document recommends.

---

## What is already paid for and not used

This is the highest-value section. A dependency already installed and not used
is free maintainability.

### `class-variance-authority@0.7.1` is imported by one file

One import in the entire tree: `presentation/entity/EntityStatus.tsx:1`, a
single `cva('ent-status', { variants: … })`. Everything else selects variants
by hand with `clsx`, and `presentation/common/primitives.tsx` shows what that
costs:

- `Button` builds its tone as
  ``clsx('btn', small && 'btn-sm', tone !== 'default' && `btn-${tone}`)`` — a
  template-interpolated class name, which is the one shape Tailwind's scanner
  cannot see and `scripts/check-tailwind.mjs` cannot check.
- `Chip` carries a twenty-line comment explaining that `CHIP_DRESS` must be
  *replaced* rather than overridden, "because two utilities setting the same
  property both land in `@layer utilities`, where the winner is Tailwind's own
  sort order and not the order of the class attribute". That is a hand-written
  statement of the problem `cva`'s `variants` / `compoundVariants` /
  `defaultVariants` exists to make structural. The `dress` escape hatch — which
  the file admits has **no production caller today**, and is kept only because
  `shell-reached-dressing.browser.test.tsx` measures it — is a variant slot in
  all but name.

**Cost:** zero. The package is already in the bundle for one component.

**What we give up:** a component's appearance becomes readable in two places —
its `cva` table and its stylesheet. During the phase-5 migration, where a
tone's rule may still live in `tree.css` or may already be a utility, that
split is genuinely confusing. **Do this after the `:root` collapse, not
before.**

### `@tanstack/react-virtual@3.14.10` has three consumers

It is reached only through `presentation/common/VirtualList.tsx`, used by
`tree/ProjectList.tsx`, `tree/ProjectRows.tsx` and
`research/DocumentBrowser.tsx`. The index page (roadmap §4) and the catalog
(§5) are exactly the two surfaces where "as friction free as possible" means
not rendering four hundred rows.

**This is a reuse, not an adoption — but not a drop-in.** `VirtualList` is
built around a fixed row height. A catalog of cards is variable-height and
needs `measureElement`. That is a real extension to `VirtualList` with its own
browser measurement, and it should be scoped as such rather than assumed.

### `zod@4.4.3` is used well — leave it alone

Thirteen files, all under `infrastructure/http/`, parsing DTOs at the seam.
There is no gap here. Resist completing the picture with `react-hook-form` and
`@hookform/resolvers`: the forms in this console are `SeedForm`,
`NewProjectForm`, `AskComposer`, `Composer` and `DialoguePage`, each one or two
fields with a `canSubmit` boolean. That is roughly 13 kB gzipped to manage
state that is currently three `useState` calls.

### Radix is used correctly, and the one gap is not worth closing

Five packages plus `react-dismissable-layer`, used as a positioning and ARIA
engine only, with `OverlayHost` deliberately taking dismissal back. That
factoring is right and is argued in `Tooltip.tsx:17-27`.

The visible gap is `primitives.tsx`'s `Disclosure` — a hand-rolled
`aria-expanded` / `aria-controls` pair with **seventeen consumers** — which
`@radix-ui/react-collapsible` would replace.

**Verdict: do not.** `Disclosure` is thirty lines, its docstring correctly
explains why it is not `<details>` (the open state must survive a re-render
driven from elsewhere), and Radix Collapsible's real value is animated height
measurement, which this console does not do. A sixth Radix package for thirty
lines is churn.

---

## 1. Theming and light mode

**No library is warranted. This is a `@theme` plus `light-dark()` plus
`@custom-variant` job.**

### The state today

`tokens.css`'s `:root` and `theme.css`'s `@theme` hold the same ~40 colours
twice. `theme.test.ts` fails on divergence. `theme.css` names the exit: *"Phase
5 deletes the `:root` block and leaves this one."* `tokens.css:34` hard-codes
`color-scheme: dark`, with `color-scheme.browser.test.tsx` pinned to it. The
roadmap already says a second palette on top of a palette written twice is four
places for one colour.

### `light-dark()` makes it one place, not two

```css
@theme {
  --color-bg: light-dark(#fbfbfa, #0b0d10);
  --color-fg: light-dark(#1a1d21, #d7dee7);
}
```

Each token holds **both** values in one declaration, in one file, and the
switch is a single `color-scheme` property. No `.dark` block, no duplicated
`@theme`, no second palette to hold in sync. That means the phase-5 collapse
and light mode become the *same* commit rather than two, and ~~`theme.test.ts`
keeps working unchanged~~ — it was rewritten. With `tokens.css`'s `:root`
holding aliases rather than values there is nothing left to compare, so the
value-agreement assertion is deleted and what replaced it checks the *rename*:
every alias points at a token that exists, and every colour the theme declares
is aliased. `--fg-dim: var(--color-fg-dm)` is the defect it now catches, and it
types, lints, builds and paints magenta.

The switch:

```css
:root                { color-scheme: light dark; }  /* follow the OS */
[data-theme='light'] { color-scheme: light; }
[data-theme='dark']  { color-scheme: dark; }
```

And for Tailwind's own `dark:` variant — which in v4 defaults to
`prefers-color-scheme`, and where the `darkMode` config key no longer exists
because the JS config is gone:

```css
@custom-variant dark (&:where([data-theme='dark'], [data-theme='dark'] *));
```

**That one-liner is half a variant and shipped as two rules instead.** It
matches an explicit choice and nothing else, so every `dark:` utility would be
inert for `system` — the default, and the setting almost every reader is on.
The implemented form adds a `prefers-color-scheme: dark` arm matching
`[data-theme='system']`. Nothing writes a `dark:` utility today, which is
precisely why the broken half would have been found late.

### Browser support, specifically

`light-dark()` has been **Baseline newly available since 2024-05-13** — Chrome
and Edge 123, Firefox 120, Safari 17.5 — and is scheduled to reach **Baseline
widely available on 2026-11-13**, roughly three months from now. Global usage
was ~83% at the 2024 measurement and is higher now. For a console served from a
local FastAPI process to a developer's Chrome, this is not a risk. The fallback,
if it ever becomes one, is a plain `@media (prefers-color-scheme)` pair — which
is the thing we would otherwise be writing anyway.

### What we give up, and it is not nothing

- **A token's value stops being greppable as a hex.**
  `--color-k-compaction: #679aae` becomes a two-argument function, and the
  AA-contrast arithmetic in `tokens.css`'s comments now has to be stated twice,
  once per scheme. Every token raised for AA — `--color-fg-dim`,
  `--color-fg-faint`, `--k-compaction` — needs its light-mode ratio computed
  and written down. **That is the actual work of this phase.** Expect it to be
  larger than the mechanical diff, and expect the visual review to be larger
  still.
- **Tailwind's opacity modifiers must be measured, not assumed.** v4 implements
  `bg-accent/50` as `color-mix(in oklab, var(--color-accent) 50%, transparent)`.
  Nesting `light-dark()` inside `color-mix()` is legal per spec and works in
  current Chromium, but this repo's standing rule is that a computed style is
  measured in the browser project rather than reasoned about. **Write that
  assertion as a `.browser.test.tsx` before converting forty tokens.**
- **`GraphCanvas` and `entity-colors.ts` read tokens at runtime through
  `getComputedStyle`.** ~~That resolves `light-dark()` to the active scheme's
  colour, so it keeps working~~ — **this is wrong, and it was measured wrong on
  2026-08-28 before the implementation trusted it.** An *unregistered* custom
  property computes to its own token stream, so `getPropertyValue('--k-session')`
  hands back the literal two-branch expression, not a colour; `fillStyle`
  ignores an unparseable value in silence and keeps the colour it had. Three
  canvases would have painted in the previous entity's colour with nothing
  thrown and nothing logged.

  The fix is `@property { syntax: "<color>"; inherits: true }` on every colour
  token, which makes the property resolve at computed-value time. Measured in
  Chromium: the same value read back bare returns
  `"light-dark(#ffffff, #000000)"` and registered returns `"rgb(255, 255, 255)"`.
  `tokens.css` carries the registration block and the argument;
  `theme.browser.test.tsx` fails if a registration is dropped.

  The caching half of the original bullet stands and is still not done — see
  the commit that landed light mode.

  **The general lesson is the one this repository keeps relearning**: three
  minutes of probing the seam beat a paragraph of reasoning about what the code
  downstream of it does with the answer.
- **`color-scheme.browser.test.tsx` is rewritten, not extended.** It currently
  asserts the UA paints a control dark. It becomes three assertions, one per
  `data-theme` state, and the `light dark` default is the case that will catch
  a missed token.

### Do not adopt `next-themes`

It is a Next.js SSR flash-prevention library, and this is a Vite SPA using
`wouter`. All it would do here is one `useState` persisted to `localStorage`
plus an inline `<script>` in `index.html` that sets `data-theme` before first
paint. Twelve lines we own beats a dependency whose reason for existing does
not apply.

---

## 2. Motion

**`motion@13.1.1`**, checked directly against the npm registry. Peer
dependencies are `react: ^18.0.0 || ^19.0.0` and `react-dom: ^18.0.0 ||
^19.0.0`, both optional — no conflict with React 19, and nothing that touches
the `eslint-plugin-jsx-a11y` override. Note that the package now depends on
`framer-motion: ^13.1.1` internally, so both names appear in the lockfile; that
is the rename shim, not two copies of the engine.

**Cost.** The full `motion/react` build is **~31 kB gzipped**. Behind
`LazyMotion` with `m` components — `m.div` rather than `motion.div`, features
loaded asynchronously — the initial cost is **~4.6 kB**, with the feature
bundle fetched after paint. Against a 512 kB budget at ~320 kB even the full
build fits, but `scripts/check-size.mjs` enforces **per-chunk** limits, so
whichever chunk imports it moves. CLAUDE.md's rule applies: raise the limit
deliberately, in its own commit, not folded into the feature.

### The reduced-motion trap, which is the real finding

This repo handles `prefers-reduced-motion` in four places. Three are targeted —
`states.css:125` on `.toast`, `course.css:161` on the extraction dots,
`tree.css:234` on skeleton rows. One is global, at `components.css:851`:

```css
@media (prefers-reduced-motion: reduce) {
  * { animation-duration: 0.001s !important; transition: none !important; }
}
```

That switches animation **off** rather than slowing it, which is this project's
stated policy. It is also **CSS-only**.

**Motion animates through WAAPI and rAF on inline styles. That global rule will
not touch a single `m.div`.** Every existing reduced-motion guarantee silently
stops covering the new surfaces, with no test failure — jsdom returns only what
an inline style said, and the browser project has no assertion for this today.
This is the `silent-defaults-hide-missing-wiring` shape exactly: working and
never-wired look identical.

The bridge is `useReducedMotion()` from `motion/react` feeding a
`MotionConfig`, and the honest version has to match the policy already written
down — **off, not slowed**. `MotionConfig transition={{ duration: 0 }}` is the
equivalent of the `0.001s` above. Motion's own `reducedMotion="user"` default
is **not** equivalent: it disables transform and layout animations only, and
leaves opacity and colour running. Adopting the default silently relaxes an
accessibility promise this repo made on purpose.

**Pick the policy explicitly, and put a browser measurement on it.**

### What else we give up

`layout` and `layoutId` animations are the reason to take Motion for a catalog
page at all, and they work by measuring and applying inline transforms — which
means an element's computed geometry mid-animation is not what any stylesheet
says. Every `.browser.test.tsx` that measures a laid-out element on an animated
surface becomes timing-sensitive, and this repo already holds that a failure
under load is not evidence until it reproduces alone.

**Confine Motion to the two new surfaces. Do not retrofit it onto the
workbench.**

---

## 3. Command palette

**`cmdk@1.1.1` is still the answer, and it composes with Radix because it *is*
Radix.** Registry-checked dependencies: `@radix-ui/react-id`,
`@radix-ui/react-primitive`, `@radix-ui/react-compose-refs`, and
`@radix-ui/react-dialog ^1.1.6`. Peers: `react: ^18 || ^19 || ^19.0.0-rc`.

It ships **no CSS at all**, which is exactly right for a build with no preflight
and no default theme: there is nothing it can bring that could be off-palette.
Roughly 5-6 kB gzipped on top of the Radix packages already present; its Radix
dependency ranges are compatible with the five already installed, so npm
dedupes rather than installing a second tree.

`react-cmdk`, which search results surface first, is a different and older
unrelated project. Do not take it. `cmdk-base` (a Base UI port) and
`modern-cmdk` exist, but neither has the deployment surface to justify being
first.

### The one thing that will break

`cmdk` exports `Command` **and** `Command.Dialog`. `Command.Dialog` wraps the
palette in **Radix Dialog**, which keeps its own layer stack, its own focus
trap, and its own Escape handling on `document` at capture. `OverlayHost` keeps
a different stack and gives Escape to the topmost of *those*.

Two stacks, each convinced it is authoritative, is the `GraphDetail` defect —
one keypress closing a panel and the thing in front of it — arriving as a
transitive dependency. `Tooltip.tsx` already spends three paragraphs bridging
around exactly this for `react-dismissable-layer`.

**So: import `Command` only, and host it inside the existing `Overlay`.** We
get the filtering, the item selection model, the ARIA combobox wiring and the
keyboard routing; `OverlayHost` keeps `inert`, Escape ordering and focus
return, which is the contract `Drawer.tsx` was refactored to depend on.

**Add a check to `scripts/check-deleted.mjs` forbidding `Command.Dialog` and
any direct `@radix-ui/react-dialog` import**, so the wrong half cannot drift
in. Same shape as the existing `title=` ban.

### What we give up

cmdk's filtering is a built-in fuzzy scorer we do not control. If the project
index wants frecency, recency weighting, or scoping by facet, we will pass
`shouldFilter={false}` and supply our own — at which point we are using cmdk
for its selection state machine and keyboard model rather than its search.
That is still worth it. Be clear it is the trade before writing "cmdk gives us
search" into a spec.

---

## 4. What not to adopt

### `Drawer.tsx` should not become Radix Dialog

This is not a default-to-the-repo answer. The docstring is right on the merits,
and the merits are specific.

`Drawer` *used to* hand-roll all of this — its own `.drawer-backdrop`, a
`window` keydown listener for Escape, and a Tab trap over a re-queried
`FOCUSABLE_SELECTOR`. All three were deleted in favour of `OverlayHost`, and
the reasoning is a statement about what a focus trap actually is: the
hand-rolled trap "was a *simulation* of confinement — it cycled Tab within the
`aside` and could only ever cover the keys it saw. It did nothing about the
pointer beyond the backdrop, nothing about a screen reader's virtual cursor,
and nothing about the dock popover painting on top of it at `z-index: 40`. The
host marks the whole page `inert`, which is the platform doing all three at
once."

**Radix Dialog is a focus trap of the first kind, not the second.** It cycles
Tab within its content and applies `aria-hidden` to siblings; it does not mark
the page `inert`. Swapping to it is a **downgrade** on the exact axis this
component was rewritten to fix — the screen reader's virtual cursor, and the
pointer beyond the backdrop — and it would look like a modernisation in the
diff while doing so.

The second, concrete loss: `Confirm.tsx` is built **on** `Drawer`, and the
docstring names `Confirm`-over-`Drawer` as working "without either knowing
about the other", precisely because the host owns the stack and gives Escape to
the topmost layer only. Radix Dialog's own stack puts two dismissal authorities
in one tree — the same conflict `Tooltip.tsx` bridges around — this time on the
component where nesting is a shipped feature.

What `Drawer` keeps for itself is about forty lines: capture focus in a
callback ref during commit, move it in, hand it back on close. Radix would
replace those forty lines and cost the `inert` semantics, the single-stack
Escape ordering, and the nesting guarantee.

**Verdict: keep it. Extend `OverlayHost` if a new layer type is needed. Do not
import a second layering system.**

### Base UI — right direction, wrong time

`@base-ui/react` reached 1.0 in December 2025, is at 1.6 by mid-2026, has a
full-time team at MUI, and became shadcn's default in July 2026. Radix's own
development has slowed after the WorkOS acquisition, though Snyk still rates
its maintenance healthy with the repository updated 2026-08-08. So Base UI is a
real and defensible future direction.

It is the wrong thing to do **inside** a console reimagining. It replaces five
packages with different APIs across `Tooltip`, `Menu`, `Popover`, `Tabs` and
`Choices`, every one of which carries a bespoke `OverlayHost` bridge that would
need re-deriving, and none of it is visible to a user. **File it in
`BACKLOG.md` as its own PR with its own risk, after §5 ships.**

### Any component kit that ships CSS

shadcn/ui, Radix Themes, MUI, Mantine, HeroUI, DaisyUI. Every one assumes
Tailwind preflight, Tailwind's default theme, or both — and `theme.css` omits
both deliberately and argues for it at length.

shadcn in particular pastes components using `bg-background`,
`text-muted-foreground`, `rounded-lg`, `p-6` — utilities that **generate no CSS
in this build** and fail silently. That is the exact failure
`scripts/check-tailwind.mjs` was written to catch, and that script covers only
the spacing families. Taking a kit means importing that failure mode at a rate
the check cannot keep up with.

### `tailwindcss-animate` / `tw-animate-css`

Same reason, plus they conflict with the global reduced-motion `!important`
rule at `components.css:851`.

### `react-hook-form`

Covered above. ~13 kB for five one-field forms.

### Tailwind's default theme, as a shortcut to `md:` and a wider palette

`theme.css` measures it at 1.3 kB gzipped and correctly calls that the smaller
reason. Taking it makes "an off-palette colour is unwritable" false, and that
property is what makes a two-week visual reimagining reviewable at all.
**Declare `--breakpoint-*` in `@theme` in the commit that first needs a
responsive variant**, as `theme.css` already instructs.

### `framer-motion` under its old name

`motion` is the maintained name. Taking `framer-motion` pins us to the shim
rather than the library.

---

## Peer-dependency and gate notes

- None of `motion` or `cmdk` declares an `eslint` peer, so the
  `eslint-plugin-jsx-a11y` override in `package.json` is untouched by anything
  here.
- Both declare React 19 in range. Neither needs `--legacy-peer-deps`.
- Every new dependency moves a **per-chunk** limit in `scripts/check-size.mjs`,
  not the 512 kB total. Raise the limit in its own commit, and say in the
  message what was measured.
- `npm run verify` is the gate that catches the prettier check and the size
  budget; the individual commands do not. The lockfile must be regenerated with
  CI's npm.

## Files worth reading before writing any spec against this

- `frontend/src/styles/theme.css` — the no-preflight and no-default-theme
  argument, and the `source(none)` scanner note.
- `frontend/src/styles/tokens.css:29-34` — the hard-coded `color-scheme: dark`
  and the test pinned to it.
- `frontend/src/styles/components.css:851` — the global reduced-motion rule
  that Motion will not honour.
- `frontend/src/presentation/common/Drawer.tsx:1-36` — the `inert` argument, in
  full.
- `frontend/src/presentation/common/Tooltip.tsx:17-30` — the two-stacks bridge,
  which is the template for hosting `cmdk`.
- `frontend/src/presentation/common/primitives.tsx:36-52` — the hand-written
  statement of the problem `cva` solves.
- `frontend/scripts/check-tailwind.mjs` — why a CSS-shipping component kit is
  dangerous here.

## Sources checked on 2026-08-27

- `https://registry.npmjs.org/motion/latest` — version, peers, dependencies.
- `https://registry.npmjs.org/cmdk/latest` — version, peers, Radix dependencies.
- `https://motion.dev/docs/react-upgrade-guide` — the framer-motion rename.
- `https://motion.dev/docs/react-reduce-bundle-size` — the LazyMotion figure.
- `https://web-platform-dx.github.io/web-features-explorer/features/light-dark/`
  — Baseline dates.
- `https://developer.mozilla.org/en-US/docs/Web/CSS/color_value/light-dark`
- `https://tailwindcss.com/docs/dark-mode` — `@custom-variant`, no `darkMode`
  key in v4.
- `https://github.com/radix-ui/primitives` and
  `https://security.snyk.io/package/npm/radix-ui` — maintenance state.
- `https://ui.shadcn.com/docs/changelog/2026-07-base-ui-default` — Base UI as
  shadcn's default.
