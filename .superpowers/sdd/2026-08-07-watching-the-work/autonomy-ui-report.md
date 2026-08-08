# The autonomy UI — two surfaces, one policy

Frontend half of "say how much rope the agent gets, from the web". Builds
against `autonomy-api-report.md`; nothing here hardcodes a tool list.

## Where each control lives

**The allow-all control is in the drawer**, immediately under `<Approvals>` in
`frontend/src/presentation/course/WorkerDrawer.tsx` — that is where the pain is,
and a person answering the same approval for the fifth time should not have to
navigate to a settings surface to make it stop.
`presentation/course/AutonomyAllowAll.tsx`. It renders **two buttons, not one
with a checkbox**:

- *Allow everything except the review gate* → `allow-all` with
  `include_stage_gates: false`
- *Also allow the review gate* → the same route with `true`, quiet tone, its own
  tooltip

A checkbox left ticked from a previous visit is precisely the accident that
matters here, so the stage-gate path is a separate press. Both buttons disable
when there is nothing left for them to move — `gatedNotAuto.length === 0` and
`stageGatesStillAsking(policy).length === 0` respectively, both computed from
the server's `gated`/`stage_gates`.

**The full per-tool panel is on the course page**, a `<section
className="autonomy-panel">` sibling to `Workers` and `RunPanel` in
`CourseView.tsx`. `presentation/course/AutonomyPanel.tsx`. One row per entry in
`gated`, in the server's order, each a `<fieldset>` of radios (arrow-key
traversal, an announced legend, and a selected state, none of it
reimplemented). It is a sibling rather than a pane inside the course because
the policy is instance-wide — it is no more a property of this project than the
run is — and burying it under a workflow the project may not have would hide it
exactly when somebody is looking for it.

## How the instance-wide warning is worded

Both surfaces render the same string, from `presentation/course/autonomy-copy.ts`:

> **This applies to every session on this instance, not just this one. The
> change is recorded on the session you make it from.**

One sentence for scope, one for the audit asymmetry. It lives in a shared module
because two controls over one policy that describe its scope differently teach
the reader that one of them is lying and give them no way to tell which — so
wording drift here is a correctness bug, not a style question. It is rendered on
the control (`.autonomy-warn`, accent left border) rather than in a tooltip, and
above the switches rather than once at the top of a page the reader may have
scrolled past.

The stage-gate sentence is in the same module:

> `advance_stage` **left asking on purpose: it is the workflow review gate, the
> point where a person looks at what was produced before the run builds on it.
> Auto-ing it lets a run cross every stage boundary with nobody looking.**

Shown after a default allow-all — so the untouched `advance_stage` reads as a
decision rather than a half-failed request — and on the gate's own row in the
panel, where it also carries a "review gate" chip and a `--k-tool` left border.
`advance_stage` can still be set to `auto` in the panel, one deliberate click at
a time; what it cannot be is swept along by "allow everything".

## How the two surfaces are kept consistent

One query key and one hook. `queryKeys.autonomy()` is deliberately
unparameterised — no session, no project — because the policy is one object
serving the whole process, and keying it by either would give the drawer and the
panel separate caches over the same state that disagree the moment either wrote.

`application/autonomy/use-autonomy.ts` is the only reader and writer. Every
write `setQueryData`s the returned full policy **and** invalidates: the seed
makes the flipped switch appear without a round trip, the invalidation covers
the case the API report warns about (another tab wrote in between, so any *other*
observer's map is stale). A test shares one `QueryClient` across both components
and asserts the panel shows `fetch: auto` after the drawer's allow-all, having
issued no request of its own.

Writes need a session for the audit record. The drawer has one; the panel is
handed `course.data?.holdingSessionId ?? null` and, when that is null, renders
the levels read-only with *"No session is attached here, so there is nothing to
record a change against"* rather than firing a request that would 404. A policy
change with no trace makes every surrounding decision unreadable, so no session
means no write, not a quiet one.

## Honesty cases handled

- **400** — `HttpAutonomyRepository` does not catch it. `HttpClient` lifts
  `detail`, and the panel renders it verbatim in a `role="alert"`:
  `unknown autonomy level: 'sometimes'`. Nothing this side could reconstruct
  which value was rejected.
- **404 (no policy wired)** — told apart from any other read failure via
  `ApiError.isNotFound` and rendered as *"This build does not expose an autonomy
  policy…"*. Never as an empty set of switches, which would imply nothing is
  gated.
- **An unknown level** — `level` is `z.string()`, and `levelsToOffer` appends a
  server-reported level this build does not know, so selecting it is not
  one-way and the current setting is never "nothing selected".
  `levelMeaning` describes it as unfamiliar rather than mislabelling it.
- **A tool in `gated` with no level** — `levelOf` returns null and the row says
  the build was not told, rather than defaulting to `ask` and inventing a safety
  claim nobody made.
- **`changed`, not `levels`, is reported** — "Changed 2 tool(s): …", so the UI
  never claims eight changes where the person made one.

## Files

New: `domain/autonomy/autonomy.ts`, `application/autonomy/use-autonomy.ts`,
`infrastructure/http/autonomy-repository.ts`,
`presentation/course/autonomy-copy.ts`,
`presentation/course/AutonomyPanel.tsx`,
`presentation/course/AutonomyAllowAll.tsx`,
`presentation/course/AutonomyPanel.test.tsx`.

Touched: `application/ports/repositories.ts` (`AutonomyRepository`),
`application/queries/keys.ts`, `app/container.ts`,
`infrastructure/http/dto.ts` (`autonomyDto`, `autonomyChangeDto`),
`infrastructure/http/mappers.ts` (`toAutonomy`, `toAutonomyChange`),
`presentation/course/CourseView.tsx`, `presentation/course/WorkerDrawer.tsx`,
`presentation/course/WorkerDrawer.test.tsx`, `styles/course.css`.

CSS uses only existing `tokens.css` custom properties — no new literal colours.
`.autonomy-panel` repeats `.worker-panel`'s three declarations so it reads as
another band of the same page; `.autonomy-allow` borrows `.extraction`'s
indent-behind-a-rule language because it likewise belongs to the thing above it.

## Two notes on tests

`AutonomyPanel.test.tsx`'s fixture invents a gated tool called `zip_files`. Any
assertion that depended on the real `GATED_TOOLS` would fail against it, which is
the point.

Its fake repository holds **one mutable policy** rather than returning a fixed
one. `useAutonomy` invalidates after every write, so a fake whose `read` always
answered the starting policy would undo each write one refetch later — the tests
would be asserting against a server that contradicts itself.

`WorkerDrawer.test.tsx` needed a `QueryClientProvider` and a `container.autonomy`
now that the drawer contains this control, and its policy fixture leaves a tool
asking so the buttons render *enabled* — an all-auto policy would disable them
and the Tab-trap tests would pass by excluding the buttons rather than including
them. One existing test, "includes approval buttons in the Tab trap", asserted
membership by treating a Reject button as the last focusable element; it now
asserts membership directly, since the autonomy control renders below the
approvals and "last" is no longer an approval button.

## Commands run

```
$ npx vitest run
Test Files  30 passed (30)
     Tests  324 passed (324)

$ npm run typecheck
tsc --noEmit && tsc --noEmit -p tsconfig.node.json      (clean)

$ npm run lint
eslint . --max-warnings 0                               (clean)

$ npm run format:check
All matched files use Prettier code style!
```

`npm run build` was **not** run and nothing under
`research_team/interfaces/web/static/` is committed, per instruction.

## Tests added (11)

Panel: renders one control per tool from `gated` (proved with an invented tool);
a level change calls the session-scoped route and reflects the returned levels;
a 400 surfaces the server's `detail` verbatim; a 404 says the build has no
policy instead of showing empty switches; no session renders read-only with a
reason and issues no write; an unknown server level is offered and described as
unfamiliar. Allow-all: leaves `advance_stage` at `ask` and explains why, while
reporting only `changed`; the separate control autos it and drops the exclusion
sentence. Both: the instance-wide warning appears on each in identical words;
one shared `QueryClient` shows the same state on both after a write. Drawer: the
control renders beside the approvals with its warning.
