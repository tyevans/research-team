# One helper, and two questions it makes cheap

Branch `responsive-primitive`, off `origin/main` 45a8cd5 (PR #188 merged).
Closes `BACKLOG.md` B64. Answers B62. Corrects B63.

## 0. Why this slice, and why now

`BACKLOG.md` B64 is the only entry in the file whose evidence is *repetition
across three independent authors*. Four browser test files now change viewport
width; each wrote its own resize helper; **three of the four independently
shipped the same bug** — the helper's readiness condition is already true at
the width it starts from, so it resolves on the first tick and the probe
measures the old layout.

The slice that found the third instance filed it rather than fixing it, for a
stated reason: *"it wants a slice that can change all three and prove the shared
one right."* This is that slice.

**The scope discipline:** a shared helper is only worth building if it is
adopted. A new module beside four unchanged files is worse than the four files,
because it is a fifth spelling. Every existing caller migrates in this slice or
the slice has not happened.

## 1. What is already known, and must not be re-derived

Three failed readings are on record and belong in the new helper's docstring as
the reason it polls what it polls:

1. `project-responsive.browser.test.tsx:158` — polls
   `split().style.gridTemplateColumns === ''`. Already true at 1000px, so a
   1000 -> 700 resize resolves without waiting for `matchMedia`, for `stacked`,
   or for a React commit. It works *only* crossing `--bp-wide`, and only because
   `afterEach` restores 1440.
2. A helper polling `data-collapse-to === 'rail'` — `'rail'` is the value on
   **both** sides of 1181, so a 1440 -> 821 resize satisfied it instantly and the
   probe read the 1440 layout: a three-track template and an 880px pane inside an
   821px viewport.
3. A third helper written to avoid both, in `project-stacked.browser.test.tsx`.

**The lesson, stated as a rule the helper must obey:** neither a React-written
attribute nor resolved geometry is sufficient alone. The attribute can be
stale-correct (case 2); the geometry waits on the browser rather than on React.
Poll **both**.

Two more constraints inherited rather than discovered:

- `check-deleted.mjs` forbids the identifier `gridTemplateColumns` anywhere under
  the session view. The shared helper must read
  `getComputedStyle(el).getPropertyValue('grid-template-columns')` from the
  start. Do **not** loosen the rule.
- B61: `GraphCanvas` sizes from a `ResizeObserver`, which fires *after* the
  layout it observed. Anything measuring this page after a resize needs
  `expect.poll`, not a bare read. A single read fails **against correct code**.

## 2. The fixture question, which is why this was filed as "not cheap"

The four files do not share a fixture, and that is the reason unifying the
helper is bigger than it looks:

- `project-responsive` and `project-tracks` wrap the view in a **bare 900px flex
  column**. That reproduces the pinned-height layout *by accident* and leaves no
  `.lay-surface` to ask questions of.
- `project-stacked` and `session-responsive` mount a **real `Shell`** with the
  wrapper at `height: 100vh` — a fixed pixel height detaches the shell from the
  viewport that `60vh` is measured against, and a 700x500 probe reported a 300px
  cap inside an 856px shell that had not moved.

**The ruling for this slice, made up front so no task has to guess:** the real
`Shell` at `height: 100vh` is correct and the bare flex column is not. But
**migrating a fixture changes what a test measures**, so the two older files move
onto the shared *resize helper* first and their fixtures are a separate,
explicitly-flagged decision (§3 task B item 3). If moving a file's fixture
changes any number it asserts, that is a **finding to report, not a number to
update** — the old number was measured against an accidental layout and the new
one is real, and which is which must be written down rather than silently
swapped.

## 3. Tasks

### Task A — build the primitive, adopt it in one file

Owns: the new shared module, and `project-tracks.browser.test.tsx`.

1. Write the shared module (suggested `src/test/browser-viewport.ts`; if a
   test-helper location already exists, use it rather than inventing one —
   check first). It exports at minimum a resize helper that takes a width and
   height, and returns only once **both** a React-written attribute and the
   resolved geometry agree with the requested width.
   - The docstring carries the three failed readings from §1 as the reason.
   - Read grid templates via `getPropertyValue('grid-template-columns')`.
   - It must work crossing `--bp-wide` in **both** directions and crossing
     `--bp-narrow` in both directions. The old helpers each worked in one.
2. **Red-prove it**, and this is the task's most important deliverable: mutate
   the helper to a single poll (attribute only, then geometry only) and watch a
   probe read the wrong viewport. Report the actual wrong numbers, not "it
   failed". If a single poll turns out to be sufficient, say so — that is a
   finding against this plan and it is wanted.
3. Migrate `project-tracks.browser.test.tsx` onto it, deleting its local
   `resize`. Every claim in the file must still pass, and the file's assertions
   must not be edited to make that true. If a number moves, stop and report.

### Task B — migrate the remaining three

Owns: `project-responsive`, `project-stacked`, `session-responsive`.

1. Migrate all three onto the shared helper; delete all three local helpers. No
   file may keep a private resize helper when this task is done.
2. For each file, **re-prove one existing red claim** against the migrated
   version, so the migration is shown not to have made the file vacuous. A file
   whose tests pass because the helper now returns too early is exactly the
   failure this slice exists to prevent, and it looks identical to success.
3. **The fixture decision** (§2): report, for each of the two bare-flex-column
   files, whether moving to a real `Shell` would change any asserted number.
   *Measure it; do not migrate it.* The migration, if wanted, is a follow-up
   with its own red proofs. File it.

### Task C — the two questions the primitive makes cheap

Owns: a new browser file, and `BACKLOG.md`.

1. **B62 — the drawer below 820.** Open a drawer at 800x900 and read
   `getBoundingClientRect().width` against the viewport. The two outcomes are
   opposite and both are plausible: the stylesheet wins and the drawer is full
   width, or Tailwind wins and it is a 360px strip pinned right on an 819px
   screen. The reasoning in B62 says the stylesheet wins
   (unlayered beats layered) — **that is a prediction, and this project has
   shipped a defect off exactly that substitution once.** Measure it. If the
   prediction is right, the entry closes with a measurement rather than an
   argument; if wrong, it is a live defect and the fix is in scope.
2. **B63 — correct the premise.** B63 says the research view is a third view
   mounting a `Split` and is unmeasured below 821. Grepped on 2026-08-14:
   `<Split` appears in exactly two files, `ProjectView.tsx:277` and
   `SessionView.tsx:122`. The route merge folded research into the project
   view's MATERIAL pane, so there is no third `Split`. **Do not simply close it
   as wrong** — establish what *is* unmeasured: whether MATERIAL rendering
   research content (a `Selection`) below 821 behaves like MATERIAL rendering
   whatever the current stacked fixture puts there. Measure that, then rewrite
   B63 to say what was actually open.
3. Close B64 with the measurement. Update B61's note if the shared helper
   changes the polling advice it gives.

## 4. Ordering

A first and alone — it owns the module both other tasks import. B and C both run
the browser suite, so they are **strictly serial** after A. No two vitest
processes at once, ever.

A owns `project-tracks`; B owns the other three; C owns the new file and
`BACKLOG.md`. They must not swap.

## 5. Global constraints

- Four gates: `uv run ruff check .`, `uv run ruff format --check .`,
  `uv run pytest`, `cd frontend && npm run verify`. Plus `npm run test:browser`,
  which is not a gate and is the whole point of this slice.
- Never two vitest processes at once.
- Every new claim is proved red, or its docstring says it would pass against
  unfixed code and why it is worth having anyway.
- A number that moves is a finding, not an edit.
- Comments say when something was measured rather than reasoned.
