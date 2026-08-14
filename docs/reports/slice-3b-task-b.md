# Slice 3b, task B — the `topic` facet, and the panel that stopped being a dialog

Read against `bd4b16f` plus tasks A, C and D's uncommitted work. Four jobs, all
done. Two findings that are not in any brief, one of which cost an hour and is
the more useful half of this report.

---

## Job 1 — the `topic` facet becomes real

`managing` is the route's now. Three files, following slice 3a's precedent and
`useDocuments`'s prop shape exactly:

| File | Change |
| --- | --- |
| `ProjectView.tsx` | `openTopic = selection?.facet === 'topic' && selection.id !== null ? TopicId(selection.id) : null`, passed to `TopicList` with an `onOpen` |
| `TopicList.tsx` | `open`/`onOpen` props, both defaulted, threaded into `useTopicQueue` |
| `use-topic-queue.ts` | `managing` is a parameter, not `useState`; `onCloseManage` calls `onManage(null)` |

Two literal comparisons rather than a helper, per the brief and per
`ProjectView.tsx`'s own comment: comparing `selection.facet` against a variable
narrows nothing, so `selection.id` stays the union of every facet's id type,
`FilePath` included. `TopicId(...)` brands it at the boundary, which is what
`openDoc` does with `SourceId(...)` one line above.

The defaults (`open = null`, `onOpen = () => {}`) are `useDocuments`'s, and are
a real caller rather than a convenience: eighteen of the twenty tests in
`TopicList.test.tsx` render the queue with no route around it, and that queue
opens nothing, which is honest.

### Glance or destination: **glance, replaced not pushed**

The same call the stage toggle and every MATERIAL selection make, and the test
is what the back button should do after forty of them. The queue is a list a
reader scans — open a question, see what it is blocked on, go back, open the
next. Pushed, the back button walks out through thirty-nine topics before it
leaves the project page; replaced, it leaves. Watching a worker stays the one
selection on this page that pushes, because it is somewhere you go rather than
something you look at.

**Closing writes `null`, not `{ facet: 'topic', id: null }`, and that differs
from the document list on purpose.** A doc's close keeps its facet because
MATERIAL has tabs and dropping it would close the Documents tab under the
reader. QUEUE renders whatever the facet is, so a bare `topic` selection holds
nothing open and would only be a URL meaning the same as no selection.

### Tests

`opens the topic the route names, with no click at all` in
`TopicList.test.tsx`, modelled on `DocumentList`'s equivalent including its
`findByRole`-not-`getByRole` lesson (`bd4b16f`): the detail is a second
request, and a test with no click in it does not get the microtask flush
`user.click` hands out for free. It fails with `managing` reverted to
`useState`, because nothing in it clicks.

**What is still not asserted:** that `ProjectView` passes `openTopic` at all.
`ProjectView.test.tsx` is pure-function tests over `regionOf` and renders no
JSX, so the threading is covered one component down, exactly as slice 3a left
`openDoc`. Worth knowing that a deleted prop in `ProjectView` would be caught
by `tsc` and by nothing else.

---

## Job 2 — the status dialog stops being modal

`TopicStatusDialog` is a `<section aria-label="Manage <question>">` in the
QUEUE column, below the queue. It renders `Loading` while the detail read is in
flight, which the drawer did not need and this does: a route-opened topic
arrives with no click behind it, so rendering nothing would show the plain
queue for the length of a request — the exact defect job 1 exists to fix,
reintroduced one request later.

### What it cost

**One thing, and it is not the keyboard contract.** Phase 1 already deleted the
hand-rolled trap; what goes is `Overlay`'s `modal`, i.e. `inert` on the page
behind. The real loss: **the page can now take a click while a half-written
justification is on screen.** A reader who types two sentences and then clicks
another topic's Manage loses them. That is the whole of it, and it is why the
commit moved behind a `Confirm`.

### What it preserved, and how Escape and focus return changed

Every assertion in `TopicStatusDialog.test.tsx` survives — justification
required and trimmed, current status not offered, save-then-close, reopen — and
the file grew from 7 tests to 10.

- **Escape.** Was the overlay host's, given to the topmost layer. There is no
  layer now, so it is a `document` listener that acts only when
  `event.target` is inside the region. Not `window`: the page behind is live,
  and a global Escape is the defect `GraphDetail` shipped once (task #24). It
  is on `document` rather than as an `onKeyDown` in the markup because
  `jsx-a11y/no-noninteractive-element-interactions` fails the build on a
  `<section>` with a key handler — and this file's own history records two
  suppressions that were deleted rather than argued with, so the containment
  test is written out instead. That spelling is also *more* correct than the
  JSX one: React bubbles portal events along the component tree, so an
  `onKeyDown` here would have received the `Confirm`'s own Escape and closed
  both. Two tests: `closes on an escape pressed inside it` and **`ignores an
  escape pressed outside it`**, the second proved red by temporarily moving the
  listener to `window`.
- **Focus in.** Kept, and it matters more than it did, not less: the panel
  renders below a queue that can be screens long. Cost stated: a page opened
  directly at `#/p/<id>/topic/<tid>` moves focus off `<body>` once.
- **Focus return.** Was unconditional and had to be — with the page `inert`,
  focus at close time was always inside. Now it is **conditional on focus still
  being inside the region when it goes away**, because a reader can tab out and
  carry on, and yanking them back to a row they left several actions ago is
  worse than doing nothing. `leaves focus alone when it closes with the reader
  working elsewhere` is the new test, proved red by making the restore
  unconditional.

### The mandatory-justification form is a `Confirm`, per §3.3

Save opens `Confirm` — heading `Change this topic to Answered?`, the trimmed
justification quoted back, and `Set to Answered` as the confirm label — and the
mutation fires from its `onConfirm`. **Save now takes two clicks.** That is
charged only on the irreversible action, which is the trade §5.2 recommends
over making the panel a dialog again. `OverlayHost` is therefore still a
precondition of this test file, for a narrower reason than before, and the
harness comment says which.

### Two findings about React that are not in any brief

1. **A `focus()` call made during the mutation phase does not survive the
   commit.** The restore was first written in the close button's callback-ref
   detach — the ordering `Drawer` argues for — and it visibly worked:
   `document.activeElement` was the restored element on the very next
   statement. It was then silently undone. React captures the focused element
   before mutating the DOM and restores it afterwards, which is the mechanism
   that keeps focus alive across a re-render that replaces a node. It is
   invisible in the close-by-Close case, because there the focused element is
   the button being removed and React has nothing to restore — which is the
   only case any test covered before this slice added a second one. The restore
   is now a passive unmount cleanup, which runs after that restoration;
   containment is still measured in the ref detach, because a tick later the
   node is gone and `contains` is false whatever the reader was doing.
   `OverlayHost` reached the same conclusion from the other direction and its
   comment says so.
2. **A `useRef` on the region would have been `null` when the button's ref
   asked about it.** React detaches refs top-down through a deleted subtree, so
   the ancestor's ref clears before the descendant's runs. The section is held
   through a callback ref that ignores `null`.

Both cost real time, and the first also cost a test: **the first version of
`leaves focus alone…` drove open and close through `user.click` and passed with
the containment check removed.** A pointer event carries a focus change of its
own, so every assertion about where focus *ended up* was true either way. It
now drives both through `rerender` and sends no pointer event. That is recorded
in the test's own docstring, because the failure mode — a green test measuring
nothing — is the one this repository keeps warning about.

---

## Job 3 — the class names, all six of them

The brief named two; the file wrote six, and the other four had no other owner,
so leaving them would have undressed the panel the moment task E deletes the
file. `research.css` is untouched.

| Class | Utilities |
| --- | --- |
| `topic-documents-section` | `mt-[16px] border-0 border-t border-solid border-line pt-[12px]` |
| `topic-section-heading` | `font-medium m-0 mb-[8px] font-mono text-xs tracking-[0.06em] text-fg-faint uppercase` |
| `topic-status-current` | `mb-[8px] text-sm text-fg-dim` |
| `topic-status-choices` | `mb-[10px] flex flex-wrap gap-[6px]` |
| `topic-status-justification` | `mx-0 mt-[4px] mb-[10px] block min-h-[4.5em] w-full resize-y` (keeps `input`) |
| `topic-status-actions` | `mb-[16px]` |
| `topic-status-choice` | dropped — `.btn[aria-pressed='true']` in `shell.css` already draws the state, and the rule was already gone |

Both border cases are `border-0` plus a directional width-and-style, per
`CLAUDE.md`. Task A's per-branch colour convention did not arise here — nothing
in this file sets a base colour and overrides it. Every arbitrary utility was
grepped out of the built `index.css` and emits a rule (`min-height:4.5em`,
`letter-spacing:.06em`, `resize:vertical`).

**Eight class names are now dead in `research.css` for task E**, not two.

---

## Job 4 — one fix, one spelling

`TopicQueue.tsx`'s `RING_INWARD` is `'lay-ring-inward'`. The constant survives
so the comment has something to hang on; the comment now points at the class
and keeps the measurement that found the hazard.

**Re-measured after the swap** — Chromium, headless, 1440×900 per
`vite.config.ts`, 2026-08-14, 24 topics in a 340×300 column:

| | value |
| --- | --- |
| computed `outline-offset` / width | `-2px` / `2px` |
| list border box | `0..340 × 75.5..300` |
| ring reach | `0..340 × 75.5..300` |
| scroller clip (padding box) | `0..340 × 75.5..300.5` |

Identical to task A's `!` row (`0..340 x 75.5..300`). The geometry is
unchanged; only the spelling is. `topic-list-ring.browser.test.tsx` gains a
fourth row in its table saying so, and its "what breaks these again" list no
longer names a `!` that no longer exists.

`grep -r 'outline-offset-\[' src/` finds nothing outside `TruncatedText.tsx`,
which task C already flagged as inert-but-harmless and out of scope.

---

## Tests

Serialised through `flock /tmp/rt-vitest.lock` throughout.

- `TopicStatusDialog.test.tsx` — 10 (was 7). Three new: the region-not-dialog
  claim, the outside-Escape refusal, and the conditional focus return. The last
  two **proved red**; the first is reasoned (a `Drawer` renders
  `role="dialog"` and `aria-modal="true"`, so it cannot pass) and its docstring
  says so rather than claiming a proof.
- `TopicList.test.tsx` — 20 (was 19). One new route test, one rewritten to
  query a region rather than a dialog.
- `src/presentation/research` + `project` + `entity/topic`: **166 pass, 21
  files.**
- `npm run test:browser`: **57 pass, 19 files**, twice, unchanged from task C's
  figure.
- `scripts/`: 89 pass. `npm run build` succeeds.
- `tsc --noEmit`, `eslint` and `prettier` clean over every file touched.

Per the brief, `npm run verify`, `pytest` and `ruff` were **not** run.

---

## What I could not do

- **The file is still called `TopicStatusDialog.tsx` and is not a dialog.**
  `TopicManagePane` is the right name. Five files outside my list name it in
  prose — `SubQuestions.tsx`, `TopicDocuments.tsx`'s neighbours,
  `use-topic-queue.ts`'s sibling comments, `entity/topic/TopicDetail.tsx`,
  `SeedForm.tsx` — three of them belonging to tasks live in this same tree, and
  a rename that reaches into live files to fix comments is the merge this
  project keeps a rule about. The component's own docstring says the name is
  wrong. **Owed, and cheap once the tree is quiet.**
- **Nothing was rendered below `--bp-wide`, and nothing was opened by eye.**
  The panel is now a tall region inside a 340px rail; that it reads well at
  that width is reasoned from the utilities and asserted by no test. It is the
  most likely place for a visual surprise in this task.
- **The three `PROJECT_TRACKS` widths** are still chosen rather than measured.
  Not mine, fourth slice running.
- Nothing was committed.

## What the plan and the sibling reports got wrong

1. **`increment-c-plan.md` §3.3 says the topic dialog "becomes the MATERIAL
   `topic` facet".** It does not and should not: `regionOf('topic')` is
   `queue`, and the plan's own §2 argues a topic is a work item beside a stage.
   The slice-3b plan and my brief both quietly corrected this to "stays in
   QUEUE as a pane region"; the older document still says otherwise and is
   worth editing, because it is the one a future reader finds first.
2. **The brief's job 3 says "two class names Task A could not reach".** There
   are six, plus one already-dead modifier. The other four are `topic-status-*`
   and appear in no task's list — task A's table does not claim them and task E
   deletes the file — so on the briefs as written they would have been
   undressed silently. Same mechanism task A recorded for grouped selectors: a
   list built from one file's names misses another file's.
3. **Task C's recommendation on `!` versus `.lay-ring-inward` is accepted and
   is right**, and its three reasons all hold at the topic list unchanged. No
   correction — recorded because job 4 was a decision made above both of us and
   the measurement confirms it cost nothing.
4. **`Confirm` is a `Drawer`, so the "demodalised" panel still opens a modal.**
   That is §3.3's own design and not a defect, but anyone reading "the topic
   dialog stops being a modal" should know that the moment which writes the
   audit trail is still one.
