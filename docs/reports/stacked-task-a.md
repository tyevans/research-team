# Task A — the stacked band, below 821px

2026-08-14, branch `narrow-band`. Scope: §3 task A of
`docs/superpowers/plans/2026-08-14-below-the-narrow-breakpoint.md`.

Files touched: `frontend/src/styles/layout.css` (one declaration, three
comments) and the new `frontend/src/presentation/project/project-stacked.browser.test.tsx`
(7 claims).

---

## 1. What the band measured as, before any change

Measured in headless Chromium at 700x900 with `ProjectView` mounted inside a
real `Shell scroll="auto"`, which is how the app mounts it.

| | pane height | body | body content |
|---|---|---|---|
| QUEUE (`scroll='body'`) | 439.0 | 400.5, `overflow: auto` | 590 |
| HOLDER (`scroll='regions'`) | 304.6 | 266.1, `overflow: hidden` | 266 |
| MATERIAL (`scroll='regions'`) | 112.3 | 73.8, `overflow: hidden` | 74 |

The split was a flex column, panes shared `left: 0`, each took the full
viewport width, and `top` increased — the arrangement is what §1 of the plan
said it was. `columns()` from the sibling file was not used, per §2: below 821
`gridTemplateColumns` computes to `none` and `'none'.split(' ')` has length 1,
which is indistinguishable from the single-column defect that file measures.

**The number that mattered was the surface: `scrollHeight` 856, `clientHeight`
856 — flat, at every width from 820 down to 375.** The three pane heights sum
to exactly 856 because the split was pinned to the surface and every pane
shrank below its content so the set would fit one screen. So:

- `.lay-shell[data-scroll='auto'] .lay-surface { overflow: auto }` (layout.css,
  in the 821 media query) had nothing to scroll and never had.
- The `max-height: 60vh` cap beside it was **inert with all three panes open** —
  no body could reach 540px, because the layout never let one grow.

This is the same defect `layout.css` already records for `page` mode fifty
lines above ("the innermost scroller absorbs the content and the surface never
has anything to scroll"), which was fixed there with
`.lay-shell[data-scroll='page'] .lay-split { flex: 0 0 auto }`. The below-narrow
half of `auto` was given the `overflow` and not the release.

**The fixture had to be changed to see this**, and that is worth recording: the
two sibling browser files wrap `ProjectView` in a bare 900px flex column, which
reproduces the pinned height by accident and leaves no `.lay-surface` to ask.
This file mounts a real `Shell`. It also uses `height: 100vh` on the wrapper
rather than `900px` — a fixed pixel height detaches the shell from the viewport
that `60vh` is measured against, and the 700x500 probe reported a 300px cap
inside an 856px shell that had not moved.

## 2. The 60vh question, answered

**The candidate defect is refuted.** `layout.css` caps `.lay-pane-body` at 60vh
unqualified, where the `page`-mode rule writes `:not([data-scroll='regions'])`,
and a cap on an `overflow: hidden` box would clip with no way to reach what it
cut. It does not clip, and the reason is measurable rather than lucky.

Measured at 700x900 with HOLDER the only open pane, so the cap has something to
bind on:

```
holder body:  362.9  (cap 540, overflow hidden, scrollHeight == clientHeight)
  Event log section     110.5   scroller [data-holder-scroll=log]  87.8 / 88
  Conversation section  109.5   scroller .conv-scroll              87.8 / 88
  composer   y=388..440, on screen, outside both scrollers
```

Every region inside a `regions` body is `flex: 1 1 0%; min-height: 0` with a
scroller of its own, so a capped body hands the shortfall down and each region
scrolls what it cannot show. Nothing is clipped and nothing is unreachable.

**QUEUE is the pane the cap actually binds on, and it is the one that can take
it** — `scroll='body'`, `overflow: auto`. Opened alone at 700x900 its body is
exactly 540.0 around 590 of content, scrollable. At 700x500 the cap computed to
300px and the body to 300.0, so the unit resolves against the viewport
correctly.

So the `:not()` qualifier is **not** wanted: adding it would be a change
justified by nothing measured. The condition that would break this is a
`regions` pane whose regions do not each shrink and scroll — no selector can
state that, so it is stated in the stylesheet comment and pinned by claims 3
and 4.

## 3. The strip form

Nothing had exercised it in a browser. `layout.css`'s strip rules are three
declarations and a comment; the band had no rendered test at all. Measured at
700x900 with QUEUE folded:

- `flex: 0 0 auto`, `overflow: hidden`, height **38.5px** — exactly the header,
  against a 540px cap. **A folded pane does not reserve 60vh.**
- Header `flex-direction: row`, title `writing-mode: horizontal-tb` — level,
  not rotated. The rail form's rotation does not leak in.
- Meta retained (`display: block`). Actions are absent on QUEUE because it
  declares none, not because a rule hides them.
- Body gone by the `hidden` attribute (`hidden === true`, height 0), not by CSS.

Everything the comment claims is true.

**Folding all but one leaves a usable page**, and the third fold is refused —
`toggleCollapsed` (`split-tracks.ts:98`) declines when every pane would close,
and that holds below 821 where it matters more, since three 38px strips would
be a page with no content that still looks like a layout. With QUEUE and
MATERIAL folded, HOLDER keeps 401.4px and both its regions keep their scrollers.

One consequence of the fix worth naming: with two panes folded the split is
478.4px in an 856px surface, so there is blank surface below it. That is
correct page-scroll behaviour — a short page is short — where before the fix
the same fold left the panes squeezed *and* the surface flat.

## 4. Where it actually breaks

Sweep definition is the previous slice's: `scrollWidth > clientWidth`, with
`overflow-x: visible` (no scroller to reach the remainder) and no
`text-overflow: ellipsis` (nothing saying it was cut). Swept 820 → 320 and then
bisected.

**Nothing clips anywhere from 820 down to 351.** The first two failures, both
well below the ~561 floor §0 sets as worth effort:

| what | needs | box | clips from |
|---|---|---|---|
| MATERIAL's five-tab strip (`.tabs`) | 351px | the viewport | **350px** |
| QUEUE's seeding form | 317px | viewport − 27px padding | **343px** |

The tab strip fits exactly at 351 and overflows by 1px at 350 — the survey
predicted 351 and was right. The seeding form's 343 is `PROJECT_TRACKS`'
measured 344 floor showing up again, as a viewport width this time rather than
a track width.

**Both recorded, neither fixed.** Per §0 these are phone widths and this
console has one user on one machine. The tab-strip fix is not as contained as
it looks either: `.tabs` is the class on both `Choices` and `TabList`
(`Choices.tsx:66`, `Tabs.tsx:78`), used across the console, so `flex-wrap: wrap`
there changes every tab row at every width — cheap to type, not cheap to
justify from one measurement in one view. If it is ever wanted, that one
declaration in `workspace.css:130-133` is the whole change.

## 5. What was changed

One declaration in `layout.css`, inside the existing `@media not all and
(min-width: 821px)` block:

```css
.lay-split {
  display: flex;
  flex-direction: column;
  flex: 0 0 auto;   /* new */
}
```

After, at 700x900: surface **1128 / 856** (it scrolls), panes **578.5 / 401.4 /
148.0**, QUEUE's body at exactly its 540 cap and scrolling internally beyond
it. Every pane now gets its content's height, bounded by the cap — which is
what every comment in the file already said this mode did.

Three comments were also corrected or added, because two of them had become
false:

1. The `page`-mode paragraph said `auto` below narrow was "not extended" this
   block. Half of it now is. Rewritten to say what still differs — `page` stops
   a non-`regions` body being a scroll container, `auto` keeps it scrolling
   under the cap — which is the half that makes them modes rather than
   spellings.
2. The new `flex: 0 0 auto` carries the before/after measurement and names the
   test that fails without it.
3. The cap's comment now records *why* it is unqualified, with the numbers from
   §2 above and the condition under which it would stop being safe.

## 6. Red proofs, with output

| claim | mutation | failure |
|---|---|---|
| 2 — the surface scrolls | `flex: 0 0 auto` removed | `AssertionError: expected 856 to be greater than 856` |
| 3 — 60vh cap | cap changed to `40vh` | `AssertionError: expected '360px' to be '540px' // Object.is equality` |
| 7 — nothing clips to 561 | sweep run at 350 instead | `AssertionError: at 350px: expected [ Array(2) ] to have a length of +0 but got 2` (the two being `.tabs` and the column around it, 351 against 350) |

**Claims 1, 4, 5 and 6 pass against unfixed code, and each says so in its own
docstring** per the house convention. They are records rather than guards:
claim 1 is the band's baseline, which was unwritten; claim 4 pins the
refutation in §2 so it is not re-derived; claim 5 is the first browser coverage
the strip form has ever had; claim 6 pins a reducer refusal that is
breakpoint-independent but looks plausible as a bug in this form.

Notably, claims 3 and 4 stayed green with the `flex: 0 0 auto` removed — the
cap claims are about the cap and not about the release, which is the separation
intended.

## 7. Verification run

- `project-stacked.browser.test.tsx` alone — 7 passed.
- `npm run test:browser` — **23 files / 77 tests passed**, against the 22/70
  baseline. No regression; the 7 are mine.
- `npm test` (jsdom, `app` + `build` projects) — 104 files / 1038 tests passed.
  `breakpoints.test.tsx` is in `src/presentation/layout/` and is included.
- `npx tsc --noEmit` — clean.
- `npx eslint` on the new test file — clean (it does not lint `.css`).
- `npx prettier --check` on both files — clean.

Never two vitest processes at once. Not run, per the brief: `npm run verify`
and the Python gates.

## 8. Left undone

- **`.tabs` at 350px and the seeding form at 343px are recorded, not fixed** —
  §4 above has the numbers and the one-line change if anyone wants it.
- **The blank surface below a folded stack** (§3) is now honest page-scroll
  behaviour rather than a squeeze, and is left as is. Making open panes grow to
  fill the surface would contradict the 60vh cap, which exists to stop exactly
  that; the two cannot both be satisfied and the cap is the one with a written
  reason.
- **Only the project view was measured.** The `layout.css` change is on the
  `.lay-split` primitive, so it applies to the session and research views below
  821 as well. The whole browser suite is green, but no test in it renders those
  two views below 821 — the change is unmeasured there rather than measured and
  fine. Task B owns the session view's responsive block and may want to look.
- **`layout.css:109-117`** (the 1180/1181 comment above the 821 query) was
  already corrected in this worktree by task C before I started; it is in the
  diff and is not mine.
