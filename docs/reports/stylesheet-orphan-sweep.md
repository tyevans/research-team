# Stylesheet orphan sweep

What this looked for: a rule in a *view-scoped* stylesheet whose selector is
written by a component that **outlives the view** — so deleting the stylesheet
with its screen silently unstyles something on a route that survives. jsdom
cannot see it, no test fails, no console error.

Method was the inversion the brief asked for: enumerate the outliving
components, collect every class name they write (literal and composed), then
resolve each name to the stylesheet that defines it. A second pass swept the
other direction for element/attribute-rooted selectors in view stylesheets.

Every `file:line` below was opened. Where something is inferred rather than
read, it says so.

**Correction, added after the fact: this was read against a branch twelve
commits behind `origin/main`, so every line number below is stale.** The
findings themselves were re-checked at `29ad8d7` and all four of the
shell-reached ones survive; what moved is where they sit. Current locations:
`.drawer*` at `course.css:582,598,607,613,628,640`; `.chip` base at
`tree.css:359`; the severity tones at `course.css:339-357`; `.btn-quiet` at
`composer.css:109,114`; `.autonomy-warn`/`.autonomy-error` at
`course.css:744,753`.

The stale base is worth recording rather than quietly fixing, because it is
what the sweep was reading when it reported `tree.css` as the home of the
`.project*` rules: those were deleted on `main` in `09f0a97` when the landing
page moved onto `ProjectCard`. A report whose line numbers are all wrong by a
uniform offset still reads as authoritative, and nothing in its own text can
tell you otherwise — which is the argument for stamping the commit a document
was read at, not just the date.

## The outliving set (confirmed by reading, not assumed)

`app/App.tsx:66-116` renders, on every route: the `brand` anchor, `Breadcrumbs`,
`AgentWidget`, `DriftBadge`, `ConnectionBadge`, `Toasts`, `DecisionBar`, all
inside `Shell`. `DecisionBar` (`presentation/shell/DecisionBar.tsx:28-60`)
renders `Approvals`, `AutonomyAllowAll` and — via `Approvals` — `GateReview`.
`AgentWidget` renders `Tooltip`, `Popover` and `WorkerDrawer`
(`presentation/agents/AgentWidget.tsx:8-10,185`), and `WorkerDrawer` renders
`Drawer` (`presentation/course/WorkerDrawer.tsx:13,88`).

So the transitive shell set includes two components filed under `course/` —
`AutonomyAllowAll` and `WorkerDrawer` — and one under `session/` —
`GateReview`. That is where every finding below lives.

Plus the shared primitives in `presentation/common/` and the layout primitives
in `presentation/layout/`, which outlive any single view by construction.

## Stylesheets I judged SHARED (not view-scoped) and why

Not findings, because nothing deletes these with a screen:

- `tokens.css`, `theme.css`, `base.css` — named as shared layers by the brief.
- `shell.css` — the chrome itself (`.brand`, `.crumbs`, `.conn`, `.drift`) plus
  `.btn` and its tones at `shell.css:180-270`. Dies only when the shell does.
- `states.css` — `.empty`/`.error-box` at `:4-30` and `.toasts`/`.toast` at
  `:35-102`. Its own header comment calls it "Empty states, error boxes and
  toasts"; all three are cross-view.
- `layout.css` — the `lay-` primitive layer.
- `structure.css` — its header (`:1-7`) states it is the additions that pay for
  rendering the design as components; explicitly cross-cutting.
- `responsive.css` — breakpoints over every view, including `.drawer` at `:148`.
- `markdown.css` — dresses `Markdown` (`common/content.tsx:22,27`), used by four
  views.
- `agents.css` — nominally a "view" name, but `AgentWidget` *is* shell chrome
  (`App.tsx:99`). It is effectively a shell stylesheet and is not in any route
  merge's deletion path.
- `index.css` — imports only.

View-scoped, and therefore deletable with a screen: `course.css`,
`research.css`, `conversation.css`, `timeline.css`, `composer.css`,
`scrub-bar.css`, `workspace.css`, `diff.css`, `tree.css`, `entity.css`,
`components.css`.

## Findings, ranked by blast radius

### 1. `.drawer`, `.drawer-head`, `.drawer-title`, `.drawer-spacer`, `.drawer-body`, `.drawer-body.is-flush` — course.css:570-630

Written literally by `presentation/common/Drawer.tsx:133-143`.

`Drawer` is a common primitive reached from the shell on every route:
`AgentWidget` (`App.tsx:99`) → `WorkerDrawer` (`AgentWidget.tsx:185`) → `Drawer`
(`WorkerDrawer.tsx:13,88`). It is also the base of `Confirm`
(`common/Confirm.tsx:2,35`), and of `TopicDetail`, `TopicStatusDialog`,
`DocumentList` and `Conversation`'s reader.

**Deleting course.css strips the drawer entirely**: the panel loses
`position: fixed`, its right-anchored 42vw box, its background, its border and
its flex column — so a drawer becomes unpositioned in-flow content with no
surface, and the body loses the 10px/12px/16px padding that
`course.css:605-627` was added specifically to fix (task #42). `research.css:352`
already records the coupling in a comment: "Reuses `.drawer`/`.drawer-backdrop`
from `course.css`". `responsive.css:148` narrows the same class.

**This is the largest finding in the sweep** — bigger than the two known ones,
because it takes out a modal contract rather than a colour.

### 2. `.chip` (base) — tree.css:379-386

Written by `common/primitives.tsx:35`, `` clsx('chip', tone && `chip-${tone}`) `` —
dynamically composed for the tone, literal for the base.

`GateReview.tsx:126` renders `<Chip tone={severity}>` from the decision bar on
every route. Seventeen other files render `Chip` (grepped; not each opened).

The known instance names the *tones* in course.css. The base rule — mono face,
`--t-xs`, padding, 3px radius, border, `--fg-dim`, `white-space: nowrap` — is in
**tree.css**, the landing view's stylesheet. If the route merge ever takes
tree.css, every chip in the console becomes unbordered, unpadded body text at
inherited size. The severity tones in course.css set only `color`/`border-color`/
`background`, so they do not rescue it.

### 3. `.autonomy-warn`, `.autonomy-error` — course.css:732-748

Written by `course/AutonomyAllowAll.tsx:113` and `:156`, literal, mixed with
Tailwind utilities on the same elements.

`AutonomyAllowAll` renders in the decision bar (`DecisionBar.tsx`, via `oldest`)
on every route. This is the *residue* of known instance #1: commit 248c6ec moved
the layout onto utilities but left these two. `course.css:645-652` and
`:719-731` both say so in comments — the second states outright that deleting
the file "unstyles the scope warning and the write error in the decision bar,
silently". Losing `.autonomy-warn` costs the 2px accent left border on the
instance-wide scope warning, which is the one thing that panel is shaped to make
unskippable.

Flagged even though it is documented: the brief listed two known instances and
this is a third live one.

### 4. `.btn-quiet` — composer.css:109-118

Written by `common/primitives.tsx:20` as `` `btn-${tone}` `` — **dynamically
composed**, which is why it does not grep as a literal from the primitive.

`AutonomyAllowAll.tsx:131` passes `tone="quiet"`, so it renders in the decision
bar on every route. Five other literal `btn btn-quiet` call sites exist
(`ResearchView.tsx:65`, `Composer.tsx:66`, `CourseView.tsx:62,66`,
`RunPanel.tsx:223`).

`ButtonTone` is declared in `primitives.tsx:10` with five values; four
(`accent`, `danger`, `ghost`, `sm`) are in shell.css, and `quiet` alone is in
**composer.css**, the session composer's stylesheet. Deleting composer.css turns
every quiet button into a default button — the cancel affordance stops reading as
subordinate to the primary action, which is exactly what the rule's comment
("never louder than the primary action") exists to guarantee.

### 5. `.tabs`, `.tab` — workspace.css:130-168

Written by `common/Tabs.tsx:78,86` and `common/Choices.tsx:66,95`, literal.

Both are Radix-backed shared primitives, but today the only consumer is
`session/FileView.tsx` — which lives in the workspace pane workspace.css dresses.
So the *current* blast radius is nil-to-low, and it is listed because the coupling
is latent: the next view to use `Tabs` or `Choices` inherits a dependency on the
workspace stylesheet, and `workspace.css:167-168` (`.tab[aria-selected='true'],
.tab[aria-checked='true']`) is the selected-state rule that the browser-mode
regression in CLAUDE.md was written about.

### 6. `.confirm p`, `.confirm-actions` — tree.css:481-490

Written by `common/Confirm.tsx:36,40`, literal.

`Confirm` is a shared primitive (`SessionView`, `ProjectList`, and anything
built on `Drawer`). Its two dressing rules — paragraph rhythm and the
right-aligned action row — sit in the landing view's stylesheet. Deleting
tree.css leaves confirm paragraphs with UA margins and the buttons left-aligned.
Not reached from the shell today, so ranked below the four above.

### 7. `.disc`, `.disc-head`, `.disc-caret`, `.disc-body` — conversation.css:162-192

Written by `common/primitives.tsx:98-111`, literal.

`Disclosure` is a shared primitive used by `Compaction`, `Timeline`, `Segments`
(session), `ExtractionPane` (course) and `ProjectList` (landing). Its base
dressing lives in the *conversation pane's* stylesheet. Deleting conversation.css
unstyles disclosures on the course page and the landing page — two screens that
survive it. Not shell-reached, so ranked here.

### 8. `pre.code` — workspace.css:174-190, with `pre.code .ln` at markdown.css:124

Written by `common/content.tsx:36,42,47`. Cross-stylesheet: markdown.css reaches
into a class workspace.css defines. Only consumer today is `FileView.tsx:213`,
so low radius — noted because the split is the kind that surprises whoever
deletes one of the two files.

### 9. `.diff`, `.dl`, `.sig`, `.skip`, `.add`/`.del`/`.ctx` — diff.css:37-70, `.diff > .diff-hunk` — structure.css:20

Written by `common/content.tsx:65-87`, with `` `dl ${row.op}` `` at `:79` —
**dynamically composed**. Only consumer is `FileHistory.tsx:129` (session). diff.css
is arguably a shared layer already; listed for completeness, no action implied.

## Reverse pass: element- and attribute-rooted selectors

Swept every view-scoped stylesheet for selectors not rooted on a class. The
complete set is nine, and all nine are anchored to a view-owned class, so none
can match shell markup:

`research.css:651` (`select.graph-entity-type`), `workspace.css:174,185`
(`pre.code`), `tree.css:343-367` (`ul.tree` and descendants), `composer.css:62`
(`select.input`), `entity.css:135` (`a.ent-ref:hover .ent-ref-name`).

The `lay-` overrides in view stylesheets are all scoped by attribute —
`course.css:29-57` uses `.lay-split[data-split='course'] > …` throughout,
`research.css:97-132` uses `.research-workbench`/`.research-rail` ancestors,
`responsive.css:36-116` uses `[data-split='session'|'course']`. None is a bare
`.lay-pane`, so none leaks onto a primitive outside its view. **Clean.**

## Stylesheets checked and found CLEAN

No rule in these is written by a component that outlives their screen:

- **timeline.css** — nothing in the outliving set writes a `timeline-`/`tl-` name.
- **scrub-bar.css** — same; `ScrubBar` is session-only.
- **entity.css** — `ent-` prefixed throughout; no shell component writes one.
- **components.css** — its chip tones (`:562-578`: `.chip-run-done`,
  `.chip-run-short`, `.chip-run-bad`, `.chip-readonly`) are written by
  `ProjectActivity`/`ProjectList`, not by anything shell-rendered. The `.chip`
  base they modify is finding 2's problem, not this file's.
- **research.css** — its only cross-view reach is the *comment* at `:352` noting
  it borrows `.drawer` from course.css; it defines nothing the shell writes.
- **markdown.css**, **diff.css**, **structure.css**, **responsive.css**,
  **states.css**, **shell.css**, **layout.css**, **agents.css** — judged shared
  above; not deletion candidates.

That leaves **course.css, tree.css, composer.css, conversation.css and
workspace.css** as the five carrying couplings, and course.css carrying three of
the four highest-radius ones.

## What I could not determine

- Whether the route merge's `QUEUE`/`HOLDER`/`MATERIAL` screens keep any of the
  five. I read the class graph, not `docs/increment-c-plan.md`, so I cannot say
  which findings are imminent versus latent.
- `.sub` — written by `AutonomyAllowAll.tsx:80,106,142` alongside utilities. It
  resolves to **nothing**: the only definition in `src/styles/` is
  `tree.css:53` `.view-head .sub`, which needs a `.view-head` ancestor the
  decision bar does not provide. So it is already dead rather than at risk. It is
  not a deletion hazard, but it is an orphan in the other direction and somebody
  should decide whether the styling was meant to apply.
- I did not run either test suite, and no assertion anywhere covers these
  couplings — which is the whole reason the hazard is silent. Confirming any
  finding visually needs `npm run test:browser` or a real browser, not jsdom.

## Verification

Every stylesheet line range and every component `file:line` cited above was read
in this session. The two claims I did **not** open both sides of, and say so:
the seventeen non-shell `Chip` call sites in finding 2 (grepped by filename
only), and the five non-shell `btn-quiet` call sites in finding 4 (grepped with
line numbers, not opened). Both sides of every finding's *defining* rule and
*shell-reached* writer were opened.
