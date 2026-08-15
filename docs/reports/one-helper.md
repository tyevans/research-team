# One helper, and two questions it makes cheap

2026-08-14, branch `responsive-primitive` off `origin/main` 45a8cd5. Closes
`BACKLOG.md` B64 and B62, corrects and closes B63, re-aims B61, files B67.

## The headline: the bug this slice fixes is one animation frame wide

`BACKLOG.md` B64 was the only entry whose evidence was *repetition across three
independent authors*: four browser test files change viewport width, each wrote
its own resize helper, and three independently shipped the same defect — the
helper's readiness condition is already true at the width it starts from, so it
resolves on the first tick and the probe measures the old layout.

The shared helper reproduces that on demand. Single-poll mutants at
`{ interval: 1 }`, resizing 1440 → 821:

```
grid-template-columns = "344px 342px 352px"     <- three tracks, sum 1038
data-collapse-to      = rail
material = 1038                                 <- a 1038px pane in an 821px viewport
```

The full helper returns at `344px 476.984px`, inline style empty.

**And then the honest part, which is a finding against the plan I wrote.** That
stale window is **one animation frame**. Run at `expect.poll`'s 50ms default,
both single-poll mutants read *correctly* on every resize tried. The brief said
"watch a probe read the wrong viewport"; that oversold how easily it reproduces.

What a single poll is, precisely: **unguarded, with scheduling standing between
it and that 1038px reading** — not reliably wrong. Both historical failures were
found by a person noticing a number rather than by a test going red, which is
exactly what an unguarded window looks like from outside. The caveat is in the
module docstring in full, so the next reader who tries to reproduce it and fails
does not conclude the helper is pointless.

Only `1440 → 821` lags at all. Four other resizes — including the reverse
`821 → 1440` — were settled at frame 0. The asymmetry is recorded and was not
chased.

## Why one helper needs four polls

| poll | signal | decisive for |
| --- | --- | --- |
| 1 | inline template present iff `width >= 1181` | crossing `--bp-wide`, either direction |
| 2 | `data-collapse-to === 'strip'` iff `width < 821` | crossing `--bp-narrow`, either direction |
| 3 | the split's box width rounds to `width` | resizes *inside* a band, where no attribute moves |
| 4 | tracks + gaps fit `clientWidth`, or `flex-direction: column` | a stale template on a correctly-sized box |

Polls 1 and 2 are the two React-written signals, and **each is constant across
the other's boundary** — which is precisely the hole both historical helpers fell
through, each working in one direction only.

The cheapest illustration of the whole entry: `project-tracks`' local helper was
**correct for that file**. Every resize there is 1440 ↔ 1181, inside the wide
band, where neither attribute changes and box width is the only signal that
moves. Right, and unreusable.

## Adoption was the deliverable, not the module

A shared module beside four unchanged files is a fifth spelling. All four
migrated; `widen()`, `stack()`, `at()` and `resize()` are deleted, and four
byte-identical `afterEach` viewport restores are now `afterEach(restoreViewport)`.
**No file in the repository keeps a private resize helper.**

No assertion was edited and no number moved. Each migrated file re-proved one
existing red claim, and **all four failures are byte-identical to the ones their
docstrings record** — which is the check that matters, because a file whose tests
pass because the helper returns too early looks identical to success.

### What the shared poll cost, and what was rejected

Poll 4 turned one recorded red proof into a timeout: `expected 300 to be greater
than or equal to 320` — which names the number — became `expected 'pending' not
to be 'pending'`. Under that mutation 600 + 300 genuinely never fit 821, so a
correct readiness signal becomes unsatisfiable for a stylesheet that overflows.

Fixed as a message, not as a poll:

```
Received: "at 821px the tracks overflow the split: "600px 300px" = 900px in a clientWidth of 821px"
```

Strictly more than the original proof, which named only the column that lost.

**Rejected: teaching poll 4 to tell a stale template from an overflowing
stylesheet** so it could fail fast rather than time out. It cannot, from one
sample — both look like tracks that do not fit — and distinguishing them means
holding state across polls for a case costing one timeout that is now diagnosed
by the message anyway. **The timeout survives; only the message improved.**

## B62 — the prediction held, so this ships a confirmation

The drawer below 820 is **full width**. At 800×900 with the document reader open:
`left 0, right 800, width 800`, computed `width 800px, max-width none,
min-width 0px`. The stylesheet wins, `Drawer.tsx:155-163`'s comment is correct as
written, and no code changed.

Worth a test anyway, because the inverse is one selector away — renaming
`.drawer` in the below-820 block gives:

```
AssertionError: expected 360 to be 800
```

`min-w-[360px]` beating `w-[42vw]`'s 336: a **360px strip pinned to the right of
an 800px screen**, a narrower panel on a narrower screen, on the one size the
rule was written to serve. The correct behaviour rests entirely on one unlayered
rule keeping its selector, so the claim asserts the box *and* three computed
longhands — moving `.drawer` into a `@layer`, deleting it, or adding a `!` to the
utilities each turns one line red with the real number.

Not measured, and said in the entry rather than implied: the 820 boundary itself.

## B63 — the premise was wrong, and the entry records the correction

B63 claimed the research view was a third view mounting a `Split`, unmeasured
below 821. `<Split` appears in exactly **two** view files. The route merge folded
research into MATERIAL's `doc` and `entity` tabs; there is no third split.

What was genuinely open once the premise was fixed is narrower and real:
`project-stacked` measures the band with `selection={null}`, leaving MATERIAL on
the `artifact` tab — a plain `overflow-auto` panel. The `doc` tab is a
**virtualizer**, which owns a scroll container, and `ProjectView.tsx:499`
deliberately gives that panel no `overflow-auto`. An inner scroller swallowing
the offered height is the same shape as the defect the below-821 rule exists for,
one level in.

Measured at 700×900: it does not happen. `surface 1558 / 856`, panes 578.5 /
401.4 / 578.5. Red-proved under the same `layout.css` mutation the sibling
records, failing byte-identically.

**The number that differs is recorded rather than reconciled.** The sibling
records MATERIAL at 148.0; here it is 578.5, because the corpus takes its
content's height where the empty artifact list took its head's — and that 430px
is the entire 1558-vs-1128 gap. A claim asserting the sibling's 1128 would have
been asserting the sibling's *fixture*.

Left open deliberately: the `entity` tab. `GraphCanvas` is `React.lazy` over a
canvas sized by a `ResizeObserver` that fires after the layout it observed (B61),
and folding it in would have smuggled B61's problem into B63's closure.

## The fixture question — measured, filed, not done (B67)

Every **width** is byte-identical between the bare-900px-flex-column fixture and
a real `Shell` at `height: 100vh`, at every width and in every collapse state.
Only heights and tops move, by exactly the chrome's 44px.

So `project-tracks` would migrate free. But `project-responsive` claim 2 computes

```ts
const topRow = 900 - 0.46 * 900   // 486
```

where that `900` is the **viewport** height standing in for the **pane column's**
height — equal only because the bare wrapper is itself 900 tall. Under a `Shell`
the column is 856 and the honest floor is **462.24, not 486** — and the claim
would keep passing (measured 706.97 clears both) while being arithmetically
wrong. That is plan §2's "a number measured against an accidental layout", found
for real, and it was reported rather than edited. Filed as B67 with the follow-up
shape.

## Two findings on the helper, neither worked around privately

- **`resizeViewport` requires a `.lay-split` to exist.** B62 does not inherently
  need one, and a bare `Drawer` fixture cannot use the shared helper at all. Task
  C used the real project view with the real drawer over it — better fidelity
  anyway — and reported the gap instead of writing a sixth private helper, which
  is the exact thing this slice exists to end. Arguably "wait for the split" is
  the wrong question on a page with no layout to settle, rather than a missing
  feature.
- **A modal drawer makes the page behind it `inert`**, so the sibling files'
  readiness signal is never *visible* to a locator and `toBeVisible()` times out
  against a page that rendered perfectly. Any future file mounting a view with an
  overlay open hits this. Commented at the call site.

## Verification

| Gate | Result |
| --- | --- |
| `uv run ruff check .` | passed |
| `uv run ruff format --check .` | 235 files already formatted |
| `uv run pytest` | **2422 passed**, 9 deselected, 219s |
| `cd frontend && npm run verify` | full chain — 35 deletion rules hold, 21 stylesheets frozen |
| `npm run test:browser` | **25 files / 82 tests** (from 24/80) |

`app` unchanged at **72.6 kB of 80**; the new module is test-only and
`vite.config.ts` excludes `src/test/**` from coverage, because the browser suite
collects none and the module would otherwise ratchet the global ratio down by its
own weight.

Two stylesheet mutations for red proofs were reverted and verified clean by
`git diff`; the failure screenshots the red runs wrote were deleted.

## Left undone, deliberately

- **Poll 4's timeout.** A file whose stylesheet overflows still waits it out and
  still fails at the helper rather than at its own line. Only the message
  improved.
- **The fixture migration (B67)** — measured, not performed. It needs claim 2's
  constant rederived from the split's own height and re-proved red.
- **The `entity` tab below 821**, and **the 820 boundary itself**.
- **Finding 2's asymmetry** — why only `1440 → 821` lags — is unexplained rather
  than merely unmeasured.
