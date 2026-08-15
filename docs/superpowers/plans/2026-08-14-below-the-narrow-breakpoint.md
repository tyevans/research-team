# Below the narrow breakpoint

2026-08-14, branch `narrow-band` off `origin/main` 801a5ae. The slice that
closes `BACKLOG.md` B57's remaining half and B60.

## 0. Why this, and what it is not

The slice that merged as #186 measured two of the page's three responsive
bands and found a shipped defect in each. It closed B57 **saying openly that
the third band was not measured**. This is that band.

Paired with it: **B60**, the session view's both-flanks-collapsed bug. The fix
already exists one block away in `responsive.css` — the project block got it —
so this is a port with a known shape and a red proof already on record, not new
design.

**A scoping judgement, made up front so nobody spends the slice on it.** This
console has one user on one machine (`vite.config.ts` says so where it explains
running one browser rather than three). **Phone widths are not the target.** The
band worth the effort is roughly **561–820px** — a small laptop or a tablet, a
window someone would actually put this in. Below that, *measure and record
rather than fix*, unless what you find is cheap. A slice that spends itself
making a research console work at 320px has optimised the wrong thing.

## 1. What the survey established, so no task re-derives it

**Below 821 the split stops being a grid.** `layout.css:144-159` makes
`.lay-split` a flex column and caps `.lay-pane-body` at 60vh. So
`PROJECT_TRACKS`' floors — the 344/342/352 the last slice measured — **guarantee
nothing here**: they are inert twice over, once because `splitTemplate` returns
`undefined` below `--bp-wide` and again because the element is not a grid. Each
pane gets the full viewport width.

**Every `:has()` collapse rule is out of scope by media query.** Both
`responsive.css` blocks are `(width >= 821px)`. Below that, collapse is the
*strip* form: `layout.css:278-284` is the whole rule set — `flex: 0 0 auto`,
title level and unrotated, meta and actions retained, body hidden by the
`hidden` attribute rather than by CSS. **This is the one collapse form the last
slice never exercised.**

**No test anywhere renders real layout below 821.** The browser suite's floor is
821 and it is reached from inside the band. `breakpoints.test.tsx` resizes to
375 but in jsdom, which lays nothing out — it asserts attributes only.

## 2. The two traps in the existing helpers, which will cost an hour each

**`widen()` is a silent no-op below 1181.** `project-responsive.browser.test.tsx:158`
polls on `split().style.gridTemplateColumns === ''`. That is already true at
1000px, so a 1000 → 700 resize resolves on the first tick **without waiting for
`matchMedia` to flip, for `stacked` to become true, or for React to commit**. It
only works crossing `--bp-wide`, and only because the `afterEach` leaves the
viewport at 1440. Do not reuse it.

Poll instead on something React writes *at this* boundary:
`pane('queue').getAttribute('data-collapse-to')`, which `Pane.tsx:126` flips
between `'rail'` and `'strip'` off the same `useWide('narrow')` subscription.
Geometry polling (as `project-tracks.browser.test.tsx:240` does) waits on the
browser rather than on React and will not catch a stale attribute — use it as
well if you like, not instead.

**`columns()` lies below 821.** The split is `display: flex`, so
`gridTemplateColumns` computes to `none`, and `'none'.split(' ')` has length 1 —
**indistinguishable from the single-column defect the existing claims measure.**
Assert on `flexDirection` and on stacked geometry (panes share a `left`, `top`
increases) instead.

## 3. Tasks

**A and B both use the browser suite, so they run one at a time, A first.**
CLAUDE.md: never two vitest processes. C touches no test and may overlap either.

### Task A — the stacked band (owns `layout.css`, one new test file)

1. **Measure `ProjectView` below 821 before changing anything.** New file
   `project-stacked.browser.test.tsx`. Build your own resize helper per §2;
   `show()`, `box()`, `pane()`, the nine-port fixture and the `afterEach` in
   `project-responsive.browser.test.tsx` port unchanged and are worth copying.
2. **The candidate defect, to confirm or refute — do not assume it.**
   `layout.css:155` caps `.lay-pane-body { max-height: 60vh }` **unqualified**,
   where the page-mode rule at `:99` deliberately writes
   `:not([data-scroll='regions'])`. HOLDER and MATERIAL both pass
   `scroll="regions"` (`ProjectView.tsx:359`, `:445`), whose body is
   `overflow: hidden`. **A 60vh cap on a box that cannot scroll clips content
   with no way to reach it** — unless the inner regions each shrink and scroll,
   which is exactly what has to be measured. QUEUE is `scroll='body'`
   (`overflow: auto`) and should be fine; the contrast between the three panes
   is the measurement.
3. **The strip form, which nothing has ever exercised in a browser.** Fold each
   pane below 821 and check the strip is what `layout.css:279-281` claims: a
   row of natural height, title level, body gone. In particular check a folded
   pane does not still reserve the 60vh, and that folding all-but-one still
   leaves a usable page.
4. **Where does it actually break?** Sweep down and find the width at which
   something paints outside a box that clips it, using the last slice's
   definition (`scrollWidth > clientWidth`, no scroller, no ellipsis). The
   survey predicts MATERIAL's five-tab strip — 351px, `.tabs` has no
   `flex-wrap` (`workspace.css:130-133`) — clips at roughly **351px of
   viewport**, which is a phone and *not* `--bp-tight`. **Report the number.
   Fix it only if the fix is cheap and contained** (a `flex-wrap` or a scroller
   on `.tabs` would be; restructuring the tab strip would not). Per §0, record
   over repair below ~560.
5. Prove every test red. Where a claim passes against unfixed code, say so in
   its docstring.

**Out of scope:** `responsive.css` entirely (task B owns it this slice),
`PROJECT_TRACKS`, the session view, `Pane`'s rotated-title wart.

### Task B — B60 and the session's own bottom edge (owns `responsive.css`)

Runs after A reports.

1. **Port the combined rule.** `responsive.css:40-45` needs the
   `:has([data-pane='timeline'].is-collapsed):has([data-pane='workspace'].is-collapsed)`
   rule giving both tracks `var(--rail-w)`, placed after the two single rules
   so it wins on source order — exactly as the project block at `:158-162`
   does. Read `BACKLOG.md` B60 and `docs/reports/measured-task-a.md`'s fix
   round 1 for the shape and the red proof.
2. **Update the project block's comment.** It currently says the session block
   "has this bug … and is deliberately left with it", and that whoever merges
   them "owes the session view this rule". After your change that is false.
   Say what is now true: the two blocks differ only in their floors.
3. **The session's bottom edge is unmeasured, and this is the finding to take
   seriously.** `responsive.css:41` writes `minmax(300px, …)` for `workspace`
   while `SESSION_TRACKS` declares its floor as **320**
   (`use-session-panes.ts:23`) — the CSS floor is *below* the declared one, with
   no justification written down and no test at 821. The project block has both
   (its 344 is measured, and `project-responsive.browser.test.tsx:360` asserts
   it). **Measure the session view at 821 the way the project view was**, and
   either justify the 300 or raise it. A test at the bottom edge either way.
4. **Two dead things, cheap while you are in the file.**
   `responsive.css:208-211` styles `.view-head`, and **no element carries that
   class** — `QueueHeader.tsx:84` records the commit that deleted the last
   inbound link. The family's definitions in `tree.css:39,47,53` are dead with
   it. Delete what is genuinely dead; **check `check-deleted.mjs` first**, since
   it freezes 21 stylesheets and holds 35 deletion rules, and confirm nothing
   else selects it. If deletion turns out to be more than a few lines, file it
   instead and say why.

**Out of scope:** `layout.css` and task A's file; the below-821 band, where
these rules do not apply at all.

### Task C — the record (owns `BACKLOG.md` and `docs/`)

May run in parallel. Items 1-2 now; item 3 needs A and B.

1. **Two comments that outlived their rules.** `components.css:582-591` says the
   course grid's third declaration "is now one rule in `responsive.css`, at
   `--bp-narrow`" — **no such rule exists**; the course view was deleted.
   `layout.css:109-113` explains the 1180/1181 spelling and sits above the
   **821** media query, having been copy-pasted from the wide-band rule. Correct
   both in place, in the house convention. **Verify each before editing** — a
   previous slice sent an agent to re-mark a correction already made.
2. **One thing to measure rather than assert.** `Drawer.tsx:164` sets width
   three ways in Tailwind utilities (`w-[42vw] max-w-[640px] min-w-[360px]`)
   while `responsive.css:217-221` sets `width: 100%; max-width: none;
   min-width: 0` below 820. Equal specificity, so source order decides, and the
   survey did not verify it. **Do not claim a defect.** File it as a question
   with the two candidate outcomes, noting that jsdom cannot answer it.
3. Close **B57** (all three bands now measured — say what was fixed and what was
   only recorded) and **B60**. Update `increment-c-plan.md` §8's residue list.

## 4. Verification

All four gates, and `npm run test:browser` is not optional — the whole slice is
measurement. Serially. Never two vitest processes.
