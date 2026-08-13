# Two foundations, and the slices that stand on them

A design for the layer underneath this console's presentation code: one contract
for showing a domain entity, one system for arranging regions on a screen, and a
rollout that finishes a surface at a time instead of a primitive at a time.

This is a companion to `docs/component-system-spec.md` and is meant to replace
its §9 inventory and its §11 rollout. It does not revisit the toolchain
decision — Radix, Tailwind v4, CVA and `eslint-plugin-jsx-a11y` are settled and
in flight, and everything below assumes they exist.

---

## 0. What I verified, and what I took from the reports

The standard here is that a document says which of its facts it checked.

**Read in source, by me, out of a clean worktree at `origin/main` = `b7388db`.**
`styles/tokens.css` in full; `styles/panes.css`, `styles/responsive.css`,
`styles/structure.css` in full; the layout half of `styles/research.css`;
`styles/agents.css` head; `app/App.tsx`; `presentation/common/Drawer.tsx` and
`primitives.tsx`; `presentation/session/use-panes.ts`;
`presentation/agents/AgentWidget.tsx`; and the row and detail markup in
`presentation/research/TopicList.tsx` and `TopicStatusDialog.tsx`. By grep
across `frontend/src`: every `z-index`, every `position: fixed|absolute`, every
occurrence of `34px`, `1180`, `1181`, `820`, `560` and `.replace('_', ' ')`, and
the import lists of five representative entity components.

**Verified by git, cheaply, and worth stating because two other documents rest
on it.** `git log 5a5a7cf..HEAD -- frontend/` is **empty** — zero frontend
commits since the four feature indexes were written. Their UI claims are
current, and so are `component-system-spec.md`'s, read two commits later at
`a010974`. The spec's per-directory test-file counts still match the tree.

**Taken from a survey of `research_team/domain/`, `application/` and
`interfaces/web/presenters.py`** for the wire shapes in §2.1, and from a survey
of `frontend/src` for the inventory figures in §1. Those are second-hand
readings by another pass over the same tree, marked *(surveyed)* where a claim
rests only on them. §2.1's table has since been re-verified against
`research_team/domain/` by the agent implementing Foundation 1 and found
correct — a turn and an artifact are not entities, and documents live in a
project-scoped `Corpus`. §2.7(a)'s premise was **not** correct and is corrected
in place there.

**Taken from the four reports**, attributed by id throughout, using the prefixes
`unified-ui-proposal.md` §4 established: **L-** landing, **R-** research, **C-**
course, **S-** session.

**Not verified, and not verifiable from here.** Nothing has been run. I did not
start the server, open a browser, or build one component. Every claim about how
a phase will *feel* is inference. Per `CLAUDE.md` the suite passing carries no
information about any of it, and `docs/design/landing-page.md` §8's two
disasters — a virtualizer that passed every test and left a 122px hole at three
projects, a read-model that passed every test and 500'd on the only database
anybody had — were both layout-and-data restructures found by a person using the
product.

### 0.1 One correction to the brief, up front

The brief I was given cites "the research view's topics and documents panes
stack too tightly to use" as a current symptom. **It is fixed on `main`, and has
been since #71 (`7e304e0`), which predates the four feature indexes.**
`styles/research.css:70-88` carries the fix and names the complaint in its own
comment:

> `min-height` is the fix for the complaint that both panes are too short to
> use: an even split of a laptop viewport across three regions left each list
> showing three or four rows, which is a scrollbar rather than a list. 240px is
> roughly seven document rows or five topic rows.

The rule is
`.research-rail > .pane-topics, .pane-documents { flex: 1 1 0; min-height: 240px; overflow: hidden }`,
with `.research-rail { overflow-y: auto }` above it so the rail scrolls rather
than squashing further.

The fix is real, and it is also the argument for a layout system rather than
against one: it is a one-off, in one stylesheet, expressed as a literal,
selected by two pane names, and nothing carries it to the session view's three
panes or to any pane built next. §3 makes it a parameter.

---

## 1. The duplication, found before anything is proposed

### 1.1 One entity, several unrelated markups

The brief's example was "a topic in the research rail, a topic in a dispatch
dialog and a topic in the graph". Two thirds of that is right; the third is not,
and the wrong third matters, because it is where the contract would have been
over-scoped.

*(checked — both files read.)* `TopicList.tsx:319` renders the question as
`<div className="topic-question">`. `TopicStatusDialog.tsx:140` renders the same
field as `<h3 className="drawer-title">` — the `Drawer` component's own heading
class, in a file that does not use `Drawer`. *(surveyed)* A third spelling
exists: `SubQuestions.tsx` renders a sub-question through
`.sub-question-text`. The two topic markups share **no class name at all**; the
only thing they share is `Button` from `common/primitives.tsx`.

The status is transformed by `topic.status.replace('_', ' ')` in **three
places** — `TopicList.tsx:321`, `TopicStatusDialog.tsx:149` and `:166`. A grep
of `frontend/src` finds those three and nothing else. So one domain vocabulary
rule — underscores are not shown to people — is written three times, in two
files, using a method that replaces only the first occurrence.

**There is no topic in the graph.** *(checked, and independently confirmed by
survey: `topic|Topic` in `GraphPane.tsx`, `GraphCanvas.tsx` and
`entity-colors.ts` returns nothing.)* A topic holds `entity_ids` pointing at
redstring entities; the graph renders a `GraphEntity` — `entity_id`, `name`,
`entity_type` — which is a different presentable. The real third and fourth
topic presentations are `SubQuestions` and `TopicDocuments`, both nested inside
the dialog.

*(surveyed)* One more, and it is the sharpest single instance in the codebase:
`TopicList.tsx:261-291` contains `DispatchChip`, a **fifth chip implementation**
with its own five status classes, which does not use the shared `Chip` in
`common/primitives.tsx`.

The reports find the same shape for every other entity:

| Entity | Distinct presentations | Reported inconsistency |
|---|---|---|
| Project | landing row, course header, research header, breadcrumb, dock row, scrub-bar chip | L-§11.1 "It implies a project is a row; every other page implies a project is a place." L-§11.2 "the landing page names projects and the session page cannot." |
| Session | landing row + fork forest, session page, `WorkerDrawer`, course worker roster, dock row | L-F42: the drawer's title from the dock is "a better name than the drawer's own `Watching 3f2a…`". L-§11.5: two views disagree about a session's ancestry "and both are 'right'." |
| Worker | landing row chip, dock row, course roster | C-D6 "Two worker rosters on one screen… neither references the other." L-F13 shows only the first worker; C-F5 shows the nested roster. |
| Document | corpus row, corpus reader, topic-output tab, session file row/viewer, course artifact link | R-§8.5: two different things "are both called **Documents** in the UI". R-F4.4: the audience is always `'author'` here, and the toggle exists on the other two mounts of the same renderer. |
| Artifact | per-stage list, flat all-artifacts list | C-G10: interactivity is a fact the row never carries and the viewer does. |
| Approval | session view, `WorkerDrawer`, course page | S-D19: the surface that asks most has no autonomy control. |

Two counter-examples, which are the pattern I am generalising rather than
inventing. `AutonomyPanel` and `AutonomyAllowAll` share **one unparameterised
query key** (C-F38) and share their copy verbatim through `autonomy-copy.ts`
(C-F33), where "wording drift between the two surfaces is treated as a
correctness bug". And *(surveyed)* `tree/SessionRow.tsx` is reused by
`SessionForest`, by `ProjectList`'s row preview and by `SessionTree` — one
entity component, three call sites, no drift. Where this codebase built a single
source it held. `tokens.css` records the same thing about colour, including two
occasions where it caught drift.

### 1.2 The state coupling — and the part of it that is already solved

This is where I have to correct something I would otherwise have overclaimed.

*(surveyed, and spot-checked by me against the import lists.)* The row-level
components are **already prop-pure**. `TopicRow` (`TopicList.tsx:293`),
`DocumentRow` (`DocumentList.tsx:158`) and `AgentRow` (`AgentWidget.tsx:255`)
take their entity as a prop and reach for nothing. They are simply **not
exported**. `Artifact` (`Artifacts.tsx:17`), `Stage` (`StageRail.tsx:11`),
`SessionRow` and `Findings` are prop-pure *and* exported. `Timeline`,
`Conversation`, `Approvals`, `Composer`, `ScrubBar`, `FileList` and `Pane` are
prop-pure too.

The coupling lives one level up, uniformly, as
`const { x } = useContainer(); const q = useQuery({ queryKey: queryKeys.…, queryFn })`
in every list and pane component: `TopicList`, `DocumentList`, `TopicDocuments`,
`SeedPanel`, `GraphPane`, `ProjectList`, `TreeView`, `CourseView`, `RunPanel`,
`Workers`, `AgentWidget`, `ConnectionBadge`, and more.

Two exceptions worth naming because they are the real work:

- **`SubQuestionRow`** (`SubQuestions.tsx:96`) is the one row component that is
  not pure — `useContainer()` at :109 and `useMutation` at :113 sit inside the
  row.
- **`ProjectList.tsx`** is 542 lines and is the extreme case. `ProjectRow` at
  `:358-513` calls `useProjectActivity` at `:380`, so the card fetches. In one
  module the file imports `useQuery`, `useMutation`, `useQueryClient`,
  `useVirtualizer`, `useContainer`, `navigate`, `notify`, `useProjectActivity`
  and `useSessionForest`, and also contains the markup of a project.

**What this changes about the proposal.** The entity contract is much less of an
invention than it first looks. For most entities it is `export` plus a
directory move plus a name, and the design work is in the *density set*, the
*slot discipline* and the *vocabulary*, not in prising components apart.
`ProjectActivity.tsx` is already the target shape — it exports `ActivityChip`
beside `useProjectActivity`, a component next to a headless hook. The pattern
exists here once, and this document generalises it.

### 1.3 The layout code

*(all checked by me, by reading and by grep across `frontend/src`.)*

**Two pane systems sharing one class name.** `panes.css` defines `.pane`,
`.pane-head`, `.pane-body`, `.pane.collapsed`. `research.css` re-specifies the
same elements through `.research-workbench .pane` and `.research-rail > .pane`,
and introduces a second fold class because the first one's rules do not fit:

> Hence `is-folded` rather than reusing `collapsed`, whose rules would rotate
> the title.

Two fold semantics, two class names, one selector namespace. R-F1.1 records a
third difference: research folding **unmounts** the body so a virtualizer does
not measure a zero-height scroller, and research has **no** "at least one stays
open" rule, so "a user can reach a state where the rail shows no content at
all". S-F17 records that the session panes refuse exactly that.

**The same three tracks declared twice, with different numbers — and one of the
declarations is dead.** `panes.css:73` says
`minmax(300px, 1.05fr) minmax(320px, 1.5fr) minmax(300px, 1.15fr)`.
`use-panes.ts:67-74` emits `minmax(280px, 1.05fr)`, `minmax(320px, 1.5fr)`,
`minmax(280px, 1.05fr)`.

> **Corrected by a browser check.** An earlier draft said the stylesheet's
> values took over below 1181px, so that crossing the breakpoint silently
> changed two minima by 20px and a weight from 1.05 to 1.15. That is wrong, and
> wrong in the direction that flatters the finding. Above 1181px the inline
> style wins; at 1180px and below, `responsive.css`'s two-column rule replaces
> the template anyway; below 821px the container stops being a grid. **So
> `panes.css:73`'s three tracks have never applied to anything.** The live
> values are, and always were, 280/320/280 at 1.05/1.5/1.05. There was never a
> live disagreement — only dead code that reads like one. The claim was
> arithmetic over class names, which is exactly the kind this document's own
> §0 says it cannot check, and it took someone opening a browser to settle.

The finding that survives is smaller and still worth acting on: two
declarations of one thing, one of them dead, and nothing that would tell a
reader which. A reader tuning the layout by editing `panes.css` changes
nothing and has no way to find out why. That is the failure `tokens.css` was
written to prevent, in a dimension `tokens.css` does not cover — and it is a
reason to have one declaration rather than a reason to prefer either set of
numbers.

**Layout constants written in two or three places.** `34px` — the collapsed rail
— is at `use-panes.ts:17` and at `responsive.css:29` and `:32`. The three-column
boundary is `@media (max-width: 1180px)` in `responsive.css:6` and
`'(min-width: 1181px)'` in `use-panes.ts:23`: one boundary, two spellings, off
by one on purpose, in two languages, with no shared constant. `560px` is in
`responsive.css:136`, `tree.css:167` and `agents.css:250`, and the last uses
`@media (width <= 560px)` while the first uses `max-width`. `tokens.css` has no
breakpoint token, no width token and no z-index token; its only layout entries
are `--radius: 5px` and `--topbar-h: 44px`.

**Responsive behaviour is a patch file, not a property.** `responsive.css` is
146 lines reaching into `.panes`, `.pane-conversation`, `.view-research`,
`.research-workbench`, `.research-rail`, `.files`, `.actions`, `.view-head`,
`.drawer` and `ul.tree` by name. A fourth surface means more rules here.

**The `min-height: 0` hazard is genuinely absent, and that is worth recording.**
*(surveyed, and consistent with everything I read.)* `body` → `#root
{ display: contents }` → `#app` → `.view` → `.panes` / `.research-workbench` →
`.pane` → `.pane-body` carries `min-height: 0` at every level, several with
comments recording the bug that put it there. The existing layout code is
careful. Its problem is that the care is not reusable.

**Five overlay mechanisms, four z-index values, one stated rule, and the rule is
violated.** Every `z-index` in `frontend/src`:

| Value | Where | What |
|---|---|---|
| 1 | `research.css:621, 808, 920` | `.graph-command`, `.graph-detail`, `.graph-legend` — three peers over one canvas, ordered by DOM position |
| 2 | `workspace.css:52` | a sticky head |
| 20 | `course.css:524` | `.drawer-backdrop` — used by `Drawer`, by `Confirm` through it, and by `TopicStatusDialog`, which copies the classes without the component |
| 20 | `tree.css:437` | the row overflow menu, a `Disclosure` positioned absolutely |
| 40 | `agents.css:87` | the agent dock popover |
| 50 | `states.css:39` | toasts |

*(surveyed, and it is the most consequential single fact in this section)*
**nothing in `presentation/` or `app/` calls `createPortal`.** Every overlay
renders inline in the React tree and escapes only through `position:
fixed|absolute`. A portal-based overlay host is a net-new capability, not a
refactor of an existing one.

The one place an order is written down is `agents.css:85-86`:

> Above the page and its sticky headers (20), below the toasts (50), which must
> stay readable over it.

`AgentWidget.tsx:75-77` states the interaction half:

> Guarded on `watching` in both listeners: with a feed open the drawer is in
> front and owns Escape, and a click inside it is not a click on the page behind
> this popover.

*(checked.)* While `watching` is set, `expanded` is unchanged, so the popover
still renders (`AgentWidget.tsx:176-200`, with `WorkerDrawer` as its sibling at
`:203-209`). `.agents` is `position: relative` with no `z-index`, and `.topbar`
sets neither, so no stacking context is created between the popover and the
root. The popover is `position: fixed; z-index: 40`; the drawer backdrop is
`position: fixed; inset: 0; z-index: 20`, `aria-modal="true"`, with a focus
trap. **So the popover paints on top of the modal backdrop, is not covered by
it, is not `inert` or `aria-hidden`, and has switched off its own Escape and
outside-pointerdown handling because the code states the drawer is in front.**
I am describing what two files do; the comment describes one order and the
stylesheet produces the other.

Two further consequences of there being no scale. The drawer backdrop and the
row menu are both `20`; they happen not to collide today because one is fixed
and one is absolute inside a row, but nothing states or enforces that. And the
graph's three floating layers are all `1`, so the detail panel, the search
results and the legend are ordered by DOM position — R-F6.4 records "Picking a
result clears the term, which is what closes the floating panel so it stops
covering the drawing you just asked for", a dismissal rule standing in for an
absent stacking answer.

---

## 2. Foundation one: the entity presentation contract

### 2.1 The presentable set, which is not the aggregate set

The brief's hierarchy — `Project → Topic → Document`,
`Project → Session → Turn → Artifact` — holds in one link of four.
*(From the domain survey.)*

- **`Project → Session`: true, both ways.** `SessionStarted.project_id` is
  required; `ProjectState.member_session_ids` holds the reverse.
- **`Project → Topic`: true, by foreign id only.** `TopicOpened.project_id`.
  The project holds no topic list.
- **`Topic → Document`: false as containment.** Documents are `DocumentRecord`
  values embedded in a **`Corpus`**, project-scoped, sharing the project's UUID
  on a separate stream. A topic holds `source_ids: list[str]` pointing into that
  dict. Many-to-many, by string, across aggregates, unenforced.
- **`Session → Turn → Artifact`: false twice.** A turn is not an entity — it is
  `TurnCompleted`/`TurnFailed` on the session stream plus a `turn_index: int`
  counter. An artifact is not an entity either: `ArtifactSlot` is an
  application-layer join of a preset's declared output path against
  `SessionState.files`. **Nothing links an artifact to the turn that wrote it**,
  which is R-§8.6 — "the dispatch that wrote a document, and the session that
  ran it, cannot be joined" — seen from the domain side. That is a domain gap,
  and §2.7(e) declines to paper over it.
- **`Course` is a read-model join** of `Preset` × `ProjectState` × the holding
  session's `files`, computed per request and never persisted. **`module` and
  `lesson` are not domain concepts at all**; `lesson` is a frontend interface
  built from `GET /api/sessions/{id}/files/parsed`.

A contract keyed on aggregates would present four things that do not exist and
miss most of what the console draws. **The contract is keyed on what crosses the
wire**, which `interfaces/web/presenters.py` already defines as pure functions:

| Presentable | Wire view | Note |
|---|---|---|
| Project | `project_view` | `{id, name, active_session_id, tip_at_event, workflow, stage}` |
| Session | `summary_view` / `session_view` | already two densities on the wire |
| Event | `event_row` | the timeline's unit; `summary` is server-composed prose |
| Topic | `topic_view` / `topic_detail_view` | detail is a strict superset of the row |
| Source | `source_view` / `source_text_view` | superset again |
| ArtifactSlot | `artifact_slot_view` | frontmatter deliberately not sent |
| Stage | `stage_progress_view` | |
| Finding | `finding_view` | |
| Worker | `worker_view` | |
| GraphEntity / GraphRelationship | `entity_view` / `relationship_view` | |
| Run | `run_view` | |
| Dispatch | the `dispatch` SSE frame | the one presentable with no REST view |
| Approval | `approvalDto` | |
| LearnerItem | `item_view` | |

**Three of these already ship a row shape and a detail shape as separate
functions, with the detail a strict superset.** That is the strongest evidence
available that the density split below describes the system rather than imposes
on it.

One more property of the wire that the contract has to respect: *(from the
survey)* **every SSE frame carries an invalidation nudge, not an entity** —
`{type, id, change, occurred_at}`, with the presenters' comments saying so. An
entity component therefore never receives a frame. A hook re-reads. This is not
a rule I am adding; it is the shape the server already has.

### 2.2 The densities, argued

I was asked to argue the set rather than accept row / card / detail /
inline-reference. I arrive at those four, and the argument is mechanical rather
than aesthetic: **each density exists because its container makes a different
guarantee about height and about who owns the actions.**

**`Ref` — the entity named inside someone else's sentence or chrome.** One line,
no box, no actions, and it must degrade to an id when the name is not in hand.
That this is a real and currently inconsistent thing: `held by 3f2a…` on the
landing row (L-F12) against `not held` on the scrub bar (S-F12); the breadcrumb
naming a project by short id "deliberately, to avoid a request on every session
load" (S-F59) against the landing page naming it, which L-§11.2 calls losing the
user's vocabulary; the dock showing "project name (or short id while
`/api/projects` has not resolved)" (L-F41); `working_on` on the run panel; a
finding's `cites`; `forked @ 12`. Seven sites, one job, no shared component.

**`Row` — a uniform-height member of a scanned list.** Its defining property is
that **its height is a function of its kind, not of its content**, which is what
lets a virtualizer estimate it and what lets a column be read by scanning.
L-F8 is the evidence and it is expensive evidence: measurements cached against
an array index "followed the wrong row and left a **122px hole** at three
projects", and `scrollMargin` re-measured with no dependency array is "invisible
at three projects, draws the wrong rows at fifty".

**`Card` — a variable-height member of a list, carrying its own actions and
possibly a disclosure.** The distinction from `Row` is not decoration: a card
**must be measured**, and measuring is where the failures are.
`docs/design/landing-page.md` §8 records "rows are fixed-height, which is what
makes this cheap" ceasing to be true "the moment a row carried a disclosure",
and records the supersession — a card that expanded its sessions inline meant
"one project's history pushed every other project off the screen". Naming `Row`
and `Card` separately names a contract a virtualizer can rely on and one it
cannot.

**`Detail` — the sole occupant of a region.** It may scroll, it owns headings,
and it is the only density allowed to render fields no list shows. R-F3.10 is
what this is for: `rationale`, `scope`, `sourceIds`, `findingNotes` and
`contested` are all fetched by the dialog and **none is rendered anywhere in
`presentation/`** — the largest unrendered field set the research report found.

**The fifth I considered and rejected: `Chip` / `Badge`.** A chip presents a
*status*, not an entity, and all four densities use one. Making it a density
would mean `TopicChip` beside `SessionChip` beside a shared `Chip`, which is the
drift the contract is for — and `DispatchChip` (§1.1) is what that already looks
like. It is a shared sub-part (§2.5), not a density.

**The sixth I considered and rejected: `Tile` / grid cell.** No report asks for
one. A density with no call site is how an abstraction becomes a configuration
language.

**Densities are separate components, not a `density` prop.** `TopicRow`,
`TopicCard`, `TopicDetail`, `TopicRef` — four exports from
`presentation/entity/topic/`. Three reasons in order of weight: a `density` prop
makes the story matrix the product of densities and states rather than the sum;
the row's height guarantee cannot be typed if a prop can turn a row into a card;
and CVA variants are the right tool for *tone* and the wrong one for
*structure*, a distinction worth keeping visible now that CVA is arriving.

**Not every entity gets four.** The rule is: **implement a density when a second
call site needs it**, and the gallery is what shows you which exist. A `Finding`
has a row and a detail and will probably never have a card. A `GraphEntity` has
a ref and a detail. Building fifty-six components on day one would be building
most of them against no evidence.

### 2.3 The shape of the contract

```ts
/** Everything an entity component may receive. There is no fifth field, and in
 *  particular no callback that fetches, invalidates, or navigates. */
type Presentation<E, Slots = Record<string, never>> = {
  /** The wire shape for this density, whole. Never a subset assembled by the
   *  caller: a component taking `question` and `status` as two props cannot be
   *  handed a topic, and every call site re-derives the mapping. */
  entity: E
  /** Affordances, supplied by the view. Named slots rather than `children`, so
   *  a story can enumerate "row with dispatch" against "row with nothing", and
   *  a type error catches a row rendering a verb it was not given. */
  slots?: Partial<Slots>
  /** Navigation is a URL, never a handler. */
  href?: string
  selected?: boolean
}
```

Four rules follow, and each closes something the reports found.

**1. The component never fetches, subscribes, mutates, reads a store or a
context, or calls `navigate`.** State lives in a headless hook in the same
directory — `useTopic`, `useTopicStatus`, `useDispatchTopic` — following
`ProjectActivity.tsx`'s existing split. This is a standing constraint on the
whole project, not a preference for this design.

**2. `href`, never `onClick`, for navigation.** L-§9.3: "Nothing on the page is
a link. Every navigation is a `<button>` calling `navigate()`. No ⌘-click, no
middle-click, no copy-link, no status-bar preview." Making this a property of
the contract closes it once instead of at five call sites. It is a behaviour
change, and the improvement is the four capabilities that sentence lists, none
of which the console has today. Anything relying on a click handler firing
before navigation has to move into the hook.

**3. Affordances come from the view, as named slots.** `TopicRow` does not know
that dispatch exists; `TopicQueue` passes
`slots={{ primary: <DispatchButton/>, overflow: [...] }}`. This is what makes
one row usable in the research rail and in a merged queue that also holds stages
and sessions, and it is what lets R-F3.4's carefully-reasoned single disabled
control stay a property of the view that knows why it is disabled.

**4. Domain vocabulary in every name.** `TopicRow`, not `ListItem`;
`topic.openSubQuestions`, not `topic.count`. And one trap the wire already sets:
**`findings` is an `int` and `finding_notes` is a list of strings**, on the same
object, and `presenters.py` warns about it in a comment. A props contract
mapping both onto `findings` would be a bug that typechecks.

### 2.4 Where the props-only rule bites

The enforcement mechanism is the one `component-system-spec.md` §6 already
states: **a component gets a story if it can be rendered from props alone, and a
component that cannot get a story is telling you it is not a component yet.** On
today's code, honestly:

- **For most rows it does not bite at all** (§1.2). `TopicRow`, `DocumentRow`
  and `AgentRow` are already prop-pure and unexported; `Artifact`, `Stage`,
  `SessionRow`, `Findings`, `Timeline`, `ScrubBar`, `FileList` and `Composer`
  are prop-pure and exported. The first story for each is an `export` and a
  fixture. I would have claimed a larger refactor than the code requires; the
  survey corrected me, and the correction is the best evidence available that
  the contract describes something already latent here.
- **It bites on `SubQuestionRow`**, the one impure row: `useContainer()` and
  `useMutation` inside the row itself. Split into `SubQuestionRow` (props) plus
  `useResolveSubQuestion`.
- **It bites hardest on `ProjectList.tsx`**, 542 lines, where `ProjectRow`
  fetches its own activity. Splitting yields `ProjectCard` (props),
  `useProjects`, `useDeleteProject`, `useProjectForest`, and a `ProjectPicker`
  that owns the virtualizer. The three virtualizer facts L-F8 records —
  `getItemKey` by id, `scrollMargin` re-measured with no dependency array, every
  row measured — stay in the view, because they are properties of the *list*.
  This is the largest single refactor in the plan and the one that proves the
  contract: if it cannot survive the console's most entangled component it is
  not worth having.
- **It bites usefully on `TopicStatusDialog`**, which splits three ways:
  `TopicDetail` (props), `useTopicStatus` (the mutation and its mandatory
  justification), and Radix's `Dialog` — the hand-copied trap deleted. The split
  exposes something a comment currently hides: `TopicList.tsx:41` says the
  detail is fetched fresh because the dialog needs the rationale and scope, and
  the dialog renders neither (R-F3.10, "Comment vs code"). A story for
  `TopicDetail` against a full fixture makes that visible on a gallery page.
- **It bites where it should not, once: `GraphCanvas`.** It needs a
  `ResizeObserver`, a lazily-loaded canvas library and `getComputedStyle` to
  read the event-kind tokens (R-F6.2). It cannot be rendered from props alone in
  any useful sense. **That is correct, and the rule must say so**: it is not an
  entity component, it is a device, and it gets no story. The honest rule is
  *"every entity component gets a story"*, with devices and views explicitly
  outside it. A rule with an unstated exception is one people route around.
- **It bites in a way I have not resolved: `Dispatch`.** It is the one
  presentable with no REST view — it exists only as an SSE frame. Its five
  statuses and their glyph vocabulary (R-F3.5) are real presentation, and its
  props would be assembled by a client-side reducer over frames. It gets a
  component and a fixture; whether the fixture is honest is something I cannot
  check without running it.

### 2.5 Shared sub-parts, and one place for vocabulary

Three things every density uses, each replacing something written more than once
today:

- **`EntityStatus`** — the chip, fed by one `statusLabel(kind, status)` in
  `domain/`, which is where the three `replace('_', ' ')` calls go and where
  `DispatchChip`'s five bespoke classes go. The tone map is a CVA variant, so an
  unknown status is a type error rather than a missing stylesheet rule. It must
  carry the distinctions the reports single out intact: C-F46's `human_gate`
  reading "needs a person" rather than filing with the failures, and C-F26's
  rule that of six run endings **only `queue_empty` earns the `done` tone**.
- **`EntityRef`** — §2.2's `Ref` density, generically. `name ?? shortId(id)`, in
  `--mono` at `--t-xs` when it falls back, with the fallback visible rather than
  silent. This turns S-F59's reasoning — name it if you already know it, never
  fetch in order to name it — from a comment in one component into the behaviour
  of every reference in the console. It also removes a coupling I found in
  `App.tsx:53, 67`: the shell holds `course` state lifted out of `CourseView`
  through an `onCourse` callback, purely so the breadcrumb can name a project.
  A ref reading the same query cache does not need the page to hand it up.
- **`Provenance`** — the chips C-F61 defines (`inferred`, `N unreadable`,
  `claims nothing`), computed server-side "precisely so a client cannot rederive
  it wrongly". Presentation only; no client-side derivation, ever.

### 2.6 What this costs when it is wrong, and how to back out

**The failure mode is the slot record becoming a prop bag.** If `TopicRow`
accumulates slots for dispatch, manage, triggers, status, selection and a
chevron, and `SessionRow` accumulates slots for fork lineage, failed turns and
held-ness, then the duplication has not been deleted — it has been moved into a
configuration language harder to read than the JSX it replaced, whose state
space is the product of its slots and therefore not enumerable by a story.

The reports contain real evidence that hosts *deliberately* differ: C-F42 (the
worker drawer has no composer, on purpose), R-F4.4 (topic documents are always
the author view), S-F49 (the conversation's empty-state copy is a prop precisely
so `WorkerDrawer` can override it), L-F42 (the drawer is better titled by its
opener than by itself). Each is a per-host difference someone reasoned about,
and each becomes a prop.

**The tripwire, stated now so it is checkable later: more than four named slots
on any entity component means the density set is wrong, not the slot set.** The
likely correction at that point is a fifth density, not a sixth slot.

**Backing out is cheap, and that is the main thing recommending the shape.** An
entity component that takes props and returns markup is deletable by inlining it
at its call sites — mechanical, one call site at a time, no state to untangle.
The headless hooks are already the codebase's idiom. The expensive,
hard-to-reverse part is not the contract; it is the `ProjectList` split, and
that is worth doing regardless, because the file cannot otherwise be tested and
has no test today.

### 2.7 What this asks of the backend

Behaviour and contract changes are on the table, so these are proposed rather
than designed around. Each is flagged as backend-side and argued rather than
asserted.

**(a) Normalise the entity envelope — client-side, not server-side.** *(Decided:
client-side. **Corrected after implementation** — see the note below.)* Every
entity view gains a common head `{kind, id, label}` so `EntityRef` is one
component. It is derived in `domain/entity/heads.ts`, from the domain types
components actually receive — **not** in `infrastructure/http/dto.ts`. It costs
one function per entity and **no Python change**. Doing it in `presenters.py` is
cleaner and touches fourteen presenters and their tests.

> **Where this section was wrong.** It said "`infrastructure/http/dto.ts`
> already exists as the mapping layer, so this costs one function per entity".
> Two things wrong in one sentence, found by the agent building Foundation 1
> against it rather than by anyone re-reading it: `dto.ts` holds Zod *wire
> schemas* and `mappers.ts` is the mapping layer, and **no module under
> `presentation/` or `domain/` imports either**. Components are handed domain
> types and never see a DTO, so a head derived from one would have had nowhere
> to go — nothing needing a head would ever be holding the value it was derived
> from. The conclusion survives the correction and the argument below is
> untouched; only the file changes. It is recorded here rather than edited away,
> per this repository's convention, because the error is instructive: the
> section priced a decision against a layer it had not opened.

**Why the cheaper arm is defensible here, and what makes it reversible.** The
server-side version is the more correct one and would stay correct for a second
client; there is no second client, and there is no backwards-compatibility
constraint on this project — the standing rule is that pre-release means
breaking data, events and contracts rather than migrating them. No stored
shape, no event, no schema evolution, and no deprecation window, because
nothing outside this repository reads the wire. The cost of choosing wrong is
one afternoon, paid whenever a second consumer appears; the cost of choosing
right now is a Python change on the critical path of every early phase. That
asymmetry is the whole argument, and it would not hold on a project with
published API consumers.

**The reversal got cheaper once it was built, not more expensive.** Every
derivation is in `heads.ts` and nothing else constructs an `EntityHead`, so
moving server-side is: add the three keys to the presenters, carry them through
`mappers.ts`, and delete the file when its last function is a passthrough. **No
component changes, because no component knows where its head came from.** That
is a better position than the one this section originally described, and it is
a property of deriving from domain types rather than from the wire.

**(b) `topic_change` SSE frames gain `project_id`.** *(From the domain survey:
the frame is `{type, topic_id, change, occurred_at}` and omits `project_id`
deliberately.)* R-F3.8 records the cost, and `App.tsx:138-144` records the
symptom in a comment — the research page's topic list "had none, which is why a
seeded topic sat invisible until a reload". Additive field; presenter change
only; no event, no stored shape. **Improvement argued:** a shell that fans
frames out to regions needs every frame to name what it invalidates. One frame
that cannot is one region that must poll or over-invalidate, and a project page
left open all day pays that continuously.

**(c) `/api/projects` rows carry `activity`.** `docs/design/landing-page.md` §8
answer 1 already names this "the right fix and… still not done", and L-R1 prices
the current shape at **two requests per drawn row** — 21 requests at eight rows.
Under the contract this is what lets `ProjectCard` stop being a fetcher, which
is the whole point of the props-only rule; it is also what unblocks L-F7's "a
live project sorts first regardless of timestamp", recorded as not built
precisely because liveness cost a request per project. **This one is worth doing
for the layout as much as for the requests:** a card that fetches cannot be
virtualized honestly.

**(d) Rename `findings: int` to `finding_count` on `topic_view` and
`topic_detail_view`.** It collides with `finding_notes: [str]` on the same
object and `presenters.py` warns about it in a comment. Pre-release, no stored
shape involved, and the alternative is a props contract that typechecks a bug.

**(e) What I am not proposing: linking an artifact to the turn that wrote it.**
R-§8.6 wants it and the domain cannot answer it — artifacts are files in
`SessionState.files` and the declared list comes from the preset. Building it
means a new event or a new field on `FileWritten`, which is a stored-shape
decision with `CLAUDE.md`'s full ceremony attached: the field's docstring saying
what no longer loads, and `tests/infrastructure/test_schema_evolution.py`
updated to assert the refusal rather than having the case deleted. It is a
domain design question and a foundation document is the wrong place to settle
it.

---

## 3. Foundation two: the layout system

### 3.1 The shell contract

Three region roles. A role is a claim about *scope*, not about position.

- **`chrome`** — present on every route; holds what is not a property of the
  page you are on. `App.tsx:70-76` already states the test, for the agent dock:
  "'what is running' is not a property of the page you happen to be on — which
  is the whole reason it exists". The same test admits the connection badge, the
  drift badge, the breadcrumb, and — per `unified-ui-proposal.md` §3.4 — a
  decision bar, since what is *asking* you is not a property of the page either.
  It excludes everything else, which is the useful half of the rule.
- **`surface`** — the route's content. **Owns the viewport and does not
  scroll**; its regions scroll individually. This is already the console's
  contract (`tokens.css:94-104`'s `body { overflow: hidden }`), and
  `research.css:7-11` states why:

  > The view owns the viewport and does not scroll. Each region scrolls on its
  > own instead, which is the whole reason the graph can fill the height it is
  > given — inside a scrolling page every pane needs a fixed pixel height, and
  > fixed heights are what made this page a stack of small boxes with the
  > largest artifact in the smallest one.

  It is currently suspended below 820px by `responsive.css:40-45` setting
  `body { overflow: auto }`. The system makes that a declared mode rather than a
  media-query override of a global.
- **`overlay`** — one host. §3.4.

`Shell` renders the three; nothing else may. `ResearchView.tsx` is the precedent
— *(surveyed)* it is pure markup by design, documented as such at its head.

### 3.2 Panes and splits

```tsx
<Split id="session" axis="x" tracks={SESSION_TRACKS} breakpoints={PANE_BREAKPOINTS}>
  <Pane id="timeline"     label="Timeline"     collapseTo="rail"  minContent={240} />
  <Pane id="workspace"    label="Workspace"    collapseTo="rail"  minContent={240} meta={…} />
  <Pane id="conversation" label="Conversation" collapseTo="strip" unmountWhenCollapsed />
</Split>
```

**`Split` owns sizing, in one place.** Tracks are declared once as data — the fix
for `panes.css:73` and `use-panes.ts:67` declaring the same thing twice, one of
them dead and silent about it (§1.3). The breakpoint handoff
S-F18 describes, which the session report singles out as "genuinely subtle and
worth preserving", becomes a property of `Split` rather than a comment in one
hook: above the widest breakpoint `Split` writes `grid-template-columns`; at or
below it writes nothing, because an inline style outranks a media query. It
reads its breakpoints from the same tokens the stylesheet does, so `1180`/`1181`
stops being two numbers in two languages.

**`Pane` declares how it collapses and to what.** Three forms exist today and
each is right where it is: `rail` (34px, title rotated — the session view above
820px), `strip` (horizontal, title level with the column — the same panes below
820px, and the research rail's `is-folded`), and `unmountWhenCollapsed`, which
is R-F1.1's reason for existing and is load-bearing rather than cosmetic.
Collapsing these into one enum with one implementation is most of what this
foundation is for.

**`minContent` is the parameter §0.1's fix should have been.** 240px is already
the right answer for two lists in a rail; `.pane-body { max-height: 60vh }` at
≤820px is the same idea spelled differently. One parameter, one implementation,
and the next pane built inherits it.

**`use-panes.ts` cannot be promoted; it has to be rewritten, and
`component-system-spec.md` §9 and §13 are wrong about this.** *(checked.)* The
hook hardcodes `PaneName = 'timeline' | 'workspace' | 'conversation'`, a `GROUP`
of `'session'`, and a track weight chosen by `pane === 'workspace'`. Each is a
literal that a second tenant set invalidates, and
`unified-ui-proposal.md` §3.2 requires exactly that. "Kept as code" also
preserves the disagreement with `panes.css`, because the two were never read
side by side. What survives is the *reasoning* — fixed track rather than
min-width, the breakpoint handoff, the last-open refusal — and
`use-panes.test.tsx`, which is the only test in `presentation/session/` and
becomes `Split`'s regression net.

### 3.3 Tokens the layout system needs

`tokens.css` gains a fourth family. Its own opening rule — "a second literal hex
would be a second palette, discoverable only by looking at both" — is the
argument, applied to a dimension it does not currently cover.

```css
--rail-w: 34px;       /* was use-panes.ts:17 and responsive.css:29, :32 */
--bp-wide: 1181px;    /* one number; stylesheets use (width < var(--bp-wide)) */
--bp-narrow: 821px;
--bp-tight: 561px;
--z-sticky: 10;       /* sticky heads; in-region floating controls */
--z-overlay: 100;     /* every dismissable layer; order inside is DOM order */
--z-toast: 200;
```

Three z-values rather than five, for the reason in §3.4. `panes.css`'s ad-hoc
`7px`/`12px` (S-§13.3) move onto `--space-*` here rather than in the last phase,
because a layout foundation built on unscaled literals inherits them and then
they are load-bearing.

*(surveyed)* Other layout literals that want tokens once the system exists:
`340px` (research rail width, `research.css:39`), the drawer's
`42vw / 640px / 360px` (`course.css:528-530`), and the toast's
`min(420px, 80vw)` (`states.css:45`). The virtualizer estimates — `52` in
`DocumentList.tsx:16`, `108`/`30` in `ProjectList.tsx:228-229` — are **not**
tokens: they are properties of a row's own markup and belong beside it, which is
a distinction the token file should state so nobody hoists them.

### 3.4 One answer for overlays

**Every dismissable layer renders into one `OverlayHost` in the shell, through a
portal, and order within the host is DOM order rather than a z-index.** That is
what Radix's dismissable-layer stack provides, and it is why the number of
layers stops mattering: `--z-overlay: 100` is a single value because nothing
inside the host needs to outrank anything else numerically.

*(surveyed, and it changes the size of this piece of work)* **nothing in the
codebase uses `createPortal` today.** The host is new capability, not a
refactor, and it is the reason this belongs in the foundation phase rather than
being absorbed into a slice.

What it closes, concretely:

- The dock-over-drawer inversion in §1.3. Under one host, the drawer opened
  *from* the dock is above it — which is what `AgentWidget.tsx`'s comment already
  describes — and the popover's Escape and outside-pointerdown guards are
  **deleted** rather than reasoned about, because the stack owns which layer
  owns Escape.
- `TopicStatusDialog`'s duplicated `FOCUSABLE_SELECTOR`, duplicated effects and
  borrowed `.drawer-backdrop`/`.drawer` classes — the failure `Drawer.tsx:17-19`
  was written to predict, sixty lines away.
- The drawer-and-menu tie at `20`, which is benign today only because one is
  fixed and one is absolute, and which nothing states.
- The graph's three peers at `1`. `.graph-command`, `.graph-detail` and
  `.graph-legend` are **in-region floating controls, not dismissable layers**,
  so they take `--z-sticky` and stay ordered inside the graph pane. This is the
  distinction a single value cannot express, and it is why the scale has three
  levels rather than one.

Toasts stay outside the host at `--z-toast`, for the reason `agents.css` already
gives: they must stay readable over whatever is open. They also gain a keyboard
route, which L-F37 records they lack — "a `<div>` with an `onClick`, no close
affordance".

### 3.5 Which reported complaints become parameters, and which do not

I was asked to be explicit. The third group is the one that matters most,
because a layout system that claims those will be measured against them and
fail.

**Become parameters of the layout system.**

| Complaint | Parameter |
|---|---|
| R-§7.5, and §0.1's rail-pane floor; S-F19's `.pane-body { max-height: 60vh }` | `Pane.minContent` |
| R-F1.1, folding must unmount so a virtualizer does not measure zero height | `Pane.unmountWhenCollapsed` |
| S-F17's 34px rail vs S-F19's horizontal strip below 820px vs research `is-folded` | `Pane.collapseTo` |
| S-F18's 1181px inline-style / media-query handoff | `Split`, once |
| `panes.css` and `use-panes.ts` declaring the same three tracks, one of them dead | `Split.tracks`, one declaration |
| L-F41 / S-F60, the dock dropping fields at 560px and 420px without wrapping or changing row height | a `progressive-drop` utility reading `--bp-*`; the *values* stay the dock's |
| C-D7's findings section rendering `null` when empty; L-§8's per-region empty/loading/error matrix; S-F4's whole-page error | `Region`'s required empty / loading / error slots — a region rendering nothing must say which nothing |
| C-F30's autonomy panel filling the first screen; C-P7's unfiltered 15-stage artifact column | `Pane` default-collapsed, declared rather than remembered per view |

**Become one answer, not a parameter.** Each is a behaviour change; each is
argued.

- **The last-open rule.** S-F17 refuses to hide the last open pane; R-F1.1
  deliberately does not, and R-§7.5 records the cost: a folded seeding pane —
  and folded state persists across reloads — leaves a user reading "nothing has
  been seeded" with **no seeding control on screen**. There is no case for the
  permissive arm. `Split` refuses, everywhere.
- **Overlay stacking.** §3.4. A per-view stacking parameter is how you get five
  z-index values and a comment describing the wrong order.
- **Navigation is a link.** §2.3 rule 2, closing L-§9.3.
- **The surface owns the viewport.** Below `--bp-narrow` this becomes a declared
  single-column scrolling mode rather than a stylesheet override of `body`.
- **A region's failure is region-level.** S-F4's whole-page error becomes a
  region error. Under any merged page this stops being optional: one failed
  session read must not blank a project page.

**Do not become either, because they are not layout problems.**

- **C-D14, stage status is positional** — "a stage advanced past with nothing
  written still reads `done`", called "the rail's single most misleading
  affordance". Data, plus an entity-presentation debt: foundation one owes it an
  evidential chip beside the positional one. No arrangement of panes fixes it.
- **S-D10, a file the agent just rewrote showing its old contents** — "the most
  consequential defect I found". Cache invalidation.
- **R-§7.2, two mutations declaring only `onSuccess`** — "the single clearest
  defect found". Wiring, two lines, and it should not wait for any of this.
- **S-D7, the timeline's invisible fork column.** It reads as a layout defect
  and is a missing *status presentation*: a mode exists with nothing on screen
  saying so. Foundation one, not two.
- **R-§7.4, pinned graph nodes never unpinned.** A graph-library question the
  research report itself declines to settle.
- **L-§9.8, `lastActivity` is session start.** A server fold.
- **C-F51, one stage expanded at a time.** A state model — `openStage` is a
  single string. It becomes a layout question only if the answer is side-by-side
  comparison (C-P9), which is a feature, not a foundation.
- **S-§14.15, no cross-reference between timeline and conversation** — "the
  single largest missed affordance". A data join between `turn_index` and a
  message index. The layout system makes it *placeable*; it does not make it
  exist.

### 3.6 What this costs when it is wrong

**The risk that matters is that `Split` and `Pane` are a worse
`use-panes.ts`.** The current hook is 78 lines, tested, and encodes one
genuinely subtle thing correctly. A generalised version has more states — three
collapse forms, N tracks, a breakpoint table — and the subtle thing must survive
all of them. If it does not, the failure will be exactly the class
`landing-page.md` §8 records: correct in every test, wrong at one window width
nobody's machine uses. S-F19's three responsive layouts and L-F41's 560/420
drops are where I would expect it, for the reason the spec gives — they are the
rules least likely to be exercised by anyone's normal window size.

**And the test suite cannot close that gap.** *(surveyed)* `vitest.setup.ts`
stubs `matchMedia`, `ResizeObserver`, `getBoundingClientRect` and
`offsetHeight`/`offsetWidth`, with a comment saying "real layout is Playwright's
job, not jsdom's" — and **there is no Playwright config or test in this
repository**. So a `Split` test can assert which template string the hook emits
at a stubbed breakpoint, exactly as `use-panes.test.tsx` does today, and cannot
assert that the resulting grid lays out. I should not pretend the prerequisite
in §4 buys more than it does.

**Backing out is genuinely hard, and harder than backing out foundation one.** A
layout primitive every view mounts inside cannot be inlined at its call sites;
reverting means restoring two pane systems and a patch stylesheet. The
mitigation is sequencing rather than design: §4 requires `Split` to host the
session view's three panes before any second tenant exists. If it cannot host
the hardest case it has not shipped, and the revert at that point is one commit.

---

## 4. The rollout

Foundations first, then one surface end to end at a time. Every phase deletes
what it replaced, and §4.4 proposes making that a gate rather than a promise.

The toolchain phase (`component-system-spec.md` §11 phase 0 — Storybook,
Tailwind v4, CVA, `jsx-a11y`) lands before all of this. *(checked — none of
those dependencies is in `frontend/package.json` on `main`, there is no
`.storybook/`, and no `*.stories.*` file exists, so it is genuinely in flight
and not yet landed.)*

### Phase A0 — the net for the session panes. **Shipped: PR #95.**

Characterization tests for what the session panes do today, so phase A has
something to fail against. 21 tests over `Pane` (new file) and `usePanes`.
No source changed.

This phase exists because of how decision 1 was settled (§7). The argument for
proving `Split` against the session panes stands; the counterweight is that
`component-system-spec.md` §11 deliberately kept its phase 1 out of
`presentation/session/` so the untested directory stayed untouched while a net
was built. Both, in order: the net first, then the migration into it.

**What it does not cover, and this is the part that constrains phase A.** jsdom
lays nothing out and there is no Playwright (§3.6), so every assertion is about
markup. In particular `SessionView.tsx:182` — the one line wiring
`gridTemplateColumns` onto `.panes` — is unprotected, and deleting its `style`
prop passes the whole suite. So does deleting any rule in `panes.css` or
`responsive.css`. The PR lists eight unprotected behaviours for a browser check;
phase A must not read the green suite as covering them.

Two tests in the first draft were found to be false cover and rewritten — one
claimed pane order in its name and passed when `PANES` was reversed; nothing
noticed when the breakpoint query itself changed. Both were caught by mutating
the source rather than by reading the tests, which is the argument for keeping
the red/green discipline on every phase rather than only the risky ones.

### Phase A — the foundations, proved against the hardest existing case. **Shipped.**

Layout tokens (§3.3). `Shell`, `Region`, `Split`, `Pane`, `OverlayHost` — the
last through a portal, which is new — and Radix `Dialog`, `Popover`, `Menu`,
`Tooltip` behind them. The entity contract's shared parts: `EntityRef`,
`EntityStatus`, `statusLabel`, `Provenance`. And **the session view's three
panes migrated onto `Split`**, because that is where the subtle behaviour lives.

*Prerequisite, not a follow-up:* `use-panes.test.tsx` extended to assert the
template emitted on both sides of the breakpoint and the last-open refusal, and
a first test for `Drawer` and `Confirm` — each proved red against a deliberately
broken version first, per this repository's convention. *(surveyed)*
`presentation/common/` has **zero** test files and holds `Drawer`, `Confirm`,
`primitives.tsx` and `content.tsx`: the four files every phase touches first are
the four with no coverage. Note §3.6's limit on what these tests can prove.

*Deletes:* `TopicStatusDialog`'s hand-copied focus trap and `FOCUSABLE_SELECTOR`;
`Drawer`'s trap; the dock's Escape and outside-pointerdown guards; all eight
`z-index` declarations; `34px` from two of its three sites; `1180`/`1181` from
one of its two; `.replace('_', ' ')` from all three.

*Why it ships alone:* it removes the dock-over-drawer inversion, which is a
modal dialog with a live, clickable panel painted over its backdrop, in the one
place the code already wrote down what the order was meant to be.

*What it actually found, recorded after the fact.* The primitives were mostly
a description rather than an invention: most of the migration was a rename.
Three things were not. `Pane` had no way to pin content below a scrolling body,
which two of the three panes need and which was `.pane.collapsed >
*:not(.pane-head)` hiding a composer with `display: none` and leaving it in the
accessibility tree. `Pane` had no way to say the body must not scroll, which was
two props — `bodyClassName` and `raw` — for one shape. And `Pane` chose between
a rail and a strip on the wrong breakpoint, turning a folded pane into a strip
360px of width early; that one was found by hitting it, not by reading, and
`Split` now carries `stacked` separately from `wide`. A migration that had
needed no changes to the primitives would have been evidence they were never
tested against anything.

*The risk, stated plainly:* this touches `presentation/session/` — fifteen
components, one test file — before anything else. The alternative is to build
`Split` against the research rail first and migrate the session panes last,
which front-loads less risk and defers the question of whether `Split` can host
the hard case until four phases depend on it. **I take the hard-case-first arm
and it is the decision in this document I am least comfortable with.** Open
question 1.

### Phase B — the research surface, end to end

`TopicRow`, `TopicDetail`, `TopicRef`; `SourceRow`, `SourceDetail`;
`GraphEntityRef`, `GraphEntityDetail`; `SubQuestionRow` split from its mutation.
`useTopics`, `useTopicStatus`, `useDispatchTopic` — the last with the `onError`
R-§7.2 wants. The rail becomes `Split`/`Pane`; `RailPane` and the research half
of `responsive.css` go. The topic detail stops being a modal and becomes a
region, so R-F3.10's five unrendered fields land, and R-§8.5's two things called
"Documents" become one component with two call sites.

*Why research first:* it has the most tests of any presentation directory (ten
files against fifteen components); its entity already ships a row shape and a
detail superset on the wire, so the density split is verifiable against
something rather than invented; three of its rows are prop-pure already; it
touches `presentation/session/` not at all; and it carries the defect its own
report calls the clearest one found, as a two-line fix inside a hook the phase
creates anyway.

*Ships on its own as:* a research view where a topic's rationale, scope,
sources, finding notes and contested flag are visible for the first time, where
a topic is linkable, and where a failed dispatch says so.

### Phase C — the picker

`ProjectCard`, `ProjectRef`, and the `ProjectList` split (§2.4). Requires
§2.7(c), `activity` on `/api/projects` rows, because a card that fetches cannot
be a row.

*Why third:* it is small, it is the contract's worst state-coupling case, and
meeting the hardest test while the contract is still cheap to change is worth
more than deferring it. It also delivers L-§9.3 — the whole page becoming links
— which is one of the few user-visible wins available at no layout risk.

### Phase D — the course surface

`StageRow`, `ArtifactRow`, `ArtifactDetail`, `FindingRow`, `WorkerRow`, and one
worker roster instead of C-D6's two. C-D14 gains its evidential chip beside the
positional one. Cheapest of the four: `StageRail.tsx`, `Artifacts.tsx` and
`Findings.tsx` are already prop-pure and exported.

### Phase E — the session surface

`EventRow`, `FileRow`, `MessageRow`, `ApprovalDetail`. The timeline, the file
list and the conversation onto the contract. Last, because
`presentation/session/` has one test file for fifteen components and the session
report's verdict is that "any redesign here is a redesign without a net" — and
because by this point four surfaces' worth of stories are a net that does not
exist today.

### 4.1 On slicing by surface when the surfaces may be merged

`unified-ui-proposal.md` §3 argues the course and research pages should not
exist, replaced by one project page with QUEUE / HOLDER / MATERIAL regions.
Slicing "research end to end" and then deleting the research page would be
waste. This is the sharpest objection to the plan above and it deserves a direct
answer.

**A slice is defined by its entities and its regions, not by its route.** Phase
B produces `TopicRow`, `TopicDetail`, `SourceRow`, the graph components, and a
rail of `Pane`s. Under the merge every one of those survives: the topic queue
becomes a QUEUE row source, the corpus and graph become MATERIAL facets, the
topic detail becomes the MATERIAL `topic` facet. What is thrown away is the
route and the page component — two files.

That is also the strongest argument for foundations before merge rather than
after. `Region` and `Split` are what make regions relocatable at all; without
them, moving the run panel from the course page to a QUEUE header is a rewrite,
and with them it is a re-parent.

### 4.2 What each phase deletes

Listed per phase above. The general rule, adopted from
`component-system-spec.md` §15: **a phase that adds a mechanism without removing
the old one has not shipped.**

### 4.3 The gates

`ruff check .` and `ruff format --check .` run over the *whole repository*, so
any phase touching a Python test file has to run both whether or not it touched
Python source. §2.7 proposes three small Python changes — (b), (c), (d) — all
presenter and route work with no event and no stored-shape consequence, so
`pytest` and `test_schema_evolution.py` are untouched by everything here. §2.7(e)
is declined for exactly the reason it would not be.

`npm run verify` absorbs the frontend work inside its existing chain; no new CI
job. Three things worth naming because they only fail there:
`prettier-plugin-tailwindcss` must be in place before the first utility-heavy
component, or class order is diff noise on every phase; the bundle-size budget
is the other chain-only check; and *(surveyed)* **the built output is committed
to this repository** (`vite.config.ts` builds into
`research_team/interfaces/web/static`), so every phase that changes the bundle's
shape lands as a large committed diff. That is worth landing in its own commit
each time, the way §12 of the spec recommends for the Prettier reflow.

One coverage note. *(surveyed)* `src/presentation/**` has **no per-layer
coverage threshold** — it is held to the global floor deliberately. So the
ratchets will not notice a phase that adds components without tests. If the
deletion gate in §4.4 is wanted, a presentation floor that rises one phase at a
time is its natural companion.

### 4.4 Making the deletion discipline a mechanism rather than a promise

`component-system-spec.md` §15 concedes the weak point in its own plan:

> Each phase's exit criterion is deleting what it replaced… This is the one that
> actually matters, and it is **a promise rather than a mechanism** — nothing in
> the four gates fails when a superseded implementation is left in place.

It also names the honest fix — "a lint rule or a deletion checklist per phase" —
and records that neither exists. It is cheap: a `scripts/check-deleted.mjs` in
the `verify` chain holding a list of forbidden strings and paths, one block per
landed phase, failing the build if any reappears. After phase A that list is
`z-index:` outside `tokens.css`, `FOCUSABLE_SELECTOR`, `'34px'`,
`replace('_', ' ')`, `1181`. After phase B it gains `RailPane`. This is the same
shape as `check-size.mjs`, which already exists and already gates the chain, and
it converts §15's admitted weakness into a failing build. Open question 5.

---

## 5. Where I disagree with `component-system-spec.md`

It is a good document and most of it stands. Six disagreements.

**5.1 Its §9 is a component list, and the duplication it cannot see is the one
this document is about.** Its §5 names five mechanisms that prevent repetition
and every one is about *interaction*: Radix owns each contract once, CVA closes
the variant set, `@theme` makes off-palette values unwritable, Storybook makes
the set discoverable, `jsx-a11y` fails the build. None prevents a topic being a
`<div class="topic-question">` in one file and an `<h3 class="drawer-title">` in
another, or `status.replace('_', ' ')` being written three times, or
`DispatchChip` existing beside `Chip`. A `Chip` with seven tones does not stop
that; it supplies a better chip to both copies. The spec documents duplication
of *behaviour* and has a mechanism for it. Duplication of *entity presentation*
is the larger class by count and the spec does not name it.

**5.2 Its §9 and §13 say `use-panes.ts` is "kept as code; only restyled" and
"promoted and restyled, never reimplemented". That is not achievable.**
*(checked.)* The hook hardcodes three pane names, the preference group
`'session'`, and a track weight selected by `pane === 'workspace'`. Any second
tenant set — which `unified-ui-proposal.md` §3.2 requires — is a rewrite, not a
restyle. "Kept as code" also preserves the disagreement between the hook's track
minima and `panes.css`'s (§1.3), which exists because the two were never read
side by side. What should be preserved is the reasoning and the test; §3.2 says
so.

**5.3 Its §6 states the right Storybook rule and its §9 inventory violates
it.** The rule is "a component gets a story if it can be rendered from props
alone… a component that cannot get a story is telling you it is not a component
yet". Tier 1 then lists `Panes` — whose hook calls `useContainer()` *(checked)* —
along with `VirtualList` and `DataGrid`, which own scroll containers and
measurement. Those are not props-only as they stand. The rule is right; making
the inventory satisfy it is exactly the props-only constraint in §2.3, which the
spec does not state. And the rule needs its exception written down (§2.4):
`GraphCanvas` cannot be props-only and should not be, and a rule with an
unstated exception is one people route around.

**5.4 Its §4's "What I did not do: invent new tokens" is right about the palette
and wrong about layout.** The check it performed — that every token
`landing-page.md` §6 called missing has since landed — is correct, and I
re-verified it in `tokens.css`. It does not generalise. There is no z-index
token, no breakpoint token and no width token, and `34px`, `1180`/`1181` and
`560` are each written in two or three places, one of them in two different
at-rule syntaxes. `tokens.css` says a second literal is a second palette; the
layout constants already are one, and nothing catches them.

**5.5 Its §11 phase 5 defers `panes.css`'s ad-hoc `7px`/`12px` to the last
stylesheet phase.** Those values are inputs to the layout foundation, not
leftovers of it. A `Split` built on unscaled literals inherits them and then
they are load-bearing. §3.3 moves them in phase A.

**5.6 Its §11 ordering leaves every view half-migrated for six phases, and its
own §15 is the argument.** "Stop after phase 2 and the console has Tailwind
*and* nineteen stylesheets, Radix dialogs *and* a hand-rolled popover" — a
reader "has to know which era a file belongs to before they can change it".
Vertical slices do not remove that hazard; they bound it. After phase B exactly
one surface is on the new system and three are on the old, and the boundary is a
directory rather than a mechanism. Stopping is still bad; it is legible.

**One place the spec is more right than it knows.** Its §3.1 argues Radix's
per-primitive packaging is what makes a strangler "payable in instalments", and
prices the floating-layer cost as paid once by whichever of
menu/popover/tooltip/select arrives first. §3.4 above concentrates all four in
phase A, which pays that ~20 kB in one instalment rather than three — and gets
the dismissable-layer stack, which is the actual fix for §1.3, at the same time.
The spec's own curve supports doing it this way; its phase ordering spreads it
out for reasons that were about primitives rather than about the stack.

**Where I agree and want it recorded.** The find-in-page trade in §9 is
correctly priced and correctly taken. §10's insistence that a test asserting
current behaviour must exist, and be proved red, *before* an implementation is
swapped is the right prerequisite and I have copied it. §15's deletion
discipline is the load-bearing one, and §4.4 is an attempt to answer its own
complaint about it.

---

## 6. The strongest argument against this design

**The entity contract is a bet that these surfaces want the same presentation of
an entity, and the reports contain direct evidence that several of them
deliberately do not.**

C-F42 records the worker drawer having no composer, on purpose. R-F4.4 records
topic documents rendered always as the author view, where the other two mounts
of the same renderer carry an audience toggle. S-F49 records the conversation's
empty-state copy being a prop precisely so `WorkerDrawer` can override it.
L-F42 records the drawer opened from the dock being better titled by its opener
than by itself. C-F8 records a worker without a session rendering as plain text,
"deliberately not a dead button". Every one is a per-host difference somebody
reasoned about and wrote down, and under §2.3 every one becomes a prop or a
slot.

Follow that far enough and `TopicRow` carries slots for dispatch, manage,
triggers and status; `SessionRow` carries slots for fork lineage, failed turns
and held-ness; `ArtifactRow` carries slots for provenance and a file link — and
the duplication has not been deleted, it has been moved into a configuration
language harder to read than the JSX it replaced, whose state space is the
product of its slots and therefore not enumerable by a story. That is the exact
outcome the gallery was supposed to prevent. §2.6's tripwire is a discipline,
not a mechanism, which is the same weakness `component-system-spec.md` §15
admits about its own deletion rule and which §4.4 only partly answers.

**Three more, in decreasing order of how much they worry me.**

*Nothing here has been run.* No component was built, no story written, no test
proved red. I read source and grepped. The two disasters `landing-page.md` §8
records both passed every gate and were found by a person using the product, and
both were layout-and-data restructures of exactly this kind. §3.6's finding
sharpens this: jsdom cannot test layout and there is no Playwright here, so the
class of failure this design is most exposed to is precisely the class the
suite cannot see.

*Phase A touches the least-tested directory first, on purpose.* Fifteen
components, one test file, and the one subtle behaviour in the console that its
own report flags as worth preserving. The argument for doing it there is that a
layout primitive which cannot host the hard case has not shipped; the argument
against is that four phases would then depend on a primitive validated against
the thing most likely to break.

*Four densities across fourteen presentables is up to fifty-six components,
against roughly sixty presentation files today.* The contract could be a larger
surface than what it replaces. §2.2's rule — implement a density when a second
call site needs it — is what keeps that from happening, and it is a discipline
too.

---

## 7. Decisions taken, and what is still open

The six questions this document opened have been answered. They are recorded
here with the reasoning that settled them, because a decision without its
argument is one somebody re-opens in six months.

**1. Phase A goes against the session panes — with the net built first.**
The argument for the hard case stands: proving `Split` against S-F18's
breakpoint handoff and S-F17's last-open rule is how you avoid an abstraction
that only fits the easy cases. The counterweight is that
`component-system-spec.md` §11 deliberately kept its phase 1 out of
`presentation/session/` so the untested directory stayed untouched while the net
was built — and that reasoning is sound and was not answered by mine. Both, in
order. Phase A0 above is the net and has shipped; phase A migrates into it.

**2. The entity envelope goes client-side, in `dto.ts`.** Server-side is more
correct and that is granted rather than argued away; client-side costs no Python
on the critical path of every early phase, and with no backwards-compatibility
constraint the move server-side later is one afternoon and no migration.
§2.7(a) now records what makes it reversible, which is the part that justifies
taking the cheaper arm rather than merely preferring it.

**3. Three z-levels.** The fourth gets added if and when a graph control
actually needs to escape its pane — not pre-emptively, and not as an exception
to the three.

**4. `check-deleted.mjs` lands in the `verify` chain.** The counter — that a
list of forbidden strings drifts and a stale entry fails a build for nothing —
is real and is outweighed. This repository's pattern is turning promises into
mechanisms: the AST guard over the `create_app` call site, the feed-coverage
test, `apply_schema`'s column reconciliation with a test that drops a column and
reopens. §15's delete-what-you-replaced is currently a promise of exactly the
kind those three replaced, and it is the one §15 itself says matters most.

**5. Three backend asks are approved and scoped as backend work:**
§2.7(b) `project_id` on `topic_change` frames, §2.7(d) the
`findings` → `finding_count` rename, and §2.7(c) `activity` on
`/api/projects` rows. (b) and (d) are presenter-only and unblock phase B; (c)
is the one with real server work and blocks phase C. §2.7(e), linking an
artifact to the turn that wrote it, **stays declined** — the reasoning holds and
it blocks nothing.

**6. Foundations precede the merge**, per §4.1: the slices are defined by their
entities and regions rather than by their routes, so they survive it, and
`Region`/`Split` are what make the merge a re-parent instead of a rewrite.

### Still open

- ~~**The unprotected list from phase A0** (PR #95), of which
  `SessionView.tsx:182` was the one that mattered.~~ **Checked in a browser and
  then closed by phase A.** The browser pass confirmed the collapse, the
  breakpoint crossing and the track values; the view's own wiring — the hole
  where one deleted prop left the whole suite green — is now held by
  `SessionView.test.tsx`, which mounts the real view rather than a composition
  of the primitives. What remains unprotected is unchanged in kind and is
  listed in that PR: jsdom computes no geometry, so no test observes a width, a
  34px rail, or whether a folded pane is off the screen, and every rule in
  `layout.css` and `responsive.css` can still be deleted with the suite green.
- **Whether `presentation/` gets a coverage floor that rises per phase**,
  beside `check-deleted.mjs`. It has none today, deliberately, so the ratchets
  will not notice a phase that adds components without tests. Raised in §4.3;
  not decided.
- ~~**Which of the two disagreeing track values is right.**~~ **Resolved by a
  browser pass, and there was no disagreement to resolve:** `panes.css:73` has
  never applied, because the hook writes `grid-template-columns` inline and
  inline beats a stylesheet unconditionally (§1.3, corrected). The live values
  are 280/320/280 at 1.05/1.5/1.05 and phase A pins them, so adopting the dead
  stylesheet's numbers would now be a deliberate 20px change with a test to
  argue past rather than a side effect of a refactor.
