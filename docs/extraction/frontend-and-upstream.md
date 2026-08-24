# Two extraction candidates: the frontend layer host, and what belongs upstream

Assessed 2026-08-12 against `frontend/src/presentation/layout/OverlayHost.tsx`,
its three Radix bridges, `VirtualList.tsx`, and four Python modules read beside
`~/workspace/eventsource-py` at `f6fa06b`.

Verdicts up front:

| Candidate | Verdict |
| --- | --- |
| A — `OverlayHost` + Radix bridges | **Extract into a library**, narrowly scoped |
| A — `VirtualList` | Balanced as-is (not extraction material) |
| B1 — `domain/targeting.py` | **Contribute upstream** — already filed there as P2 |
| B2 — `apply_schema` added-column reconcile | **Contribute upstream** — library already does this for its own tables |
| B3 — `application/live_feed.py` | Balanced as-is; a *narrow* upstream case for a pull-based feed iterator |
| B4 — `application/turn_supervisor.py` | Balanced as-is — app-specific, and not event-sourcing |

---

## Candidate A — the frontend layer host

### What it actually is

Strip the prose and `OverlayHost` is about 120 lines of mechanism:

1. A single portal container (`.lay-overlay-host`) at one `z-index`
   (`--z-overlay`), so paint order is mount order and there is no per-layer
   number to get wrong.
2. A mount-ordered registry of layers, each contributing only `{key, modal,
   handlersRef}`. Registration keys on identity and `modal` alone; everything
   mutable is read through a ref — the "refs-not-registry" trick that stops a
   parent re-render from silently reordering the stack.
3. Escape routed to exactly one owner: `layers[layers.length - 1]`.
4. `blocked` — `inert` + `aria-hidden` on every layer *strictly below* the
   topmost modal, plus on the page wrapper `.lay-app-root`.
5. Focus restore owed to the host, run in an effect keyed on `layers`, because
   the host's own re-render is the render that removes `inert` and
   `focus()` into an inert subtree is a silent no-op.
6. `useEscape` — a stack slot for something that isn't an overlay at all
   (`GraphDetail`, a panel laid out beside the canvas).
7. A three-line bridge contract for a third-party floating primitive: take
   `container`, portal into it, `useLayer` while open, decline the library's
   own Escape at its documented seam. `Tooltip`, `Popover` and `Menu` each do
   exactly this, unchanged.

### Does the ecosystem already solve this?

Researched across Radix, Floating UI, react-aria/React Spectrum, Base UI,
Ariakit, Headless UI, and the npm "overlay manager" genre. **No, and the gap is
specific rather than a package I missed.**

- **Radix `@radix-ui/react-dismissable-layer`** is closer than its reputation
  suggests. `DismissableLayerContext`'s *default value* holds live `Set`s and
  no provider is ever rendered, so every Radix layer in an app shares one
  de-facto global stack, ordered by mount, and only `isHighestLayer` attaches
  the (capture-phase, `document`) keydown listener. `onEscapeKeyDown` +
  `preventDefault()` is a real documented seam — the JSDoc says "Can be
  prevented" and the code is `if (!event.defaultPrevented && onDismiss)`. So
  the three bridges in this repo are pressing on a supported button, and
  `Tooltip`'s claim about Radix's stack is accurate.
  **But**: the context is not exported, `DismissableLayerBranch` and
  `useDismissableLayerSurface` register *surfaces*, not *layers*, and there is
  no public API to push a hand-rolled `Drawer` onto that stack. Radix has no
  `inert` anywhere in this path — page-blocking is `hideOthers` (the
  `aria-hidden` package) + `react-remove-scroll` + its own `FocusScope`. It
  also has no docs page at all (`/utilities/dismissable-layer` 404s).
  Source: <https://github.com/radix-ui/primitives/blob/main/packages/react/dismissable-layer/src/dismissable-layer.tsx>
- **Floating UI `FloatingTree`** is explicitly provider-scoped to one
  hierarchy of nested floating elements, not a page-wide stack; ordering is by
  event bubbling (`bubbles: {escapeKey, outsidePress}`), not a stack index.
  `FloatingFocusManager` gained `outsideElementsInert` in v0.27.0 (PR #3131) —
  the one mainstream library that will apply real `inert` — but it is opt-in,
  per-floating-element, and uncoordinated across instances.
  <https://floating-ui.com/docs/floatingtree>, <https://github.com/floating-ui/floating-ui/pull/3131>
- **react-aria** has the best AT-hiding primitive on the market and no
  dismissal authority. `ariaHideOutside` is publicly exported, ref-counted via
  a module WeakMap, keeps a module-global LIFO `observerStack`, and **already
  prefers `inert` where supported**. `ModalProvider`/`useModal` is a *counting
  tree* (`modalCount > 0`) that answers "is a modal open above me" and cannot
  answer "who is topmost". `useOverlay`'s `isDismissable` does not coordinate
  across overlays. Portal container is `UNSAFE_PortalProvider`.
- **Base UI** adds nothing global — it is Floating UI internals plus an
  `InternalBackdrop` (an SVG `clip-path` cutout div, not `inert`), and its docs
  answer stacking with z-index/`isolation` advice. The exact failure this host
  exists to prevent is an open upstream issue:
  <https://github.com/mui/base-ui/issues/2854> ("Stacking / z-index issue when
  using Base UI components inside Radix Dialog").
- **Ariakit** has the most sophisticated arbitration of the lot and it is still
  single-library: it marks the DOM tree outside an open dialog and each dialog
  declines Escape if `isElementMarked(dialog)`, with a per-event `WeakMap` memo
  and a capture/bubble document listener pair. It does use `inert`. Its answer
  for foreign overlays is `getPersistentElements` — an exemption from marking,
  i.e. coexistence, not registration. <https://github.com/ariakit/ariakit/discussions/2703>
- **Headless UI is the architecture this repo independently arrived at,
  sealed inside the package.** `src/machines/stack-machine.ts` is a
  module-global scope-keyed id stack; `use-is-top-layer.ts` is the `isTop`
  selector; `use-inert-others.tsx` sets **both** `inert` and `aria-hidden` with
  ref-counting; `use-escape.ts` is gated on `useIsTopLayer`. Registration is a
  layout effect with an *optimistic* `return true` for the not-yet-registered
  render — the same hazard this repo handles conservatively in the other
  direction with `mine >= 0`. None of it is exported.
- **The npm "overlay manager" genre is state management, not layer
  management.** `@ebay/nice-modal-react` and toss's `overlay-kit` are
  show/hide-by-id state stores that explicitly disclaim DOM and a11y concerns.
  `react-layer-stack` (9 years stale) and `react-overlay-manager` (3 years)
  are dead. The only one with real topmost logic is react-bootstrap's
  `react-overlays` `ModalManager` (`isTopModal()` gates both focus and Escape)
  — own-library only, `aria-hidden` on *direct siblings* only, no `inert`,
  unmaintained.
- **Native top layer is a rendering substrate, not a manager.** Popover API is
  Baseline Widely Available since April 2025 (~88%), and it genuinely
  eliminates z-index. It gives you no way to ask "am I topmost", no Escape
  arbitration between a top-layer element and a React overlay, and `popover`
  (unlike `showModal()`) does not inert anything. Worse for partial adoption: a
  non-top-layer overlay can never paint above a top-layer one at any z-index,
  and a popover opened after a dialog paints above it while the dialog eats the
  click. <https://www.htmhell.dev/adventcalendar/2025/1/>,
  <https://web.dev/blog/popover-baseline>

**So the honest gap statement:** every stack that exists is scoped to one
library's context or module state and is invisible to a foreign overlay. What
this host has that none of them expose is *(a)* one shared portal container so
paint order is mount order across heterogeneous sources, *(b)* Escape to
exactly one owner across a hand-rolled `Overlay`, a Radix `Tooltip` and a thing
that is not an overlay at all, *(c)* `inert` strictly below the topmost modal
with the "a confirm opened from a drawer stays live" half, and *(d)* focus
restore sequenced to when `inert` lifts.

(d) is the part I'd defend hardest, and it is corroborated: `focus()` inside an
inert subtree is a silent no-op per spec (<https://web.dev/articles/inert>), and
React's own issue tracker carries the StrictMode variant
(<https://github.com/facebook/react/issues/25979>). No library documents the
`useLayoutEffect`-vs-`useEffect` registration ordering as prose; Headless UI
encodes it in code with an optimistic fallback, and Radix compensates for plain
`useEffect` registration by broadcasting a synthetic `dismissableLayer.update`
DOM event to force re-renders.

### Verdict: extract into a library — narrowly

The extractable artefact is small and sharply bounded: **`OverlayHost`,
`useLayer`, `useEscape`, `Overlay`, and the documented bridge contract.** Call
it a layer-arbitration host. It has no opinion on positioning (Radix brings
that), no opinion on styling, and one CSS requirement (`inset: 0`,
`pointer-events: none`, one z-index).

Reasons this survives skepticism:

- The mechanism is genuinely reusable and the app-specific parts are few. The
  `--z-overlay`/`--z-toast` token names and `.lay-*` class names are the
  coupling; both are parameterisable.
- The value is disproportionately in what the file *records* rather than what
  it does. The `useLayoutEffect` argument, the refs-not-registry argument, the
  `display: contents` + `inert` caveat, the "jsdom implements `inert`'s
  presence and none of its behaviour" warning — these are four findings that
  each cost a browser session to obtain and that no library documents. A
  package is the only container that carries them to a second project.
- Adoption cost for a consumer is one provider plus an eleven-line bridge per
  floating primitive, demonstrated three times here with the bridge unchanged.

Two honest costs, and one thing to fix before extracting:

- **The "no host, no content" failure mode is the package's worst property.** A
  `Tooltip` mounted without an `OverlayHost` renders a trigger and no
  explanation, silently. That is defensible inside one app with one rule; as a
  published package it is a support burden. Extraction should add a
  development-mode warning, which this repo has no reason to want and a library
  does.
- **`blocked` is applied by the consumer, not the host**, because there is no
  single element to apply it to. The comment is right that this is forced —
  but it means the host's central guarantee is a boolean the consumer can
  forget, and the file records that being forgotten twice (`Popover`,
  `Tooltip`). A library should ship a `useBlockedProps()` returning
  `{inert, 'aria-hidden'}` so forgetting is harder than remembering.
- **Do not reimplement AT-hiding.** `ariaHideOutside` from
  `@react-aria/overlays` is publicly exported, ref-counted, has an observer
  stack for DOM mutation, and already prefers `inert`. The `.lay-app-root`
  wrapper + `display: contents` approach here is simpler and works, but the
  file itself flags the one assumption it cannot check (whether `display:
  contents` defeats `inert`). A library that ships to unknown DOM shapes should
  either lean on react-aria's implementation or ship the browser test the repo
  admits jsdom cannot provide.

Prior art to read before writing it: Headless UI's `stack-machine.ts` +
`use-is-top-layer.ts` for the cleanest model, and Ariakit's DOM-marking
arbitration — the latter is the only approach that could ever extend *across*
libraries, since the marker lives in the DOM rather than in React context.
That is worth considering as the extracted package's v2 story.

### `VirtualList` — balanced as-is

Not extraction material, and the file says why without meaning to: it is a
~60-line wrapper over `@tanstack/react-virtual` whose three justifications
(re-measured `scrollMargin`, per-row measurement with an `|| estimate`
fallback, `getItemKey`) are three correct usages of an existing library, one of
which (`|| estimate`) exists solely because jsdom reports every height as 0.
"Use the library correctly, in one place, so two call sites cannot diverge" is
a good internal wrapper and a bad package. Leave it.

---

## Candidate B — what belongs upstream in eventsource-py

### B1 — `domain/targeting.py`: **contribute upstream**

This is the strongest verdict in the report, and not on my judgement: **it is
already filed in eventsource-py's own backlog, and the entry names this repo's
mixin as the workaround.**

`~/workspace/eventsource-py/BACKLOG.md`, "`_stamp` does not check that an event
targets its own aggregate (P2)":

> The downstream consumer worked around it with a mixin that overrides
> `execute`, compares a declared target field against `self.aggregate_id`, and
> raises `CommandRejectedError` on a mismatch. That works, but every consumer
> following ADR 0056 needs it, which is the argument for it being upstream.

ADR 0056's own Consequences section concedes the gap and punts it:

> The aggregate does not verify that a command's id matches its own. […]
> Application code that accepts ids from outside should check the id it routes
> on against the id it constructs the command with, which is a check it wants
> regardless.

So the library states the hazard, declines to close it, and the app closes it —
which is the textbook shape of an upstream contribution rather than a
workaround.

The upstream home the backlog names is better than the mixin. `_stamp` already
rejects a divergent `aggregate_type` via `_reject_divergent_aggregate_type`;
this is the analogous invariant one field over, it costs one comparison, and it
needs no `target_field` declaration per aggregate because `_stamp` sees the
*event*'s `aggregate_id` directly rather than guessing which command field
named it. That is strictly stronger than the mixin: the mixin only catches
commands whose target field the aggregate remembered to declare, and it checks
the command rather than the events, so a `decide` that hardcodes a wrong id
without a command field passes.

**Skeptical counterpoint, stated so it isn't lost:** the mixin fails *earlier*
(before `decide` runs) with a message naming the command type, which is a
better developer experience than a rejection at stamp time. The two are
complementary, not competing, and the upstream version is the one that closes
the hole for everyone. Contribute the `_stamp` check; keep or delete the mixin
afterwards on ergonomics alone.

### B2 — `apply_schema`'s added-column reconcile: **contribute upstream**

The bug is exactly as `read_models.py:269` describes: `CREATE TABLE IF NOT
EXISTS` is the whole of the read-model DDL, adding `project_id` to
`SessionSummaryRow` broke every existing database, and every test passed
because tests build from nothing.

The decisive fact is that **eventsource-py already does this technique — for
its own tables only.** `adapters/sqlite/store.py::_apply_additive_updates`:

> SQLite has no `ADD COLUMN IF NOT EXISTS`, and this schema is applied on every
> first connection -- including to a file that already carries the column from
> an earlier process.

…followed by a `PRAGMA table_info` read and a conditional `ALTER TABLE …ADD
COLUMN`. That is `apply_schema`'s body, hardcoded for one column on one
library-owned table. There is a whole `adapters/sql/schemas/additive/` and
`updates/` tree for library tables. Consumer read models get
`generate_full_schema()` and nothing else — the asymmetry is the gap.

The upstream argument is also cleaner than most schema-migration arguments,
because the reasoning `apply_schema` gives is a property of read models in
general, not of this app: derived data can always be widened safely, the column
comes in empty, and a rebuild re-derives it. Only additions; a rename or retype
is a rebuild, and silently dropping data would be worse than an error nobody
can miss.

Natural home: an `ensure_schema(connection, model)` beside
`generate_full_schema` in `adapters/sql/readmodel_schema.py`, or on the
`ReadModelRepository` adapters so it happens on open. Postgres needs the
dialect branch (`ADD COLUMN IF NOT EXISTS` exists there, so it is simpler).

**Skeptical counterpoint:** a library that silently alters a consumer's table
is doing something a lot of teams want done by Alembic instead, and
eventsource-py already ships Alembic templates (`BACKLOG.md:68`). The
contribution should therefore be opt-in — a function the consumer calls, which
is exactly what `apply_schema` is — rather than something that fires inside
`SQLiteReadModelRepository.__init__`. Pitch it that way and the objection
disappears.

### B3 — `application/live_feed.py`: balanced as-is

Verdict: leave it, with a narrow upstream note.

Reading it against the library: eventsource-py has **no** `follow`,
`read_since`, or `wait_for_append`. It has `GlobalEventFeed.read_all(from_position=…)`
and `current_position()` on the store port, `Position` with `to_str`/`from_str`,
and a *push*-based `LiveRunner` that "wakes on bus notifications and delivers
events read from the global feed" with checkpointing, flow control, circuit
breakers and DLQ.

So `LiveFeed` is not duplicating `LiveRunner` — it is the pull-shaped sibling:
an `AsyncIterator` a request handler can `async for` over for the lifetime of
an SSE connection, with no checkpoint, no subscription registration, and no
handler protocol.

But the module is 79 lines and most of that is prose. The actual content:

- `encode_position`/`decode_position` are pass-throughs to the app's own
  `EventFeed`, which are themselves pass-throughs to the library's
  `Position.to_str`/`from_str` plus a `store_id` check. Nothing to extract.
- `position_now()` exists for one caller's ordering need.
- `follow()` is a while-loop, a three-way start policy (`from_position` /
  `from_start` / now), and a `wait_for_append` hint.

That is a small enough thing that "a library" is the wrong container. **The
piece with a real upstream case is `wait_for_append` as a port**, not the loop
over it. The library's `LiveRunner` gets its wake-up from an event bus; a
consumer that wants a cursor-driven pull feed has no library-blessed way to be
woken by a local append and must invent one (as `event_store.py:379` does, with
the "cleared before waiting, not after" subtlety that is easy to get wrong).
An `AppendSignal` port plus a default `LiveFeed`-shaped iterator would be a
reasonable upstream proposal — but it is a proposal, not a working thing being
lifted, so it is a smaller and more speculative contribution than B1 or B2.

Also note the app-specific part that would not travel: `read_since` in
`event_store.py` filters to a fixed set of aggregate types
(`research_team`-specific), which is deliberately at the infrastructure layer
and would have to become a parameter.

### B4 — `application/turn_supervisor.py`: balanced as-is

Verdict: keep it where it is. This is the one candidate I'd argue *against*.

It is a good module — the `asyncio.shield` split between "the turn was
cancelled" and "the awaiter went away", the bounded settle timeout, and the
`Cancellation(cancelled, settled)` pair that refuses to lie about a turn still
unwinding are all careful. But:

- **It is not event sourcing.** Nothing in it touches a store, a stream, an
  event, or a position. It is cancellable single-flight keyed on a UUID,
  wrapping a `SessionService`. Putting it in eventsource-py would widen that
  library's remit from "the event-sourcing boundary" to "async work
  supervision", and the library is visibly disciplined about that (`ports/` is
  documented as "stdlib, typing, dataclasses, datetime, uuid only").
- **The domain knowledge is the whole value.** `turn_index`, `TurnOutcome`,
  `ActivityReporter`, "half a minute of model time is not worth throwing away
  because a browser tab closed", `running_sessions()` existing for the
  cross-project roster — strip these and what remains is `dict[K,
  asyncio.Task]` with a shield, which is thirty lines anyone writes and nobody
  installs.
- **The generic version already exists.** Single-flight-per-key over asyncio is
  well-trodden; the library also already has `application/background_tasks.py`
  and a `ports/lifecycle.py`, and its locks port explicitly scopes mutual
  exclusion to "callers sharing one manager instance" — which is what this is,
  in-process.

The one thing worth mentioning to the library maintainers is a *pattern*, not
code: the version-check race this exists to pre-empt ("a second turn should be
refused before it spends a minute in the model rather than after, when the
append would lose a version check anyway") is an optimistic-concurrency
ergonomics observation that could earn a docs paragraph. That is a docs PR, not
an extraction.

---

## Summary of recommended actions

1. **Open the `_stamp` aggregate-id check upstream** against the existing P2
   backlog entry. Lowest-risk, highest-certainty contribution here; the
   library has already written the case for it.
2. **Propose `ensure_schema` / additive column reconcile for read models**
   upstream, opt-in, dialect-aware, citing `_apply_additive_updates` as the
   precedent the library already set for its own tables.
3. **Extract the layer host** as a small package: `OverlayHost`, `useLayer`,
   `useEscape`, `Overlay`, the bridge contract, plus a dev-mode missing-host
   warning and a `useBlockedProps()`. Do not extract positioning or styling.
   Consider `ariaHideOutside` rather than a hand-rolled page wrapper.
4. **Leave `LiveFeed`, `TurnSupervisor` and `VirtualList` where they are.** The
   only follow-up worth logging is an upstream `AppendSignal`-style port for
   pull-based followers.

## Sources

- Radix DismissableLayer source: <https://github.com/radix-ui/primitives/blob/main/packages/react/dismissable-layer/src/dismissable-layer.tsx>
- Radix effect-ordering/stale-closure issue: <https://github.com/radix-ui/primitives/issues/4014>
- Floating UI `FloatingTree`: <https://floating-ui.com/docs/floatingtree>; `useDismiss`: <https://floating-ui.com/docs/usedismiss>; `FloatingFocusManager`: <https://floating-ui.com/docs/floatingfocusmanager>
- Floating UI `outsideElementsInert` PR: <https://github.com/floating-ui/floating-ui/pull/3131>
- react-aria inert migration: <https://github.com/adobe/react-spectrum/issues/4313>; inert misapplication: <https://github.com/adobe/react-spectrum/issues/9364>; FocusScope restore failure: <https://github.com/adobe/react-spectrum/issues/2444>
- Base UI cross-library stacking issue: <https://github.com/mui/base-ui/issues/2854>; Base UI Dialog docs: <https://base-ui.com/react/components/dialog>
- Ariakit foreign-element escape hatch: <https://github.com/ariakit/ariakit/discussions/2703>
- React 19 `inert` prop: <https://react.dev/blog/2024/12/05/react-19>, <https://github.com/facebook/react/pull/24730>
- StrictMode breaks focus restoration: <https://github.com/facebook/react/issues/25979>
- `inert` semantics: <https://web.dev/articles/inert>, <https://samthor.au/2021/inert/>, <https://css-tricks.com/focus-management-and-inert/>
- Popover API baseline: <https://web.dev/blog/popover-baseline>, <https://developer.mozilla.org/en-US/docs/Web/API/Popover_API>
- Top-layer dialog/popover conflict: <https://www.htmhell.dev/adventcalendar/2025/1/>, <https://github.com/fortanix/baklava/issues/88>
- `@ebay/nice-modal-react`: <https://github.com/eBay/nice-modal-react>; `overlay-kit`: <https://github.com/toss/overlay-kit>; `react-overlays`: <https://www.npmjs.com/package/react-overlays>
- eventsource-py ADR 0056: `~/workspace/eventsource-py/docs/adrs/0056-decider-initial-state-is-nullary.md`
- eventsource-py backlog entry: `~/workspace/eventsource-py/BACKLOG.md`, "`_stamp` does not check that an event targets its own aggregate (P2)"
- eventsource-py additive-column precedent: `~/workspace/eventsource-py/src/eventsource/adapters/sqlite/store.py::_apply_additive_updates`
