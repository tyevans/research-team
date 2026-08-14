# Audit 3 — the component-system spec, the foundations, and the stylesheet end-state

Read-only audit at `9fa6c7b` (merged `main`) in the `gate-review-tooltip`
worktree. **Nothing was run**: no gates, no build, no tests, no git writes. Every
measurement below comes from reading files, from `git ls-tree`/`git archive` over
history, or from the **already-built** stylesheet and chunks committed at
`research_team/interfaces/web/static/assets/`. Where a claim can only be settled
by a run, it is marked UNVERIFIABLE and says which run settles it.

Findings are ordered by what getting them wrong costs.

---

## F1. The single-side-border rule is half wrong, and the half that is wrong is the one the corpus is acting on

**Cost of getting this wrong: a sweep of ~20 call sites, a new `check-tailwind.mjs`
rule, and a `CLAUDE.md` entry, all aimed at a defect this build does not have —
while the half that *is* real gets less attention than the half that is not.**

`CLAUDE.md` states the rule in two halves:

> The case that bites in the other direction: `border-t` *with* a width but
> *without* `border-solid` draws nothing at all, because every side's style is
> still `none`.

`BACKLOG.md` B55 (`BACKLOG.md:1164-1198`) is built entirely on that half — four
instances listed, two "fixed", two outstanding (`presentation/common/Drawer.tsx:163`,
`presentation/shell/DecisionBar.tsx:44`), plus a proposed `check-tailwind.mjs`
rule: "a directional `border-{t,r,b,l}` in a class list with no `border-solid`
… is always this bug".

**It is not this bug.** Tailwind v4 does not emit a bare width longhand. From the
built stylesheet in this repository:

```
.border-l{border-left-style:var(--tw-border-style);border-left-width:1px}
.border-b{border-bottom-style:var(--tw-border-style);border-bottom-width:1px}
.border{border-style:var(--tw-border-style);border-width:1px}
@property --tw-border-style{syntax:"*";inherits:false;initial-value:solid}
```

(`research_team/interfaces/web/static/assets/index.css`, all four present.) The
registered custom property's `initial-value` is `solid`, and Tailwind emits a
second belt-and-braces assignment `--tw-border-style:solid` on `*,::before,::after`
inside its Safari `@supports` block. So `border-b` alone resolves to
`border-bottom-style: solid; border-bottom-width: 1px` and **draws**. No
`border-solid` is required, and `border-style:none` appears nowhere in the built
sheet (0 occurrences).

The repository already contains the measurement that says so, and it is green in
the browser suite:

- `frontend/src/presentation/common/Drawer.tsx:162` writes
  `border-l border-line` with no `border-solid`, and `.drawer` gets no border rule
  from any stylesheet (`responsive.css:95-99` sets only width/max-width/min-width).
- `frontend/src/presentation/common/shell-reached-dressing.browser.test.tsx:157-158`
  asserts `borderLeftWidth === '1px'` **and** `borderLeftStyle === 'solid'` on that
  same element.

If B55's premise held, that assertion would be red.

**The half that is real, and which no instance currently violates.**
`.border-solid{--tw-border-style:solid;border-style:solid}` — the shorthand, all
four sides. So `border-solid` paired with a directional width and *without*
`border-0` does leave three sides styled with no explicit width, falling back to
the UA `medium`. That is CLAUDE.md's first half and it is correct. I swept every
string literal in `frontend/src/**/*.{ts,tsx}` (comments stripped) for that
pattern: **zero instances**. The `border-0 border-b border-solid border-line` form
in `AskHead.tsx:27`, `AskComposer.tsx:43`, `AskTurn.tsx:36` is correct but
redundant under v4 — `border-b` alone is sufficient and equivalent.

**Replacement sentences.**

For `CLAUDE.md`: *"Tailwind v4 emits the style longhand with the width
(`border-b` → `border-bottom-style: var(--tw-border-style); border-bottom-width:
1px`) and registers `--tw-border-style` with `initial-value: solid`, so a
directional width alone draws. The half that still bites is the other one:
`border-solid` sets `border-style` on all four sides, so pairing it with one
directional width and no `border-0` gives the other three sides the UA's `medium`
and draws a box. Verified against the built `index.css`, not reasoned."*

For B55: *"Premise withdrawn. The two remaining entries are not defects; a
directional width alone draws solid under Tailwind v4. What is worth keeping is
the inverse rule for `check-tailwind.mjs`: `border-solid` (or any explicit
`border-style` utility) beside a directional width with no `border-0` is the box
this repository actually drew twice."*

**What is still owed.** Something was seen by eye in Storybook, twice, in both
directions. The first direction is explained above. The second — a case where a
directional width visibly drew nothing — is not explained by the current build and
the observation should be re-taken rather than assumed away, because if it
reproduces, my reading of the built CSS is missing something. **UNVERIFIABLE from
here:** what settles it is one browser test rendering `<div className="border-b
border-line" />` and asserting `getComputedStyle(el).borderBottomStyle === 'solid'`
— five lines, and it belongs in `src/styles/` beside `spacing-zero.browser.test.tsx`
and `hidden-attribute.browser.test.tsx`, which are the same shape of standing
proof about what this build's missing preflight does and does not cost.

---

## F2. `component-system-spec.md` §3.3's stylesheet figures are wrong by ~2x, and a load-bearing conclusion rests on them

**Cost: the whole "the CSS side is roughly neutral" argument (§3.3, restated in
§8.2's honest framing) is built on a denominator that is 2.4x too small.**

§3.3:329 and §3.3:367 state:

> Today's nineteen stylesheets are 61.5 kB raw / 11.5 kB gzipped.

The file count was right at the time — `git ls-tree a010974 frontend/src/styles/`
returns exactly 19 `.css` files. The bytes were not. At that same commit:

| | spec §3.3 | measured at `a010974` | measured at `9fa6c7b` (22 files) |
|---|---|---|---|
| raw | 61.5 kB | **112.7 kB** (115,378 B) | **193.5 kB** (198,117 B) |
| gzip (concatenated) | 11.5 kB | **27.3 kB** (27,986 B) | **56.8 kB** (58,189 B) |
| lines | — | 4,989 | 6,298 |

No subset of the 19 sums to 61.5 kB — the four largest alone (`research`,
`course`, `components`, `tree`) are 65.1 kB. The figure is not a scoping choice.

The conclusion it supports is §3.3:369-372: *"a reasonable estimate for full
coverage is 8–12 kB — at or slightly below where the hand-written CSS already
is."* Against 27.3 kB, Tailwind at 8–12 kB is not "at or slightly below" the
hand-written CSS; it is **less than half of it**. The argument gets *stronger*,
not weaker — which is worth saying, because a wrong number that flatters the
conclusion and a wrong number that understates it are both worth the same
correction, and this one has been quoted onward.

**Replacement sentence for §3.3:367:** *"Today's twenty-two stylesheets are
193.5 kB raw / 56.8 kB gzipped as source; the whole `index.css` chain as built and
minified measures 13.9 kB gzipped, Tailwind's utilities included. At `a010974`,
when this section was written, the nineteen files then present were 112.7 kB raw /
27.3 kB gzipped — the 61.5 / 11.5 originally printed here was wrong by roughly a
factor of two in both columns and was never re-derived."*

Related, same section: §3.3's table row *"Keep 19 hand-written stylesheets"* and
§16's open question 4 *"Deleting nineteen stylesheets file by file"* both still say
nineteen. There are 22, frozen by name in `frontend/scripts/check-deleted.mjs:400-423`.
§11:1009 says 22 and *"roughly 6430 lines"*; the current count is **6,298**.

---

## F3. `increment-c-plan.md` §5.1's combinator table is stale — slice 3's headline hazard no longer exists

**Cost: slice 3 is planned around seven `>` selectors in `research.css` that
slices 1 and 2 already deleted, and the file that actually carries the risk into
slice 2 (`conversation.css`) is undercounted.**

The plan's table is measured at `f87443b`. Slices 1 and 2 landed after that
(`c1fbc6c`, `17813b7`, `427d648`), and the phase-C1 rule in `check-deleted.mjs:344-356`
deleted the research and course combinators along with the views. Re-measured now
over `frontend/src/styles/*.css`, comments stripped, counting `>`/`+`/`~` in
selector preludes only:

| File | §5.1 says | Actual at `9fa6c7b` | Note |
|---|---|---|---|
| `conversation.css` | 7 | **8** (`:48, 53, 56, 184, 190, 193, 309, 317`) | plan listed 8 positions under the count 7 |
| `research.css` | 7 | **0** | every one went with `ResearchView` |
| `responsive.css` | 6 | **3** (`:12, 25, 73`) | only the session pair and the tree remain |
| `course.css` | 4 | **2** (`:452, 467`) | plan listed 5 positions under the count 4; both survivors are `AutonomyPanel` |
| `timeline.css` | 2 | 2 (`:41, 212`) | |
| `tree.css` | 2 | 2 (`:293, 303`) | |
| `components.css` / `structure.css` | 2 each | 2 / 2 | |
| `composer.css` / `markdown.css` / `workspace.css` | 1 each | 1 / 1 / 1 | |
| `layout.css`, `entity.css`, `states.css`, `agents.css`, `shell.css`, `tokens.css`, `theme.css` | 0 | 0 | |
| **total** | — | **24** | |

VERIFIED, unchanged: **there is not a single `+` or `~` combinator in the
directory.** The plan's correction of the spec on that point holds, and my scan
independently reproduces it.

**Replacement for §5.1's `responsive.css` row and paragraph.** The paragraph says
*"each of slices 1, 2 and 3 silently voids a rule in a file it is not touching"*.
Slices 1 and 3's exposures are gone; only slice 2's remain:
*"`responsive.css` now holds three combinators: `.lay-split[data-split='session'] >
[data-pane='conversation']` at `:12` and `:25` (inside `@media (width >= 821px) and
(width < 1181px)`), and `ul.tree ul > li:last-child::after` at `:73`. Only slice 2
voids anything here, and it voids both session rules at once — at a viewport no
default window is at, which is why the grep is the whole mitigation. The course and
research combinators this table listed were deleted with their views in slices 1
and 2."*

Two internal inconsistencies worth fixing while the table is edited: the
`conversation.css` row prints 7 against 8 line numbers, and the `course.css` row
prints 4 against 5.

---

## F4. `panes.css` does not exist, and four documents still schedule work in it

**Cost: a reader following the corpus goes looking for a file that was renamed
eight commits of migration ago, and the debt it named is now somewhere else.**

`check-deleted.mjs:113-127` records the rename: *"`panes.css` is `scrub-bar.css`
now and holds no pane rule."* The phase-C rule forbids `^\.pane\b`, `^\.pane-head\b`
and six siblings anywhere under `styles`. Confirmed against the directory listing —
no `panes.css`, and `scrub-bar.css` is in the frozen manifest.

Still naming it as live:

- `component-system-spec.md:436` — *"`panes.css`'s ad-hoc `7px`/`12px` (S-§13.3)
  become `--spacing-*` during phase 5"*. Carries a phase-5-dissolved parenthetical
  at `:441` but not a note that the file is gone.
- `component-system-spec.md:995` — same sentence inside the superseded phase-5 body.
- `component-system-spec.md:1266` — the §15 amendment.
- `unified-ui-proposal.md:814` — *"`panes.css` uses ad-hoc `7px`/`12px`/`34px`"*,
  and *"Promoting `use-panes.ts` to the whole app promotes that debt with it."*
  `use-panes.ts` is also gone: `check-deleted.mjs:46` forbids `\busePanes\b` under
  `presentation/session`, and what exists is `layout/use-split-panes.ts`,
  `session/use-session-panes.ts`, `project/use-project-panes.ts`.
- `ui-foundations.md:747` — *"`panes.css`'s ad-hoc `7px`/`12px` move onto
  `--space-*` here"*, an unactioned recommendation in a shipped phase.

**The debt itself survives and should be re-pointed rather than dropped:**
`scrub-bar.css:16-17` (`gap: 12px; padding: 7px 14px`), `:32` and `:53` (`gap: 7px`).
`34px` is now the `--rail-w` token (`tokens.css:147`) and is guarded by
`check-deleted.mjs:72`, so that third of the debt is genuinely paid.

**Replacement sentence** (for the spec §4 and the proposal §6.5): *"The ad-hoc
`7px`/`12px` are in `scrub-bar.css:16-17, 32, 53` — `panes.css` was renamed when the
session panes moved to `Split`/`Pane`, and the file holds no pane rule. `34px` is
`--rail-w` in `tokens.css:147` and `check-deleted.mjs` forbids the literal. The
remaining two values die with the scrub bar whenever slice 2 rebuilds it; nothing
schedules them separately."*

---

## F5. §5.2's clipped focus ring: mechanism VERIFIED, the two "live exposures" are mis-described, and none of it is measured

The mechanism is real and paid for three times, each fix carrying its measurement
in the stylesheet:

- `workspace.css:17-48` — the file list, ring `outline-offset: -2px`.
- `research.css:383-401` — `.document-row-open`, with the measured boxes
  (`-2..342 x -2..55` against a clip at `1..339 x 1..199`).
- `research.css:337-347` — `.document-list-scroll`, the Chromium
  focusable-scroll-container trap, measured at 1440×900.
- `agents.css:198-217` — the agent roster.

**Line citation is stale.** §5.2 cites `tokens.css:294` for the global ring; it is
`tokens.css:340-341` (`outline: 2px solid var(--accent); outline-offset: 1px`).
`layout.css:221` for `.lay-pane-body { overflow: auto }` with no padding is
correct.

**The two claimed live exposures do not hold as stated.**

- `.extraction-merge-list` — cited as `course.css:509-518`, actually
  `course.css:479-488`. `padding: 0` and `overflow-y: auto` are both still there,
  VERIFIED. But its children are plain `<li>` text: `ExtractionPane.tsx:159-167`
  renders `<li className="extraction-merge">{line}</li>` with no link, no button,
  no `tabIndex`. **There is no focusable row to lose a ring.** The only exposure
  left is the Chromium focusable-scroll-container trap on the `<ul>` itself, which
  is a different defect with a different fix and is not what §5.2 describes.
- `.topic-list` — cited as `research.css:203-214`, actually `research.css:81-92`.
  `padding: 0`, `overflow-y: auto`, VERIFIED, and `entity.css` declares no
  `:focus-visible` rule at all. But the focusable child is not a full-width row:
  `TopicRow.tsx:109-126` renders `<li className="ent-topic-row">` (not focusable)
  containing `<a>{topic.question}</a>` inside `.ent-topic-question`. An inline link
  is text-width, so the horizontal clipping the three prior fixes measured does not
  apply the same way; the first and last rows' vertical ring is the plausible loss.

**Replacement sentence:** *"Two exposures sit under `.lay-pane-body` today and
neither is the full-width-row shape the three prior fixes measured. `.topic-list`
(`research.css:81-92`, `padding: 0`) holds rows whose only tab stop is an inline
`<a>` (`TopicRow.tsx:120`), so the loss is vertical on the first and last row
rather than the sides. `.extraction-merge-list` (`course.css:479-488`) holds no
focusable child at all; what it exposes is the Chromium focusable-scroll-container
trap that `research.css:337` records, and the fix for that is an inward ring on the
scroller, not on a row. Both are unmeasured."*

**Both prior slice reports list this as unmeasured and that is still true.**
UNVERIFIABLE from here. What settles it: `npm run test:browser` with a case
following `FileList.browser.test.tsx` — focus each element and compare
`getBoundingClientRect()` of the ring's outer edge against the scroller's padding
box, at the 1440×900 `vite.config.ts:288` sets. The §5.2 instruction that matters
for the slices ahead — *"any full-width focusable row inside a region's scroller
needs `outline-offset: -2px` at the point it is written"* — is correct and should
stand unchanged.

---

## F6. `check-tailwind.mjs` cannot catch the border class through the mechanism it has, and B55 says it can

`findSilentUtilities` (`check-tailwind.mjs:143-156`) asks one question: does a
selector for this class name appear in the built `index.css`? `border-b` **does**
emit a rule. So the check as built would never have caught any B55 instance,
including under B55's own (mistaken) premise — the defect it describes is a
*missing companion class*, not a missing rule, and no amount of `emitsARule` sees
it. B55's *"That would have caught all three at the commit that wrote them"* is
WRONG about this script.

What *is* cheap, and what the file is already shaped for: the scan at
`check-tailwind.mjs:93-113` already tokenises every string literal in
`src/**/*.{ts,tsx}` with comments stripped and line numbers preserved. A
**co-occurrence pass** over that same token set costs about fifteen lines and could
catch the class that is real:

- `border-solid`/`border-dashed`/`border-dotted` beside a directional width with
  no `border-0` — the box CLAUDE.md records drawing twice. (Currently zero
  instances; this is a ratchet, not a fix.)
- Two utilities setting the same property in one class string — the coin-toss
  `primitives.tsx:44-48` documents for `text-fg-dim` beside `text-k-failure`. That
  comment names a real hazard and nothing enforces it.
- The file's own stated gaps: a **colour** typo (`bg-bg-panel-3`) and a
  **breakpoint** variant (`md:`) both emit nothing silently. `theme.css:49-54`
  declares no `--breakpoint-*`, so every `sm:`/`md:`/`lg:` variant compiles to
  nothing today. I swept `presentation/**` for those variants: **zero uses**, so
  this is latent rather than live — but it is one `md:flex` away from being live,
  and extending `CANDIDATE` to flag any *variant prefix* that is not a declared
  breakpoint or a known state is strictly easier than the colour case.

**Replacement sentence for B55's last paragraph:** *"The `check-tailwind.mjs` rule
worth writing is the inverse of the one proposed here, and it is a co-occurrence
pass rather than an emission check: `border-solid` beside a directional width with
no `border-0` draws three unwanted sides, and that is the half of `CLAUDE.md`'s
rule this build actually has. An emission check cannot see either half — `border-b`
emits a rule."*

---

## F7. What else the corpus assumes preflight provides

Both live examples in the brief are "the spec assumes a browser default this build
does not have". I checked the rest of Tailwind's preflight against
`frontend/src/styles/`:

| Preflight does | This build | Status |
|---|---|---|
| `box-sizing: border-box` on `*` | `tokens.css:247-249` | covered |
| `margin: 0` on body | `tokens.css:251-255` | covered |
| `font: inherit` on form controls | `tokens.css:269-274` | covered (task #34) |
| background/colour on form controls, `a { color: inherit }` | `tokens.css:304-322` | covered (task #34) |
| `[hidden] { display: none }` | `base.css:57-59`, with `!important` and `:where()` | covered, today |
| `border-style: solid` on `*` | **not needed** — Tailwind v4's `@property --tw-border-style` | F1 |
| **`margin: 0` on `h1`–`h6`, `p`, `ul`, `ol`, `pre`, `blockquote`** | nothing | **open** |
| **`list-style: none; padding: 0` on `ul`/`ol`** | nothing global; written locally **20 times** across five stylesheets (`course.css` ×9, `research.css` ×7, `tree.css` ×2, `components.css`, `entity.css`) | **open** |
| `display: block` on `img`/`svg`/`canvas` | nothing | open, low stakes |
| `border-collapse` on `table` | nothing | no tables shipped |

**The list case is the `[hidden]` shape exactly**, and it is the one to act on
before increment C's remaining slices: a bug diagnosed and repaired locally many
times over, where the next caller — a QUEUE row list or a MATERIAL facet list built
in utilities — gets no help from any of the twenty repairs and silently inherits
discs and 40px of `padding-inline-start`. The `[hidden]` fix retired three local
patches; this would retire twenty. The heading/paragraph margins are the same
shape one step down, and `m-0` does now emit correctly (`.m-0{margin:var(--spacing-0)}`
with `--spacing-0: 0px` at `theme.css:196`), so the utility route works when
someone remembers it.

**UNVERIFIABLE from here:** whether adding `ul, ol { list-style: none; padding: 0 }`
to `base.css` regresses anything is a Storybook/browser question —
`markdown.css` renders authored lists (`.md-list`) that *want* markers, so the rule
would have to exempt `.md` content or be scoped away from it. That is the design
question, and it is why this is a finding rather than a patch.

---

## F8. Phase 6 shipped, but not as the spec describes it — and §6/§7's picture of the toolchain is stale

- §6:530 and §11:1074-1078 specify phase 6 as `@storybook/addon-vitest` with
  browser mode. **It is not installed.** `package.json` has `@vitest/browser`,
  `@vitest/browser-playwright`, `playwright` and a direct `axe-core` devDependency
  with a paragraph (`package.json:29`) explaining why the version is pinned
  directly rather than through the lint plugin. What shipped is a hand-written
  suite: **15 `*.browser.test.tsx` files**, plus `src/a11y.browser.test.tsx`
  driving axe itself.
- §6:511 specifies `@storybook/addon-a11y` running axe against each story. **Not
  installed.** Same substitution.
- §7:562 states the chain as *"format:check && lint && typecheck && test:coverage
  && build && size"*. It is now eight steps —
  `… && size && deleted && check:tailwind` (`package.json:24`). §7's stronger claim
  that **no new CI job is created** VERIFIED: both additions are inside the chain.
- §6:541-549's coverage warning VERIFIED as heeded — `.stories.tsx` are excluded
  from the walk in both `check-tailwind.mjs:77` and the coverage config.

**Replacement sentence for §11's phase 6:** *"Shipped, by a different mechanism
than the one proposed. Rather than `@storybook/addon-vitest` running every story,
`vitest`'s browser project runs a hand-written `src/**/*.browser.test.tsx` suite —
sixteen files today — with `axe-core` imported directly by `src/a11y.browser.test.tsx`
so its version is pinned rather than chosen by a lint plugin's resolution. The
trade is that the suite is written rather than generated, and that it stays outside
`verify` and outside CI, which the spec's version would not have been."*

---

## F9. The as-built bundle figures in §8.2 have drifted, and `app-` is the one to watch

§8.2:652-655 states: *"`ui-` is 33.0 of 56 with five primitives in it, `app-` is
67.6 of 80, and the whole console is 280.7 of 512."*

Gzipping the committed build in `research_team/interfaces/web/static/assets/`:

| bucket | §8.2 says | on disk | limit |
|---|---|---|---|
| `ui-` | 33.0 | **32.7** | 56 |
| `app-` (`app.js` 57.7 + `index.css` 13.9) | 67.6 | **71.6** | 80 |
| `total` | 280.7 | **283.7** | 512 |

**Caveat, stated because it changes what the numbers are worth:** `app.js` on disk
is timestamped 22 minutes after every other artifact, so this build is possibly a
partial rebuild and is certainly not guaranteed to correspond to `9fa6c7b`. The
figures are indicative, not a `npm run size` result. **UNVERIFIABLE:** what settles
it is `npm run build && npm run size`.

The direction is what matters and it is worth a sentence in the spec: `app-` has
moved from 58.8 (baseline) through 67.6 to ~71.6 against 80, while `ui-` is
static. §3.3's *"the strangler fits inside the existing `app-` budget with room to
spare"* was an argument about a coexistence peak that §11 then dissolved, and
`app-` is now growing for ordinary reasons with **~8 kB of slack**, not 23. The
23 kB in §14.1 is spent.

**Replacement sentence for §14.1's parenthetical:** *"(Phase 5 was dissolved — §11.
The head-room is now ordinary slack rather than a budget earmarked for two
stylesheet languages at once, and most of it has since been spent: `app-` measures
about 71.6 kB of 80.)"*

---

## F10. `unified-ui-proposal.md` §6.5 is stale in three ways, of which the spec catches one

§6.5:808 — *"The bundle budget is `app-` 57 and `total` 512"*. Caught by spec
§14.1; the limits are `app: 80` and `total: 512` (`check-size.mjs`, and the raise
carries its own multi-paragraph note). Two further staleness items §14.1 does not
catch, both in §6.5's second paragraph: `panes.css` no longer exists (F4), and
`use-panes.ts` was never "promoted to the whole app" — it was replaced by
`Split` + `use-split-panes.ts`, with `usePanes` forbidden under
`presentation/session` by `check-deleted.mjs:46`. The proposal's *"Promoting
`use-panes.ts` to the whole app promotes that debt with it"* describes a migration
that did not happen the way it predicts.

The one claim in §6.5 that is VERIFIED and load-bearing: *"`GraphCanvas` stays lazy
… so the ~60kB force-graph chunk is still not paid by a reader who came for a
transcript."* `graph.js` measures 60.9 kB gzipped on disk against a 74 kB budget,
and `GraphCanvas.js` is a separate 1.3 kB wrapper — exactly the arrangement
`check-size.mjs` documents.

---

## F11. Two phase numbering schemes are in use, and nothing reconciles them

`check-deleted.mjs` carries 33 rules under **eleven distinct phase labels**:
`1, 2, 3, 4, 5` (the spec's phases) and `A, B, C, C1, D, E` (the
`ui-foundations.md` phases). The task list adds a third vocabulary: "Increment A"
(#27, the decision bar), "Increment B" (#4, the floating layer = spec phase 3),
"Increment C" (#28). So spec phase 3, task "Increment B" and check-deleted phase
`3` are the same work under three names, while check-deleted phase `C` and phase
`C1` are *foundations* phase C and *increment* C slice 1 respectively — two
different things one character apart, in one array.

This costs nothing today because every rule carries a `what`/`why` sentence. It
costs something the first time somebody greps for "phase C". **Recommendation:**
one sentence above `RULES` mapping the three schemes, rather than a renumbering —
the spec's own §11:830 argues correctly that *"a plan edited to match its outcome
stops being evidence about planning"*, and the same holds for the rules.

---

## F12. The "die with their screens, never ported" policy — where the spec still says otherwise

The brief asked whether the spec still says it everywhere. It very nearly does.
The policy is stated at §11:1005-1007 and mechanised at
`check-deleted.mjs:366-423`; §4:441, §10:795-797, §12:1131-1137, §14.1:1196-1199
and §16's answer at :1331 all carry in-place dissolution notes. That is
better-maintained than the rest of the corpus.

The places it does not, all of which are *count* or *file* errors rather than
policy errors, are F2 (nineteen/61.5 kB) and F4 (`panes.css`). One more, minor:
§9's Tier-0 table still lists `Dialog`, `Disclosure`, `ToggleGroup` and
`VisuallyHidden` with phase numbers, where §3.1a:249-251 records that they are
first-party and that `package.json` holds only `dropdown-menu`, `popover`,
`radio-group`, `tabs`, `tooltip`. VERIFIED — five Radix packages,
`package.json:37-41`. The table is a plan and the correction is elsewhere in the
same document, so this is a navigation cost rather than a wrong claim.

---

## Classification table

| # | Claim | Where | Verdict |
|---|---|---|---|
| 1 | `border-t` with width and no `border-solid` draws nothing | `CLAUDE.md`; `BACKLOG.md:1170-1172` | **WRONG** — F1 |
| 2 | B55's two remaining instances are defects | `BACKLOG.md:1182-1186` | **WRONG** — F1 |
| 3 | `border-solid` + directional width + no `border-0` draws three unwanted sides | `CLAUDE.md` | **VERIFIED** — built `index.css`; zero live instances |
| 4 | `check-tailwind.mjs` would have caught the border class | `BACKLOG.md:1194-1198` | **WRONG** — F6; a new co-occurrence pass could |
| 5 | Nineteen stylesheets, 61.5 kB raw / 11.5 kB gzipped | spec §3.3:367 | **WRONG** — 19 files was right; 112.7 / 27.3 kB at that commit — F2 |
| 6 | 22 stylesheets, ~6430 lines | spec §11:1009 | **VERIFIED** on count, **STALE** on lines (6,298) |
| 7 | Tailwind full coverage 8–12 kB is "at or slightly below" today's CSS | spec §3.3:369-372 | **WRONG, in the conclusion's favour** — F2 |
| 8 | `check-deleted.mjs` freezes 22 stylesheets and fails both directions | spec §11:1027-1035 | **VERIFIED** — `check-deleted.mjs:400-423, 487-522`; manifest matches disk exactly |
| 9 | Stylesheets die with their screens, never ported | spec §11:1005 | **VERIFIED** as policy and as mechanism |
| 10 | `panes.css`'s 7px/12px become `--spacing-*` | spec §4:436, §11:995; proposal §6.5:814; foundations §3.3:747 | **STALE** — file gone; debt is `scrub-bar.css:16-17, 32, 53` — F4 |
| 11 | `use-panes.ts` is promoted to the whole app | proposal §6.5:816 | **WRONG** — replaced by `Split`/`use-split-panes.ts` — F10 |
| 12 | Combinator counts: research 7, responsive 6, course 4, conversation 7 | plan §5.1:469-477 | **STALE** — 0 / 3 / 2 / 8 — F3 |
| 13 | Not a single `+` combinator in the directory | plan §5.1:481 | **VERIFIED** — independently re-scanned; no `+` and no `~` |
| 14 | Each of slices 1, 2, 3 voids a `responsive.css` rule | plan §5.1:498 | **STALE** — only slice 2 now — F3 |
| 15 | `.extraction-failed > .extraction-summary` is this failure already having happened | plan §5.1:505; `check-deleted.mjs:265` | **VERIFIED** as a recorded incident |
| 16 | Global ring is 2px at `outline-offset: 1px`, `tokens.css:294` | plan §5.2:511 | **VERIFIED** on substance, **STALE** on line — `tokens.css:340-341` |
| 17 | Three prior fixes, each carrying its measurement | plan §5.2:516-522 | **VERIFIED** — `workspace.css:17-48`, `research.css:383-401`, `agents.css:198-217`; plus a fourth at `research.css:337-347` |
| 18 | `.topic-list` and `.extraction-merge-list` are live exposures with no inward-ring fix | plan §5.2:534-539 | **WRONG as described** — neither has a full-width focusable row — F5 |
| 19 | The clipped ring is measured somewhere in increment C | plan §5.2 | **UNVERIFIABLE** — still unmeasured; both prior slice reports agree |
| 20 | `.lay-pane-body` is `overflow: auto` with no padding | plan §5.2:532 | **VERIFIED** — `layout.css:221` |
| 21 | jsdom judges none of §5.1/§5.2 | plan §5.3 | **VERIFIED** — and heeded: slices 1 and 2 each added a browser test (`TopicQueue.browser.test.tsx`, `ProjectView.browser.test.tsx`) |
| 22 | Viewport is set in `vite.config.ts`, not by the test wrapper | plan §5.3:559 | **VERIFIED** — `vite.config.ts:288`, 1440×900, with the reasoning above it |
| 23 | The built output is committed, so every slice lands a large diff | plan §5.4; foundations §4.3 | **VERIFIED** — `static/assets/` is tracked; task #44 removed the hashes that made it conflict |
| 24 | `src/presentation/**` has no coverage floor | plan §5.4; foundations §4.3 | **VERIFIED** |
| 25 | Phase 6 = `@storybook/addon-vitest` + `addon-a11y` | spec §6:511, :530; §11:1074 | **STALE** — neither installed; 15 hand-written browser tests instead — F8 |
| 26 | The verify chain is six steps, no new CI job | spec §7:562 | **STALE** on the list (eight steps), **VERIFIED** on the claim |
| 27 | Stories excluded from coverage | spec §6:541-549 | **VERIFIED** |
| 28 | `ui-` 33.0, `app-` 67.6, total 280.7 | spec §8.2:652 | **STALE** — ~32.7 / ~71.6 / ~283.7 on the build on disk — F9 |
| 29 | `ui-` budget 56, does not move again; end state ~43.8 kB | spec §3.1a:285-298 | **VERIFIED** as written; the projection itself is UNVERIFIABLE without a harness run |
| 30 | `app-` limit 80, `total` 512 | spec §14.1 | **VERIFIED** — `check-size.mjs` |
| 31 | Proposal §6.5's `app-` 57 | proposal §6.5:808 | **WRONG**, already caught by spec §14.1 |
| 32 | `GraphCanvas` stays lazy, force-graph unpaid by a transcript reader | proposal §6.5:810 | **VERIFIED** — `graph.js` 60.9 kB, separate 1.3 kB wrapper |
| 33 | Tier-0 lists 11 primitives incl. `Dialog`, `Disclosure`, `ToggleGroup`, `VisuallyHidden` | spec §9:689-699 | **STALE** — five Radix packages installed; corrected in §3.1a — F12 |
| 34 | `presentation/common/` has 4 components and 0 tests | spec §10:756 | **STALE** — 12 modules, 8 jsdom test files, 3 browser tests, 7 story files. The spec's "the four files every phase touches first are the four with the least coverage" is retired |
| 35 | Layout tokens `--rail-w`, `--bp-*`, three `--z-*` | foundations §3.3:737-743 | **VERIFIED** — `tokens.css:147, 154-156, 219-221` |
| 36 | The deletion discipline should become `scripts/check-deleted.mjs` | foundations §4.4 | **VERIFIED as delivered** — 33 rules, in the chain |
| 37 | Preflight is deliberately not imported | `theme.css:26` | **VERIFIED** — and F7 lists what that still leaves open |
| 38 | `md:` and friends generate nothing until breakpoints are declared | `check-tailwind.mjs:30-33`; `theme.css:49-54` | **VERIFIED** — and zero uses in `presentation/`, so latent not live |
| 39 | Two phase numbering schemes coexist unreconciled | `check-deleted.mjs`; task list | **VERIFIED** — F11 |

---

## What I could not check without running anything

1. **Whether the browser suite is green today.** Everything in F1 rests on
   `shell-reached-dressing.browser.test.tsx:157-158` passing. It is outside
   `verify` and outside CI, so nothing has forced it to run since it was written.
   `npm run test:browser` settles F1 completely.
2. **Whether a directional-width-only border visibly draws.** Same run. Five lines
   in `src/styles/` would make it a standing proof rather than an inference from
   the built CSS. Until then F1 is: the built stylesheet says one thing and a
   Storybook observation reportedly said another, and only one of the two has been
   re-taken.
3. **The clipped focus ring on `.topic-list` and `.extraction-merge-list`.** Never
   measured. `npm run test:browser` with a case following
   `FileList.browser.test.tsx`.
4. **Real bundle numbers.** `npm run build && npm run size`. The `app.js` on disk
   is 22 minutes newer than every sibling, so F9's figures could be a partial
   rebuild.
5. **Whether `check-tailwind.mjs` and `check-deleted.mjs` pass at `9fa6c7b`.** I
   read both and reproduced the stylesheet-manifest comparison by hand (22 = 22,
   no additions, no removals), but I did not execute the 33 `RULES` regexes over
   the tree. `npm run deleted && npm run check:tailwind`.
6. **Whether a global `ul, ol` reset regresses authored markdown lists.** F7's
   recommendation needs a Storybook look at `markdown.css`'s `.md-list` before it
   is safe to write.
7. **Whether the Tailwind full-coverage estimate (8–12 kB) still holds** now that
   the source CSS is 193.5 kB. Nothing in F2 re-derives it; the estimate was never
   more than an estimate and the correction only changes what it is compared
   against.
