# A component system, and the path onto it

A specification for rebuilding this console's presentation layer on standard,
externally-maintained primitives, and for migrating onto it one shippable
increment at a time.

Read out of a clean worktree at `origin/main` = `a010974` ("Turn the embedding
store on, and delete the floor it makes unnecessary", #90). The four feature
indexes were written at `5a5a7cf` and `unified-ui-proposal.md` at `4a86e89`;
neither intervening commit touches `frontend/`, so their UI claims are current.

## What I verified myself, and what I took on trust

The standard in this repository is that a document says which of its facts it
checked. Mine divide into three kinds.

**Measured, by building and gzipping in this worktree.** Every kilobyte figure
in §3 and §8. I installed each candidate library against this project's real
`react@19`/`vite@8` tree, built a bundle importing the primitives this console
would actually use, put `react`/`react-dom`/`scheduler` in a separate chunk and
excluded it, and gzipped what was left. Method notes and caveats are in §8.1.
The baseline (`app-` 58.8 kB, `vendor-` 36.8 kB, total 239.1 kB) is
`npm run build && npm run size` on an untouched checkout. The harness was
deleted afterwards; `git status` is clean and no dependency was saved to
`package.json`.

**Read in source, by me.** `frontend/src/styles/tokens.css` in full;
`presentation/common/{primitives,content,Confirm,Drawer}.tsx`;
`presentation/session/{Pane,Timeline}.tsx`;
`presentation/research/TopicStatusDialog.tsx`;
`presentation/agents/AgentWidget.tsx`; `eslint.config.js`; `vite.config.ts`;
`scripts/check-size.mjs`; and the output of `find src -type f`, which is where
the test-file counts in §10 come from.

**Taken from the four reports**, and attributed by feature id wherever it
appears. Where a report's claim is load-bearing for a decision here, I re-read
the code; those cases are marked *(checked)*.

**Not verified, and not verifiable from here.** Nothing in this document has
been run. I did not start the server, open a browser, or migrate a single
component and watch it work. Every claim about how a phase will *feel* is
inference. Per `CLAUDE.md`, the suite passing carries no information about any
of it, and the specific historical warning in `docs/design/landing-page.md` §8
— a virtualizer that passed every test and left a 122px hole at three
projects, a read-model that passed every test and 500'd on the only database
anybody had — applies with full force to a migration that touches every
component on the page.

---

## 1. The decision, stated once

- **Behaviour comes from Radix UI primitives.** Unstyled, per-primitive
  packages, WAI-ARIA patterns implemented once by people who do this full
  time. §3.1. Estimated cost was 16.6 kB for the first phase and 46.3 kB for
  the complete set. **Corrected against the real build on 2026-08-12: the five
  primitives actually shipped cost 33.0 kB, and the complete set lands near
  43.8 kB.** The destination survived; the route to it did not. §3.1a.
- **Styling and theming come from Tailwind CSS v4**, with today's token values
  ported verbatim into its `@theme` block so the tokens generate both the CSS
  custom properties and the utilities that consume them. §4. Measured cost:
  **4.8 kB gzipped** for a utility-heavy surface, against **11.5 kB** of
  hand-written CSS today.
- **Variants come from `class-variance-authority`** — 0.7 kB — so a component's
  tones are a typed data structure rather than a `clsx` expression per call
  site. §5.
- **Storybook 10 is the workbench and, through `composeStories`, the test
  fixture.** Stories run inside the existing `vitest` project with no new CI
  infrastructure; the browser-mode runner is a later, optional phase. §6.
- **`eslint-plugin-jsx-a11y` lands in phase 0.** It costs nothing at runtime,
  it is not currently installed *(checked — `eslint.config.js` has
  `js.recommended`, `tseslint.recommendedTypeChecked` and `react-hooks`, and no
  a11y plugin)*, and it would have caught several of the defects in §2 as lint
  errors.
- **Radix gets its own bundle bucket, `ui-`.** `vendor-` stays at 48 kB and
  keeps biting. §8.2.
- **The rollout is seven phases and every one of them ships.** Phase 0 changes
  no pixel. Phase 1 deletes three hand-rolled focus traps. Nothing waits for
  the end. §11.

What is *not* being given up: the palette, the type scale, the spacing rhythm,
the event-kind colours and the one elevation. Those are values, and they carry
across unchanged. §4.1 says why I kept them rather than taking a library's
defaults.

---

## 2. Why not bespoke: the evidence is in this repository

The instruction is to stop hand-building. That instruction does not need my
support, so this section is not an argument for it — it is the record of what
the hand-built approach actually produced here, because the failures are
specific and they are what the phases in §11 are ordered against.

**The duplication the code predicted, then committed.** `common/Drawer.tsx`
carries this comment:

> A second copy of that is how one of two dialogs quietly stops trapping focus
> a year later.

`research/TopicStatusDialog.tsx` is that second copy. It duplicates
`FOCUSABLE_SELECTOR` verbatim, duplicates both effects, duplicates the
Tab-wrapping branch, and reuses `Drawer`'s own CSS classes
(`.drawer-backdrop`, `.drawer`) without using `Drawer` *(checked — both files
read in full)*. The comment names the failure mode and the failure is sixty
lines away. That is what hand-building an interaction contract costs even when
the cost is understood well enough to be written down in advance.

There is a third overlay contract in `AgentWidget.tsx` (Escape plus outside
`pointerdown`, deliberately no trap, with a hand-written suppression rule while
a drawer is in front) *(checked)*. Three overlays, three implementations, one
stated stacking rule. Radix ships one dismissable-layer stack that all of them
would share.

**Accessible names that are punctuation.** `Pane.tsx`'s toggle renders
`{collapsed ? '▸' : '◂'}` as its only child *(checked)*. `aria-expanded` and
`title` are set; the accessible name is a glyph. `AgentWidget.tsx:130-133`
names this as a known bug it declines to spread *(checked — the comment reads
"A real sentence, not the glyph. `Pane.tsx` announces its toggles as
'◂'/'▸'…")*. So: a bug identified in writing, still present, with a second
component routing around it rather than through it. Whatever the reason —
`Pane` is shared, and changing shared code is a wider change than fixing your
own — the observable result is that the correct behaviour exists in one
component and the incorrect behaviour in another, and a shared primitive is
what collapses that into one answer.

**A mode that changes what Enter does, with nothing on screen.** `Timeline.tsx`
holds a `column` state; `→` sets it to 1; `Enter` at column 1 forks the session
— creating a new session, irreversibly — and at column 0 scrubs *(checked,
lines 50-70)*. Nothing renders `column`. `aria-colcount={2}` is declared and no
cell carries `aria-colindex` *(checked)*. `.ev-fork:focus-visible` exists in
`timeline.css:150` and the fork button is permanently `tabIndex={-1}`
*(checked, `Timeline.tsx:225`)* — a focus style for a state the element cannot
enter. (S-D7 reports all of this; I confirmed each part.)

**Nine explanations that exist only in a `title` attribute** (S-D3), plus
roughly a dozen more across the landing and course reports (L-F11, L-F12,
L-F14, L-F17, L-F19, C-F21, C-F22, C-F50, C-F58, C-F62, C-F65). `title` is not
keyboard-reachable, not available on touch, and inconsistently announced.
There is no tooltip component in the codebase at all.

**Three disclosure implementations.** `common/primitives.tsx`'s `Disclosure`
(a real button with `aria-controls`, state owned externally — the good one), a
raw `<details>` for `Discarded` (S-D14, state owned by the DOM and lost on
unmount), and a bare `<div onClick>` for revision headers with no `role`, no
`tabIndex` and no key handler (S-D12, S-F39). One of the three is not operable
by keyboard at all.

**Toasts with no keyboard route.** L-F37: a `<div>` with an `onClick`, no close
affordance, dismissed by clicking it.

**Four free-text filters with four match rules and four implementations**
(L-F3, R-F3.2, R-F5.2, R-F6.4); **two virtualizer configurations** with
independently load-bearing settings (L-F8, R-F5.1); **two pane mechanisms**
with incompatible fold semantics (R-F1.1 unmounts, S-F17 keeps a 34px rail and
enforces a last-open rule); **two worker rosters** (C-D6); **two things labelled
"Documents"** (R-§8.5); **two "file not here" messages** (S-D13); **two
confirmation mechanisms**, one of them `window.confirm` (S-D1) beside a
`Confirm.tsx` that exists and is unused on that path (S-§12.8).

The through-line is not that these were built carelessly. Several carry
better-reasoned comments than the libraries that would replace them. It is that
**an interaction contract implemented per-site drifts per-site**, and this
codebase has now demonstrated that at every scale: within a file, between two
files, and between two pages.

`tokens.css` is the counter-example, and it is the reason §4 keeps its values.
It is a *single source with a stated rule* — "a second literal hex would be a
second palette" — and the file records two occasions where a value was written
twice and it caught the drift. Where this codebase built a single source of
truth it worked. Where it built the same behaviour repeatedly it drifted. The
recommendation below is the first pattern applied to the second problem.

---

## 3. The choice, with the alternatives priced

### 3.1 The behaviour layer

All figures gzipped, measured in this worktree, `react` excluded. See §8.1 for
method.

| Option | ~10 primitives | Verdict |
|---|---|---|
| **Radix UI** (per-primitive packages) | **39.2 kB** | **Chosen** |
| Ark UI (`@ark-ui/react`, zag.js state machines) | 62.8 kB | Rejected — 60% more for the same coverage |
| React Aria Components (Adobe) | 68.4 kB | Rejected — best-in-class behaviour, worst price here |
| Base UI (`@base-ui/react` 1.7.0) | 67.6 kB | Rejected — 73% more than Radix, no compensating win |
| Mantine (styled, 13 components) | 72.3 kB JS **+ 33.2 kB CSS** | Rejected decisively — §3.2 |

Three things decided it.

**Price.** Radix is the cheapest by a wide margin at equal coverage. React Aria
is the most rigorous implementation of the three headless options — its
internationalisation, its pointer/keyboard interaction modelling and its
collection API are genuinely better engineering than Radix's — and at 68.4 kB
it costs 74% more than Radix for a single-operator, English-only, localhost
console. If this application were shipped to a diverse public I would argue
the other way and I want that recorded, because it is the one place my
recommendation is contingent on facts about the product rather than about the
libraries. `landing-page.md` §8 answer 4 and `unified-ui-proposal.md` §10 both
settle that this is a single-user, `127.0.0.1`, no-authentication console.

**Incrementality, which matters more here than price.** Radix's per-primitive
packaging is what makes a strangler migration payable in instalments. The
measured curve:

**The table below is a pre-build estimate and three of its rows are wrong.**
It is kept rather than rewritten, because what it got wrong is the useful part;
§3.1a has the measurements and what they change.

| Import set | Cumulative | Marginal |
|---|---|---|
| `visually-hidden` alone (the shared floor: slot, primitive, compose-refs, context) | 5.8 kB | — |
| `+ dialog` | 16.6 kB | +10.8 |
| `+ collapsible` | 17.1 kB | +0.5 |
| `+ toggle-group + radio-group` | 22.9 kB | +5.8 |
| `+ dropdown-menu` | 35.2 kB | +12.3 |
| `+ popover + tabs + tooltip` | 38.6 kB | +3.4 |
| `+ select + toast` (twelve total) | 46.3 kB | +7.7 |

The shape is the argument: there is a ~5.8 kB floor, a ~20 kB floating-layer
cost paid once by whichever of menu/popover/tooltip/select arrives first
(`popover` alone measures 25.7 kB, which is that cost plus the floor), and then
each additional primitive is cheap. Phase 1 pays 16.6 kB and delivers a
working dialog contract; phase 3 pays the floating-layer cost and gets four
primitives for it. A monolithic package cannot be bought this way — the
single-package options above cost their full price on the first import that
touches their shared core.

### 3.1a What the build actually charged

Written 2026-08-12, after five primitives had shipped. The numbers above came
from a standalone harness; these come from `npm run size` on the console this
repository builds, plus a second harness run for the primitives not yet
adopted. Where the two disagree, this section wins.

**The order changed, so the estimate cannot be compared row for row.** The
migration did not proceed phase 1 → 2 → 3. `Dialog` and `Disclosure` are still
first-party — the hand-rolled versions were fixed rather than replaced — and
the floating layer arrived first. What is in `package.json` today is
`dropdown-menu`, `popover`, `radio-group`, `tabs` and `tooltip`.

Measured live during that adoption, in the real `ui-` chunk:

| `ui-` after | Cumulative | Marginal |
|---|---|---|
| empty (the chunk exists, nothing in it) | 0.5 kB | — |
| `+ tooltip` | 18.0 kB | +17.5 |
| `+ popover` | 24.6 kB | +6.6 |
| `+ dropdown-menu` | 30.8 kB | +6.2 |
| `+ tabs + radio-group` (today) | 33.0 kB | +2.2 |

**Where the estimate went wrong.** It priced the floating-layer engine as a
single ~20 kB toll paid once, after which "each additional primitive is cheap".
The first half is right — `tooltip` alone is 17.5 kB and almost all of that is
floating-ui. The second half is not: `popover` and `dropdown-menu` cost 6.6 and
6.2 kB *on top of* a tree that already had floating-ui, dismissable-layer,
presence, portal and slot in it. A floating primitive is its own state machine,
and sharing a positioning engine with a sibling does not make it free.

**Where the end state went, once that is corrected.** Extrapolating those ~6 kB
marginals across twelve primitives gives about 88 kB, which is what this
correction was opened to report. Extrapolation was wrong too. Measured, in the
same harness as §8.1 and against the shipped five as the baseline:

| Added to today's five | Marginal |
|---|---|
| `dialog` | +0.8 kB |
| `collapsible` | +0.5 kB |
| `toggle-group` | +0.7 kB |
| `select` | +5.6 kB |
| `toast` | +3.2 kB |
| `visually-hidden` | +0.0 kB |

So the complete Tier-0 set lands at **33.0 + 10.8 ≈ 43.8 kB**, against a `ui-`
budget of 56. The ~6 kB marginal is not a property of "another Radix
primitive"; it is a property of *another floating primitive*. `dialog`,
`collapsible` and `toggle-group` reuse machinery already paid for and cost
rounding error. `select` is the one remaining expensive item, and it is
expensive for the same reason `popover` was.

**What this changes: nothing that has to be done.** No budget raise, no
primitive dropped on cost grounds. `Tabs` was skipped in the floating-layer
increment because `FileView`'s first-party `TabGroup` works and is tested, and
that decision was made on "fixes no defect" rather than on kilobytes — it
should stay made on those grounds. The `ui-` budget stays at 56, which now has
about 12 kB of genuine head-room rather than the 10 kB the old numbers implied
by luck.

**Method, and its one honest gap.** The marginal table above is from a
standalone build (`react`/`react-dom`/`scheduler` chunked separately and
excluded, gzip at default level, every import mounted so nothing is shaken —
§8.1's method, including the failure mode it records). That harness reports
36.0 kB for the shipped five where the real build reports 33.0, a constant
~3 kB of harness overhead. The marginals are what is being claimed and they are
robust to that offset; the 43.8 kB total applies them to the real baseline
rather than to the harness's. It is a projection, and the first projection in
this document was wrong, which is the reason to say so plainly here.

**It is the default.** Radix is what shadcn/ui is built on, which is to say it
is the reference answer to "React app, headless primitives, own your styling"
and the thing a new contributor is most likely to already know. "Conformance
to standards and not being bespoke" is satisfied more completely by the option
with the largest body of existing documentation, examples and Stack Overflow
answers than by the technically superior one.

Compatibility with this tree was confirmed by installation: `npm install`
resolved `@radix-ui/*@1.x`, `react-aria-components`, `@ark-ui/react` and
`@base-ui/react` against `react@19` with no peer-dependency error, which npm 7+
treats as a hard failure. That is real evidence and it is weak evidence — it
proves the manifests agree, not that the runtime does.

**On shadcn/ui specifically.** I am not proposing `npx shadcn add`. Its
components are styled for a light-first, rounded, generously-spaced product
aesthetic that is the opposite of this console's dark, dense, monospace-forward
one, so every one of them would need rewriting, and a rewritten shadcn
component is a first-party component with a confusing provenance. What this
spec takes from shadcn is its *architecture* — Radix for behaviour, Tailwind
for style, CVA for variants, the component owned in-repo — which is the part
that is actually the standard.

### 3.2 Why not a styled library

Mantine is the strongest styled option for a dark developer tool and it fails
on measurement, not on taste. **77.5 kB of JS plus 33.2 kB of CSS.** The CSS is
the disqualifier: `check-size.mjs` charges every `.css` file to the `app-`
bucket *(checked — "CSS rides with the entry chunk as far as a reader is
concerned")*, which stands at 58.8 kB against an 80 kB limit. Mantine's
stylesheet alone would take `app-` to 92 kB before a single line of this
project's own CSS or a single one of its components moved. MUI and Chakra are
larger still.

The second objection is the one the owner's instruction does not dissolve.
A styled library brings a *complete* visual language, and adopting it means
either accepting its language — discarding the palette, the type scale, the
event-kind colours and the density that make this console legible — or
overriding it, which is bespoke work performed through a theming API instead of
a stylesheet, and is strictly harder than bespoke work performed in a
stylesheet. Neither branch is what "stop being bespoke" is asking for. Headless
primitives dissolve the dilemma: they ship no appearance at all, so there is
nothing to fight.

### 3.3 Styling and theming

| Option | Verdict |
|---|---|
| **Tailwind CSS v4** | **Chosen.** Measured 4.8 kB gzipped for a utility-heavy surface. `@theme` makes the token file the source of both variables and utilities. §4. |
| Keep 19 hand-written stylesheets | Rejected — it is the mechanism the instruction rejects, and it is where the drift documented in `tokens.css`'s own comments came from. |
| CSS Modules | Rejected — scoping is not the problem. The problem is that a "chip" is spelled four different ways; modules make each spelling local and un-greppable, which is worse. |
| Panda CSS / vanilla-extract | Rejected — tokens-first and genuinely good, but each is a smaller ecosystem with a build-time integration this project would be among the few to run. Standard-conformance was the brief. |

Measurement: a single component file exercising five button tones, chips, a
pane header with a sticky head, a hover/focus-within row, an empty state, an
error box, a modal with backdrop blur, a divided list, a code block, a
textarea, a three-breakpoint responsive grid and explicit focus rings compiled
to **21.8 kB raw / 4.8 kB gzipped**, with this project's tokens in `@theme`.
Today's nineteen stylesheets are 61.5 kB raw / 11.5 kB gzipped.

I will not claim Tailwind ends at 4.8 kB for the whole console. Utility output
grows sub-linearly because utilities are shared between components, so a
reasonable estimate for full coverage is 8–12 kB — at or slightly below where
the hand-written CSS already is. That is an estimate and it is labelled as one.
The number that matters for the migration is the *coexistence peak*, and it is
small: during any phase both stylesheets are loaded, so `app-` peaks near
58.8 + 5 ≈ 64 kB against its 80 kB limit. **The strangler fits inside the
existing `app-` budget with room to spare.** That is not a lucky accident, it
is a consequence of the owner's earlier raise from 57 to 80 — and it is the
single fact that makes a phase-by-phase CSS migration viable at all.

### 3.4 Variants

`class-variance-authority`, 0.7 kB. A `Button` today reads
`clsx('btn', small && 'btn-sm', tone !== 'default' && \`btn-${tone}\`, className)`
*(checked)* — a template string building a class name, which no tool can check
and which fails silently for a tone that has no stylesheet rule. CVA makes the
tone map a typed object, so an unknown tone is a type error and the set of
tones is enumerable by a story. `tailwind-variants` is the alternative; it is
larger and its extra features (slots, responsive variants) are not needed.

---

## 4. Theming, concretely

**The tokens survive as values. The mechanism moves.**

`tokens.css` becomes a Tailwind `@theme` block. Every entry generates both a
CSS custom property and the utilities that consume it, from one declaration:

```css
@theme {
  --color-bg: #0b0d10;
  --color-fg-dim: #8a95a3;
  --color-accent: #e2a457;
  --color-k-file: #5ec98a;
  --spacing-3: 10px;
  --text-md: 13px;
  --shadow-1: 0 6px 20px rgb(0 0 0 / 50%);
}
```

`--color-bg` yields `bg-bg`, `text-bg`, `border-bg` and the `--color-bg`
variable itself. This is what "unified theming" means operationally here, and
it is a stronger version of the rule `tokens.css` already states: today a
second literal hex is discoverable only by reading two files, and a *token used
without a utility* is not discoverable at all. Under `@theme` a colour that is
not in the theme block cannot be written as a utility class at all — the
utility does not exist — so the rule is enforced by the compiler rather than by
a comment asking for it.

Three specifics:

**Radix contributes nothing to the theme, which is the point.** It ships no
CSS. There is no library theme to reconcile with this one. It exposes state as
data attributes (`[data-state="open"]`, `[data-disabled]`, `[data-highlighted]`)
which Tailwind targets directly (`data-[state=open]:bg-bg-raise`). The
appearance stays entirely ours; only the keyboard, focus and ARIA behaviour is
imported.

**The event-kind colours stay exactly as they are**, including the design idea
behind them — one accent, with event kinds carrying the only other colour, so
the log reads as a legend for itself. `getComputedStyle` reads them at runtime
for the graph canvas (`entity-colors.ts`, R-F6.2), and `@theme` still emits
them as custom properties, so that code is untouched.

**`--topbar-h`, and the panes' `34px` rail, are layout constants rather than
theme tokens.** They stay as CSS variables outside `@theme`. `panes.css`'s
ad-hoc `7px`/`12px` (S-§13.3) become `--spacing-*` during phase 5. Those values
sit outside the `--space-*` scale because that part of the console was written
before the scale existed; it is accumulated inconsistency rather than a
decision anyone made, and phase 5 is the first work whose scope includes it.

**What I did not do: invent new tokens.** `landing-page.md` §6 lists tokens as
genuinely missing and every one it named has since landed *(checked —
`--line-strong`, the four `--tint-*`, `--shadow-1`, and `--space-1`…`6` are all
present in `tokens.css` with comments recording why)*. The palette is in good
shape. Porting it is a mechanical change, and mechanical is what makes it safe
to do in phase 0.

---

## 5. What actually prevents repetition

Naming the mechanism rather than the aspiration, in the order they bite:

1. **Radix owns each interaction contract once.** There cannot be a second
   focus trap, because nobody writes a focus trap. This is the mechanism that
   closes §2's first and largest failure.
2. **CVA makes a component's variants a closed, typed set.** A fifth button
   tone is a key in one object, not a class name invented at a call site and a
   rule added to a stylesheet.
3. **`@theme` makes an off-palette value unwritable.** There is no utility for
   a colour that is not a token.
4. **Storybook makes the existing set visible.** The duplicates in §2 — four
   filters, three folds, three empty-state wordings for one situation
   (S-§13.3) — are spread across directories with no index, so finding out
   whether a thing already exists currently means grepping for a name you would
   have to guess. A gallery makes the existing set answerable at a glance,
   which is the only one of these five that addresses discoverability rather
   than enforcement.
5. **`eslint-plugin-jsx-a11y` fails the build on the recurring class.**
   `no-noninteractive-element-interactions` catches S-D12's `<div onClick>`;
   `control-has-associated-label` catches glyph-only buttons;
   `click-events-have-key-events` catches L-F37's toast. These are lint errors
   in most React codebases and are not currently checked here.

Note what is *not* on this list: a rule, a convention document, or a review
checklist. Each of the five is something that fails a build or is visible on a
screen.

---

## 6. Storybook's role

**Storybook 10.5.7** with `@storybook/react-vite`, which supports `vite@8` and
`react@19` *(checked via `npm view … peerDependencies`)*.

**Which components get stories.** Everything in the Tier-0 and Tier-1
inventories in §9 — the reusable layer. Not `SessionView`, not `CourseView`,
not `ProjectList`: a story for a component that fetches its own data is a story
about the mock, and the four reports are unanimous that the interesting
behaviour in those files is data-flow, which `vitest` already tests better.
The rule: **a component gets a story if it can be rendered from props alone.**
That rule is also the design constraint the brief asks for — "standalone
components that make sense in isolation" — so a component that cannot get a
story is telling you it is not a component yet.

**What a story asserts.** Three things, in increasing strength:

- *That the states exist and are enumerated.* One story per variant, which is
  what makes §5's item 4 work. `EmptyState` gets its distinct wordings side by
  side; `Chip` gets all seven tones; `OutcomeBox` gets all six run endings
  (C-F26) so the rule that only `queue_empty` earns the `done` tone is visible
  rather than asserted in prose.
- *That the interaction works*, via a `play` function driving
  `@testing-library/user-event` — the same library already in `devDependencies`
  *(checked)*. A `Dialog` story that opens it, tabs to the end and asserts
  focus wrapped is the test that `TopicStatusDialog` and `Drawer` should have
  shared and did not.
- *That it is accessible*, via `@storybook/addon-a11y`, which runs axe against
  each story.

**How it runs in CI, and this is the part that has to be right or none of it
counts.** There are two mechanisms and I am recommending the cheaper one first.

*Phase 0 (recommended): portable stories.* `composeStories` from
`@storybook/react` turns a story file into plain React elements with args and
`play` applied. Existing `vitest` test files import them and render them in
jsdom. **No new CI job, no new runner, no browser binary** — stories become
fixtures inside the `app` vitest project that already exists, and
`npm run verify` picks them up through `test:coverage` with no change to the
chain. This is what makes stories *complement* rather than replace the vitest
tests: the story is the fixture, the assertion stays in the test file, and
there is exactly one place a component's states are written down.

*Phase 6 (optional): `@storybook/addon-vitest`.* It runs every story as a test
automatically, but its peer dependencies are `@vitest/browser` and
`@vitest/browser-playwright` *(checked)*, meaning vitest browser mode and a
downloaded Chromium in CI. That is a real cost and it buys one real thing:
axe's colour-contrast rules are meaningless in jsdom, because jsdom computes no
layout and no colours. A console this dark, with `--fg-faint: #5c6673` on
`--bg: #0b0d10`, has contrast questions worth answering — but they are worth
answering after the components exist, not before.

**Does Storybook replace `vitest`?** No, and it must not be allowed to drift
into looking like it does. The domain layer's 90% coverage floor, the store
tests, the mapper tests and the routing tests are the majority of this suite's
value and Storybook has nothing to say about any of them.

**One integration detail that will otherwise silently corrupt the gates.**
`vite.config.ts`'s coverage `include` is `src/**/*.{ts,tsx}` with only tests,
`main.tsx` and `src/app/**` excluded *(checked)*. Story files land in `src/`
and would be counted as production code — dozens of small, fully-executed
modules would inflate every ratchet, and the thresholds are explicitly
"ratchets, not targets… each number sits just under what the suite actually
reaches today". `src/**/*.stories.tsx` must be added to the coverage `exclude`
in the same commit that adds the first story, or the gate stops measuring what
it was written to measure.

---

## 7. What this does to the four gates

| Gate | Change |
|---|---|
| `uv run ruff check .` | None. No Python changes anywhere in this spec. |
| `uv run ruff format --check .` | None. |
| `uv run pytest` | None. |
| `npm run verify` | Four changes, all inside the existing chain — see below. |

The chain is `format:check && lint && typecheck && test:coverage && build &&
size`. Every addition lands inside it; **no new CI job is created**, which is
deliberate, because a check that lives outside the chain is a check that CI
does not run.

- `format:check` — Prettier must be told about Tailwind class ordering, via
  `prettier-plugin-tailwindcss`. Without it, class order is a matter of
  opinion and every diff carries reordering noise. With it, class order is
  mechanical and `format:check` enforces it. This is the single highest-value
  piece of anti-bikeshedding in the proposal.
- `lint` — `eslint-plugin-jsx-a11y` joins the flat config, scoped to
  `src/**/*.tsx`. It must be introduced with the `presentation/` failures it
  finds either fixed or explicitly listed, because `--max-warnings 0` means
  there is no "warn for now" setting.
- `typecheck` — Storybook config files (`.storybook/*.ts`) sit outside
  `tsconfig.json` for the same reason `vite.config.ts` does: that config is the
  browser's, and application code must not see `process`. They join the
  `allowDefaultProject` list already in `eslint.config.js`.
- `test:coverage` — stories are excluded from coverage (§6) and composed
  stories are imported by tests.
- `build` / `size` — a new `ui-` chunk and its budget entry. §8.2.

A `storybook build` is *not* added to the chain. It would roughly double
frontend CI time to catch a class of error — a story that fails to compile —
that `typecheck` already catches, since stories are TypeScript inside `src/`.

---

## 8. The bundle, priced

### 8.1 Method, and what it does not tell you

Each candidate was built with `vite@8` at `target: 'es2022'`, minified,
`react`/`react-dom`/`scheduler` forced into a separate chunk which was then
excluded from the total, and the remainder gzipped with node's `zlib` at
default level — the same unit `check-size.mjs` uses. The measured entry mounts
the primitives with `createRoot(...).render(...)` so Rollup cannot tree-shake
them; the first run of this harness reported 0.1 kB for every candidate
precisely because an unreferenced export was shaken away, which is worth
recording as the way this measurement goes wrong.

Three caveats. These are the cost of the *library*, not of the finished
components — this project's own wrapper code, which lands in `app-`, is extra
and unmeasured. Marginal costs in the §3.1 table are order-dependent, because
whichever floating primitive arrives first pays for the positioning engine.
And a bundle measurement says nothing about runtime cost; I did not profile
anything.

### 8.2 Budgets

Baseline today, from `npm run size` on an untouched checkout:

```
app-      58.8 / 80     react-  55.3 / 66    text-  25.0 / 34
vendor-   36.8 / 48     graph-  61.4 / 74    total 239.1 / 512
```

`vendor-` has 11.2 kB of slack, and phase 1 alone needs 16.6 kB. So a budget
change is required, and there are two ways to make it.

**Rejected: raise `vendor-` to 88.** It works and it destroys the bucket. The
file's own comment says `vendor-` is "the bucket a *new library* lands in, so
it is the one where the gate still has real work to do". Folding Radix in
would leave query, zustand, wouter, zod, date-fns, clsx and the virtualizer
sharing a limit with 46 kB of head-room-shaped slack, which is the same as no
limit.

**Proposed: a `ui-` chunk, exactly as `graph-` was carved out.**
`vite.config.ts`'s `manualChunks` already special-cases a dependency group by
name, with a comment explaining that naming them "keeps a future unrelated
dependency from silently landing here" *(checked)*. Add:

```js
if (id.includes('node_modules/@radix-ui/')) return 'ui'
if (id.includes('node_modules/class-variance-authority/')) return 'ui'
```

`vendor-` stays at 48 kB and keeps biting at 36.8. `ui-` gets a budget that
moves once per phase, with the note the file's convention requires — what was
measured and what it bought:

| After phase | `ui-` estimated | `ui-` budget | `app-` expected |
|---|---|---|---|
| 1 (dialog) | 16.6 | 20 | ~64 peak (both stylesheets) |
| 2 (+ collapsible, toggle-group, radio-group) | 22.9 | 26 | ~64 |
| 3 (+ menu, popover, tabs, tooltip) | 38.6 | 42 | ~62 |
| 4–7 (+ select, toast) | 46.3 | 52 | ~55, falling as CSS is deleted |

**This table was not followed and its middle rows never happened** — see §3.1a.
The phases ran out of order, `dialog` and `collapsible` were never adopted, and
`ui-` was given a single 56 kB budget rather than one that steps per phase. As
built: `ui-` is 33.0 of 56 with five primitives in it, `app-` is 67.6 of 80,
and the whole console is 280.7 of 512. The projected end state is ~43.8 kB of
`ui-`, so the budget does not move again.

The per-phase budget was the part worth abandoning and it is worth saying why
rather than leaving it as drift. A limit that is raised on the same commit that
consumes it tests nothing; `check-size.mjs`'s own comment makes that argument.
Stepping `ui-` four times would have meant four such commits. One budget set
above the projected end state, with a document saying what the end state is,
puts the argument where an argument belongs.

Total lands near 290 kB against 512 — comfortable, and worth noting that the
`total` gate was described in its own comment as one "that anything realistic
will trip" no longer, so `ui-` is the number actually doing the work.

**The honest framing of the raise.** The owner has said exploration outranks
bundle size at this stage, so head-room is available. I am not claiming Radix
is free. **~44 kB is 16% of what this console currently downloads, spent
entirely on behaviour a user never sees added** — no new feature, no new pixel,
just interaction contracts that stop being wrong. That is the trade and it
should be made with eyes open rather than absorbed into a raise. The mitigating
facts are that it is paid in instalments (§3.1), that it is separately gated so
its growth stays visible, and that the CSS side is roughly neutral (§3.3).

---

## 9. The component inventory

Derived from what the four reports found, not invented. Feature ids are
prefixed **L-** landing, **R-** research, **C-** course, **S-** session, as
`unified-ui-proposal.md` §4 established.

### Tier 0 — behaviour from Radix, appearance from us

| Component | Radix primitive | Replaces / serves | Phase |
|---|---|---|---|
| `Dialog` | `react-dialog` | `Drawer`, `Confirm`, `TopicStatusDialog`'s hand trap, `WorkerDrawer` — L-F16, L-F19, L-F42, R-F4.1–4.4, R-F5.3, C-F39–F45, S-D1 | 1 |
| `VisuallyHidden` | `react-visually-hidden` | accessible names for glyph controls — S-D2, R-F1.1 | 1 |
| `Disclosure` | `react-collapsible` | the three fold implementations — L-F5, L-F21, R-F1.1, C-F10, C-F30, C-F51, S-F26, S-F39, S-F42, S-F45, S-F46, S-F48, S-D12, S-D14 | 2 |
| `ToggleGroup` | `react-toggle-group` | R-F4.1 statuses, R-F4.4 document tabs, C-F8 watch toggle | 2 |
| `RadioGroup` | `react-radio-group` | R-F3.3 focus slices, C-F31 per-tool autonomy levels | 2 |
| `Tooltip` | `react-tooltip` | the ~20 `title`-only affordances — S-D3's nine, L-F11/12/14/17/19, C-F21/22/50/58/62/65 | 3 |
| `Menu` | `react-dropdown-menu` | L-F19's `⋯`, which gains two more verbs under the proposal's §8.3 | 3 |
| `Popover` | `react-popover` | L-F40 / S-F60 agent dock, R-F6.4 search results, R-F6.6 `GraphDetail` | 3 |
| `Tabs` | `react-tabs` | S-F32 rendered/source, S-F35 contents/history, S-F33 + C-F65 audience | 3 |
| `Select` | `react-select` | L-F46 workflow, R-F6.4 entity type | 4 |
| ~~`Toast`~~ | ~~`react-toast`~~ | **declined — see Phase 4 below** | 4 |

### Tier 1 — first-party, no Radix equivalent, standardised anyway

These exist because the reports found the *content* rules load-bearing, not
because the interaction is hard. Each gets CVA variants and stories.

| Component | Why it is a component | Sources |
|---|---|---|
| `Button` | five tones, one place | existing |
| `Chip` | seven tones; `title` becomes a `Tooltip` | L-F11–F14, L-F24–F26, C-F5/F6/F20/F21/F46/F50/F58/F61, S-F12/F25/F37/F42 |
| `EmptyState` | the *detail* line is the load-bearing part, and "empty states that do not say what to do next" is a named defect in two reports | R-F3.9, R-F4.4, R-F5.5, R-F6.6, R-F6.9, C-F55/F56/F59/F61, S-F21/F29/F31/F35/F49, L-F22 |
| `ErrorBox` | never claims emptiness on a failed read — the distinction R-F6.9 draws | existing, R-F6.9, C-D7 |
| `StatusNote` | region-level failure that is *not* a toast; `role="alert"` inline beside the control | C-F37, S-D17, S-D18 |
| `Banner` | drifted-but-following vs stopped, with a button only when a button can work | L-F33, L-F34 |
| `Counter` | written-of-declared, never a percentage; each with its explanatory tooltip | C-F22, C-F50 |
| `OutcomeBox` | six endings, six tones, only `queue_empty` earns `done` | C-F26, C-F27 |
| `Stale` | last-good data plus a marker — "the one rule the component must not break" | C-F5, S-F31 |
| `UnavailableLink` | muted text with a reason, deliberately not a disabled button | C-F62 |
| `Field` | label + description + inline `role="alert"` error, resolving the C-F18/C-F37 split between toast and inline validation | C-F18, C-F37, R-F2.1, R-F4.1, R-F4.3, L-F45 |
| `SearchField` | one implementation, match rule as a prop | L-F3, R-F3.2, R-F5.2, R-F6.4 |
| `VirtualList` | one wrapper preserving `getItemKey`, re-measured `scrollMargin`, per-row measurement | L-F8, R-F5.1, and S-§14.3 which needs it and lacks it |
| `DataGrid` | `role="grid"` with roving tabindex — and a **visible** column cursor, which is the fix for S-D7 | S-F21, S-F22, S-D7 |
| `ListBox` | `aria-activedescendant`, and a real focus ring | S-F29, S-D4 |
| `Panes` | `use-panes.ts` kept as code; only restyled | S-F17–F20 |
| `Breadcrumbs` | existing | L-F36, S-F59 |
| `KeyboardHelp` | the `?` overlay; the model is undocumented and inconsistent across four components | S-D6, S-D5 |
| `Markdown`/`CodeBlock`/`DiffView` | **kept verbatim**, §12 | S-F32, S-F38 |

**Two deliberate omissions.** There is no `Splitter` from a library, because
Radix has none and `use-panes.ts` already solves the harder problem — the
1181px handoff where the hook returns `undefined` and hands `grid-template-columns`
back to the media queries, because an inline style would outrank them (S-F18,
the one thing the session report labels "genuinely subtle and worth
preserving"). It moves as code, not as a description. And there is no
`GraphCanvas` replacement: `react-force-graph-2d` stays, lazily, in `graph-`.

**One contradiction the inventory has to resolve.** The course report treats
native `<details>` as a virtue (C-F30: keyboard behaviour, screen-reader
expanded state, find-in-page opening it to reach a match) and the session
report treats it as a defect (S-D14: DOM-owned state lost on unmount). Both are
right. Radix `Collapsible` gives externally-owned state and correct ARIA, and
loses find-in-page — a browser feature that opens a closed `<details>` to reveal
a match, which no JavaScript disclosure can replicate. I take the Radix arm,
because state surviving a refetch is load-bearing for S-F48 (a tool run stays
open while its conversation refetches on every turn end) and find-in-page is
not mentioned as used by anyone. **This is a real, small, permanent loss and it
should be recorded rather than discovered.**

---

## 10. Test debt: where it is a prerequisite, not a follow-up

`find src -type f` gives the counts directly *(checked)*:

| Directory | Components | Test files |
|---|---|---|
| `presentation/common/` | 4 | **0** |
| `presentation/session/` | 15 | **1** (`use-panes.test.tsx`) |
| `presentation/tree/` | 8 | 1 |
| `presentation/lesson/` | 6 | **0** |
| `presentation/course/` | 11 | 5 |
| `presentation/research/` | 15 | 10 |

The session report's verdict — "Any redesign here is a redesign without a net"
— is correct and understates the problem in one respect: **`presentation/common/`
has no tests at all**, and it holds `Drawer`, `Confirm`, `primitives.tsx` and
`content.tsx`. The four files every phase of this migration touches first are
the four with the least coverage in the codebase. `unified-ui-proposal.md` §6.4
lists session tests as a prerequisite and does not mention `common/`; that is a
gap in it, and it matters more, because `common/` is upstream of everything.

**The rule.** A component must have a test asserting its current behaviour
*before* its implementation is swapped, and that test must be proved red
against a deliberately broken version first — this repository's stated
convention, and the only thing that distinguishes a test from reassurance.

**Prerequisite, per phase.** These block their phase; they are not follow-ups.

- *Before phase 1:* `Drawer` (focus in on open, focus restored on close with
  the DOM-membership re-check, Escape, Tab and Shift+Tab wrapping),
  `Confirm` (one paragraph per line, confirm and cancel wiring). Both are new
  files. `WorkerDrawer.test.tsx:232-330` and `TopicStatusDialog.test.tsx`
  already assert the contract for their own copies and become the regression
  net for the swap.
- *Before phase 2:* `Disclosure` (open state owned externally and surviving a
  parent re-render — the S-F48 property), and `Segments`, which is the largest
  consumer of folds and has no test.
- *Before phase 4:* **`Timeline`, `ScrubBar`, `FileList`, `FileView`,
  `Composer` and `Conversation`.** This is the expensive one and it is the
  phase that must not be started without it. `Timeline` alone carries roving
  tabindex, vi keys, `Home`/`End`/`Escape`, the HEAD marker one past the end,
  the invisible column cursor and `stopPropagation` so one Escape does not fold
  twice — six behaviours, no test, and phase 4 changes the keyboard model on
  purpose.
- *Before phase 5:* nothing new. `use-panes.test.tsx` already covers the hook,
  and phase 5 is restyling, not rewriting.

Composed stories (§6) make this cheaper than it sounds: the story enumerating a
component's states is also the fixture the test renders, so the net and the
gallery are one artifact rather than two.

---

## 11. The rollout

Seven phases. Each ships to `main`, leaves the console working, and is worth
having if the next one never happens. The exit criterion of every phase after
0 includes **deleting the code it replaced** — for reasons §15 explains, that
is the load-bearing discipline here, not an afterthought.

### Phase 0 — the workbench. No pixel changes.

Storybook 10 with `react-vite`; Tailwind v4 via `@tailwindcss/vite` with
`tokens.css` ported into `@theme` (the old file stays, still imported, so
nothing changes visually); `prettier-plugin-tailwindcss`; CVA;
`eslint-plugin-jsx-a11y` with its findings fixed or explicitly listed;
`src/**/*.stories.tsx` excluded from coverage; the `ui-` chunk and budget
declared. Tests for `Drawer` and `Confirm`.

**Why it ships alone:** the whole of it is verifiable by the four gates, and
the console's built output should be very nearly byte-identical. A phase whose
success condition is "nothing changed" is the cheapest possible way to find out
whether the toolchain integrates — and if Tailwind, Storybook or the a11y
plugin turns out to fight this project's config, it is discovered here, at a
cost of one revert.

**The `ui-` figure in each heading below is the pre-build estimate, and the
phases did not run in this order.** §3.1a has what was actually charged and
what shipped in which increment; nothing from here down has been renumbered,
because a plan edited to match its outcome stops being evidence about planning.

### Phase 1 — one dialog contract. **`ui-` 16.6 kB.**

`Dialog` on `@radix-ui/react-dialog` + `VisuallyHidden`. `Drawer` and `Confirm`
re-implemented on it; `TopicStatusDialog`'s hand-rolled trap deleted;
`WorkerDrawer` moved over; `window.confirm` in `ScrubBar` (S-D1) replaced with
the `Confirm` that already exists and is unused.

**Why it ships alone:** it removes the defect §2 opens with, in the one place
where the code already wrote down that the defect would happen. It deletes
roughly 120 lines of duplicated focus-trap logic across two files. It touches
`presentation/common/` and one file each in `research/` and `course/`, and
**does not touch `presentation/session/` at all** except to delete a
`window.confirm` — so the untested directory stays untouched while the net is
being built. It is the smallest Radix payment on the curve.

### Phase 2 — folds, toggles and choices. **`ui-` 22.9 kB.**

`Disclosure`, `ToggleGroup`, `RadioGroup`. The three fold implementations
become one. `Pane.tsx`'s glyph toggle gets a real accessible name via
`VisuallyHidden` — which, because `Pane` is shared, fixes it everywhere at
once, and lets `AgentWidget` drop the comment about a bug it declines to
spread.

**Why it ships alone:** S-D2 and S-D12 close. A keyboard user gains operable
revision headers, which they do not have today.

### Phase 3 — the floating layer. **`ui-` 38.6 kB.**

`Tooltip`, `Menu`, `Popover`, `Tabs`. The ~20 `title`-only explanations become
reachable by keyboard and touch. The agent dock's hand-written dismiss-and-
layering logic (L-F40) is replaced by Radix's dismissable-layer stack, which
handles the "a drawer is in front and owns Escape" rule structurally.

**Why it ships alone:** S-D3 closes, which is the largest single block of
inaccessible content in the console. The floating-layer cost is paid once here
and everything after is cheap.

### Phase 4 — the grid, the listbox, the toasts. **`ui-` 46.3 kB.**
**Prerequisite: the six session tests in §10 — met before the phase began.**

**All four of this phase's proposed components were declined, and the phase
still closed real defects.** That is not a reversal of §3.1's argument for
Radix; it is what happens when a plan written in one sitting meets four
increments of intervening work. What each was wanted for had either already
shipped by another route, or turned out not to need a component at all. The
audit that established this is recorded per item below, because the decision is
only worth as much as the evidence under it.

**`Select` is declined.** Both call sites are already native `<select>` with
proper labels — the workflow picker at `NewProjectForm.tsx` and the entity-type
filter at `GraphPane.tsx`. Native selects are keyboard-operable and
screen-reader-correct for free, and the likely original complaint was
appearance: a light UA popup in a dark console. That was fixed by
`color-scheme: dark` in `tokens.css`, which has its own browser test. Paying
+5.6 kB gzipped — the most expensive remaining primitive, and the one whose
marginal §3.1a actually measured — to replace two correct controls with
something that gives up the OS picker is the worst value in this document.

**`DataGrid` is declined as a one-caller abstraction.** `role="grid"` appears
exactly once in the codebase, in `Timeline.tsx`. The deliverable that justified
it — "a **visible** column cursor, which is the fix for S-D7" — had already
shipped inline there, with `aria-colindex`, an `aria-activedescendant` naming
the current cell, a rendered cursor class and a rule in `timeline.css` that
draws it. Extracting the pattern now would put working, argued, tested code
behind an interface with one consumer, and #26 is scheduled to restructure that
component's keyboard model anyway.

**`ListBox` is declined for the same reason, and its real defect was CSS.**
`FileList.tsx` is the only listbox, and its `aria-activedescendant` half was
already correct. What was actually broken was the other half of the spec's own
one-line description — "and a real focus ring". There was one, from the global
`:focus-visible` rule, and **none of it was visible**: `outline-offset: 1px`
draws outside the border box, and the listbox fills a scroll container that
clips exactly there. Measured in Chromium, the ring extended to `-3..423 x
-3..523` against a clip box of `0..420 x 0..176`. Zero pixels. Fixed with an
inward ring on the scroller, and a focus-dependent treatment on the selected
row, since in an `aria-activedescendant` listbox the selected row *is* the
keyboard cursor and a box ring alone does not say where you are.

That finding generalised, which is the most valuable thing this phase produced.
A sweep found the same shape wherever a scroller has no padding and its child is
`width: 100%`: the agent roster and the document list, both with rings entirely
clipped in their ordinary state, plus two scroll containers that Chromium makes
focusable with no `tabIndex` at all — a trap that reasoning gets wrong and only
measurement catches. Scrollers with ≥4px of padding have room for the ring and
were fine. The browser suite is where all of this lives, for the reason
`CLAUDE.md` gives: jsdom computes no layout, so every one of these bugs was
invisible to a fully green jsdom run.

**`Toast` is declined, and the two features it was wanted for were built by
hand instead.** L-F37 was already closed in `Toasts.tsx` — a real `<button>`
per toast rather than `role="button"` inside the live region, named for the
message it closes, with a hold on the expiry timer while a pointer or focus is
in the stack. Adopting `react-toast` meant rewriting all of that correct and
argued code to buy swipe-to-dismiss (irrelevant on a localhost desktop
console) plus an F6 hotkey and a focus restore on dismiss, which are ~20 lines
each. The price was +3.2 kB gzipped and the churn. Both features now exist:
F6 moves focus into the stack, registered only while a toast is up so the
browser keeps the key the rest of the time, and dismissing hands focus to the
next toast, then the previous, then back to wherever the reader came in from.

**Left undone:** F6 does not cycle *out* of the region (ARIA practices cycles
landmarks; this is one-way), and neither it nor the tree's `/` is documented
anywhere a reader would find it — `KeyboardHelp` is the surface for that and
§13 defers it to phase 7 on purpose.

**The two remaining items had already shipped.** The fork column's visible state
and `aria-colindex` closed S-D7 in an earlier increment, and `VirtualList`
already unifies L-F8's and R-F5.1's configurations — one wrapper, used by
`DocumentBrowser` and `ProjectList`. What has *not* shipped is the third thing
that sentence claims: the timeline is not virtualized. That is #26, and it is
not a follow-up to this phase but a redesign — a virtualizer unmounts
off-screen rows, and the timeline's tab stop lives *on* a row, so the moment the
selected row scrolls out the tab stop leaves the DOM, focus falls to `<body>`,
the grid's key handler stops receiving anything and `aria-activedescendant`
points at an id that no longer exists. Every one of those failures is silent.
The fix is to move the tab stop to the container with a two-level cursor, which
`2026-08-10-final-path-design.md` sequences after increment C on purpose.

It is also, on the evidence here, unmeasured: nothing in this repository
establishes how long a real session log gets, and the code's own prose assumes
"a hundred" rows — an order of magnitude below where virtualization pays for
itself. **It should be gated behind a measurement of a real log rather than
built on the assumption that a list wants virtualizing.**

**Why it shipped alone:** the reasoning below was written when this phase was
believed to be four new primitives and a keyboard-model change. It shipped alone
for a better reason than the one predicted — every increment in it was a defect
fix landing in a stylesheet or a component that already existed, verifiable in
isolation, with nothing downstream waiting on it.

**What the plan got wrong, kept because it is the useful part:** the most
dangerous defect named here — the invisible mode where an arrow key turns Enter
from "scrub" into "fork irreversibly" — was real, and was fixed before the phase
meant to fix it ever started. A phase defined by the components it adds will
mis-describe itself the moment the defects it was aimed at get closed another
way. The defects were the durable part of this plan; the component list was not.

### Phase 5 — the stylesheet migration completes.

Components move to utilities file by file; each deleted stylesheet is the exit
criterion. `panes.css`'s ad-hoc `7px`/`12px` become `--spacing-*` (S-§13.3) — values that
predate the spacing scale and have had no reason to change since.
`tokens.css` shrinks
to `@theme` plus the handful of layout constants.

**Why it ships alone:** `app-` falls as stylesheets are deleted, and it is
individually revertible per file.

### Phase 6 — real-browser accessibility.

`@storybook/addon-vitest` with browser mode, so axe's colour-contrast rules
have layout to run against. Optional, and last, because it is the only piece
that adds CI infrastructure.

### Phase 7 — the unified UI.

Only now does `unified-ui-proposal.md` §3's QUEUE / HOLDER / MATERIAL merge
become a layout problem instead of a component problem. Its `GateReview`, its
unified queue row, its six-facet MATERIAL shell and its `?` overlay are all
compositions of Tier-0 and Tier-1 components that exist by this point.

**On sequencing against that proposal.** Its §9 argues the decision bar should
be the first increment and I agree that it is the right first *feature* — it is
the highest-value user-visible change available and it is true under every
version of the merge. It is orthogonal to this document. My recommendation is
Phase 0 (invisible, cheap, fast) → the decision bar built on Phase 1's
`Dialog`, not before it. Building `GateReview` on the current hand-rolled
overlay means building it twice, and the delay is small.

---

## 12. What breaks, and when

**Phase 0.** Prettier reformats every `className` it can order — a large,
mechanical, one-time diff. Best landed in its own commit so it does not hide a
real change. `eslint-plugin-jsx-a11y` will fail the build on first run; the
count is unknown until it runs, and §2's list is a lower bound.

**Phase 1.** `TopicStatusDialog` keeps its backdrop-click-to-close; Radix's
`onPointerDownOutside` is the equivalent and is not identical — Radix closes on
pointer-down, the current code on click. Anyone who presses inside and releases
outside will see different behaviour. Trivial, real, worth knowing. The
`Drawer` API stays the same so its callers do not change.

**Phase 2.** Find-in-page no longer opens a closed `Discarded` fold (§9). One
browser feature, permanently lost, in one place.

**Phase 3.** `title` tooltips appear on hover after a delay rather than
instantly, and hover-delay is a taste question that will need one round of
adjustment. Native `title` on non-interactive elements should be *kept* where
the element is not focusable — a `Tooltip` requires a trigger, and turning a
static span into a button to give it a tooltip would be worse.

**Phase 4.** The keyboard model changes on purpose: the fork column becomes
visible, which means it becomes discoverable, which means people will use a
path that was previously secret. This is the intent and it is still a change in
behaviour for anyone who had learned the old one.

**Phase 5.** The highest-risk phase for *appearance* and the lowest for
*behaviour*. Every stylesheet deletion is a chance for a rule nobody knew was
load-bearing to vanish. The three responsive layouts (S-F19) and the
progressive field-dropping in the agent dock at 560px and 420px (L-F41) are
where I would expect the failures, because they are the rules least likely to
be exercised by anyone's normal window size.

**Not broken by anything here:** no event shape, no read model, no API
contract, no Python file. This is a frontend-only specification, which means
`CLAUDE.md`'s two most expensive traps — a schema evolution that cannot read
old payloads, and a read-model change verified only against a fresh database —
are not in play. That is worth stating because it is the main way this
migration is *less* dangerous than the feature work around it.

---

## 13. What I am not proposing

- **shadcn/ui's components.** Its architecture, yes; its component code, no.
  §3.1.
- **A styled component library.** Mantine, MUI and Chakra all fail on measured
  size before the design argument is even reached. §3.2.
- **React Aria Components**, despite believing it is the best-engineered of the
  three headless options. It costs 74% more than Radix for capabilities — deep
  internationalisation, sophisticated pointer modelling — that a single-user
  localhost console does not use. §3.1.
- **A CSS-in-JS runtime.** Every candidate adds runtime cost to solve a problem
  Tailwind solves at build time.
- **Rewriting `use-panes.ts`.** It is promoted and restyled, never
  reimplemented. §9.
- **Replacing `Markdown`, `CodeBlock` or `DiffView`.** `Markdown` is the single
  `dangerouslySetInnerHTML` in the application, greppable by design and
  memoised on its source; a library would take that property away and give
  nothing back.
- **Replacing `react-force-graph-2d`.** It is lazy, isolated and budgeted.
- **A design-token pipeline** (Style Dictionary, Theo, a `tokens.json`). One
  application, one theme, no native targets, no dark/light pair. `@theme` is
  the whole requirement.
- **Chromatic or any visual-regression service.** It is the natural next thing
  to reach for after Storybook and it needs a hosted service and a budget for
  a console with one user.
- **A `?` help overlay before phase 7.** It is a real gap (S-D6) and it is a
  *content* problem — the keyboard model must be made consistent before it is
  worth documenting, or the overlay documents the inconsistency.
- **Any change to the domain, application or infrastructure layers**, or to the
  `no-restricted-imports` rules that keep them apart. The layering is the
  architecture and nothing here touches it.
- **Making the learner toggle look like a permission boundary.** There is no
  authentication; it is a presentation affordance documented as one in three
  places, and S-§13.4 is right that a redesign implying otherwise is a
  regression. It becomes `Tabs` and stays exactly as honest.

---

## 14. Where I disagree with `unified-ui-proposal.md`

It is evidence, not scripture, and it is good evidence — §2 of it is the best
short account of this console's problem that exists. Four disagreements.

**14.1 Its §6.5 prices the bundle against a budget that has already moved.** It
states "the bundle budget is `app-` 57 and `total` 512". The current limits are
`app-` **80** and `total` 512 *(checked — `check-size.mjs`)*, raised on the
owner's instruction with the reasoning recorded in the file itself. This is not
a nitpick: 23 kB of `app-` head-room is what makes phase 5's coexistence period
affordable, and a document arguing that a merged page "grows `app-`" against a
57 kB ceiling reaches a more pessimistic conclusion than the facts support.

**14.2 Its §10 declines "a new design system or dependency", and the argument
given for that is weaker than the rest of the document.** It says the existing
eight primitives "cover everything here except the QUEUE's heterogeneous row,
which is a `Disclosure` with different chrome". Its own §4 asks for: a
`?` help overlay with a documented keyboard model, a `⋯` menu grown to three
verbs (its §8.3), a decision bar rendering grouped findings, six MATERIAL
facets with one selection model, and the `title`-only explanations addressed
"by the `?` overlay plus inline text". There is no menu primitive, no tooltip
primitive and no tab primitive in this codebase. The proposal's own scope
requires components its §10 says it does not need. The owner's instruction
settles the question anyway; I record it because the proposal reached the
opposite conclusion honestly and its reasoning should be seen to fail rather
than be overruled.

**14.3 Its §6.4 lists "Tests for `presentation/session/`" as the prerequisite
and misses `presentation/common/`,** which has zero tests and is upstream of
every page *(checked)*. Its §11 correctly names the session directory as the
strongest argument against itself; the same argument applies harder one layer
down, where a mistake reaches all four pages at once.

**14.4 I agree with its §11 conclusion and reach it by a different route.** It
says that if the test debt is judged too heavy, "the honest smaller version of
this document is §9 plus §3.4 plus the linkable-navigation fixes". I would say
something stronger: the component system in phases 0–3 is *strictly* the
smaller version, because it delivers most of the accessibility repair the merge
was going to deliver incidentally, at no layout risk at all, and it leaves the
merge cheaper to build afterwards. Where the proposal treats the test debt as a
reason to consider doing less, I treat it as a reason to do this first.

---

## 15. The strongest argument against this specification

**A half-finished strangler is worse than either end of it, and the only thing
holding this one together across seven phases is a promise.**

Stop after phase 2 and the console has Tailwind *and* nineteen stylesheets,
Radix dialogs *and* a hand-rolled popover, one fold implementation in `common/`
and another in `session/`. Every one of those is a *worse* state than either
endpoint, because a reader has to know which era a file belongs to before they
can change it, and because the second mechanism has to be maintained by people
who are no longer thinking about it. That hazard is intrinsic to the shape of
the plan and does not depend on anything having gone wrong here before.

**On precedent: I know of no case in this repository where a UI migration was
undertaken and abandoned.** I looked for one and did not find it, and the
absence cuts both ways — there is no local evidence that this team stalls
mid-migration, and equally no local evidence that it finishes one, because as
far as I can tell a migration of this shape has not been attempted. The risk
below is argued from the structure of the plan, not from this project's record.

> **Amended after review.** An earlier draft of this section claimed the
> repository had "already run this experiment and lost", citing
> `landing-page.md` §6's design language as having been applied to the landing
> page and "never back-ported" to the session view. The owner has corrected
> this: **the landing-page work was scoped to the landing page.** Nobody
> undertook to propagate the design language further, so nothing was abandoned
> — the boundary is evidence of what that project's scope was, not of a
> migration that stalled. The claim assumed an intent that was never held, and
> a design document asserting a colleague's abandoned intent is worse than one
> making no historical claim at all. It is amended here rather than deleted
> quietly, per this repository's convention that a document records where it
> was wrong.
>
> The underlying code observation survives the correction and is used
> accordingly: `panes.css`'s `7px`/`12px`/`34px` sit outside the `--space-*`
> scale (S-§13.3), and that is real accumulated inconsistency worth paying down
> — §4 and phase 5 both schedule it. It is a description of the code, not a
> verdict on anyone's follow-through.

I do not have a rebuttal that removes the risk. Four things reduce it, and I
want to be clear that they are unequal:

- **Phase 0 is genuinely free to abandon.** It adds tooling and changes no
  behaviour, so stopping after it costs a `package.json` entry.
- **Phases 1–3 do not touch `presentation/session/`.** The half-migrated state
  they leave is confined to `common/`, `research/`, `course/` and `tree/`.
- **Each phase's exit criterion is deleting what it replaced.** A phase that
  adds a new mechanism without removing the old one has not shipped. This is
  the one that actually matters, and it is **a promise rather than a
  mechanism** — nothing in the four gates fails when a superseded
  implementation is left in place, so it holds exactly as long as someone
  chooses to enforce it. If the owner wants it made real, the honest way is a
  lint rule or a deletion checklist per phase, and neither exists today.
- **The `ui-` budget makes the cost visible per phase**, so an abandoned
  migration at least announces what it is still paying for.

That last honesty applies to the whole document. **Nothing here has been run.**
No component was migrated, no story was written, no test was proved red. I
measured bundles and read source; I did not build the thing I am specifying.
The two disasters `landing-page.md` §8 records were both found by a person
using the product, after passing every gate — and a specification is a weaker
artifact than a passing test suite.

**The second argument against it.** 46 kB of gzipped JavaScript is 19% of what
this console currently downloads, bought entirely for behaviour a user never
sees added. If the owner's judgement that exploration outranks bundle size
reverses before phase 4, the sunk portion is not recoverable without undoing
the work — Radix cannot be partially removed once four components depend on its
dismissable-layer stack.

**The third.** I recommended Radix over React Aria Components partly because
this console has one user on one machine speaking one language. That is a
correct reading of today and a bet against the product changing. If this ever
becomes something more than a localhost developer console, the 29 kB I saved
will look like the wrong trade, and by then it will be four phases deep.

---

## 16. Open questions for the owner

1. **Is `ui-` at 52 kB acceptable as a standing cost?** §8.2 argues yes under
   the current priority and prices it honestly. It is the one number in this
   document that a "no" would invalidate the whole of, and it is worth
   answering before phase 1 rather than at phase 4.
2. **Should the decision bar precede phase 1 or follow it?** §11 recommends
   following, at a cost of a few days, to avoid building `GateReview` twice.
   The counter is that the decision bar is the only genuinely user-visible
   improvement in either document.
3. **Is find-in-page on folded content worth keeping anywhere?** §9 trades it
   away globally for externally-owned state. It could be kept for `Discarded`
   alone by leaving that one as `<details>` — at the cost of the inconsistency
   S-D14 complains about.
4. **How aggressive should phase 5 be?** Deleting nineteen stylesheets file by
   file is a long tail of small risky changes. An alternative is to stop after
   phase 4 with Tailwind used only for *new* components and the old stylesheets
   frozen — which is a coherent, permanent, two-language end state, and is
   exactly what §15 warns against. I take the complete-the-migration arm and I
   am least confident about it.
5. **Does `presentation/lesson/` belong in this at all?** Six components, zero
   tests, four interactive widget types with their own keyboard models
   (C-F65, S-F34), and grading that is server-side by design. It is the one
   area I have scoped no phase for, because none of the four reports treats it
   as broken — but "not reported as broken" and "tested" are not the same
   thing, and it has the same coverage as `common/`.
