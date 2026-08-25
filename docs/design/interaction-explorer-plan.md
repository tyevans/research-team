# Interaction explorer — build plan

Spec: `docs/design/interaction-explorer.md`. Read it first; it holds every
decision, and a task that disagrees with it is wrong.

Six tasks in three waves. Each wave's tasks touch disjoint files.

## Wave 1

**T1 — reads on the store.** `InteractionLogReader` in
`research_team/infrastructure/persistence/interaction_log.py`: `health`,
`sessions`, `session`, `events`, `summary`. SQL over the store's own
connection for filtering and counting; medians in Python. Expose it from
`InteractionLogStore` and from `InteractionLogRunner` as `.reader`. Tests in
`tests/infrastructure/test_interaction_log_reader.py`.

**T4 — the route grammar.** `frontend/src/presentation/routing/routes.ts`:
add `{ name: 'interactions', filters }`, parse and print `#/i`, with every
filter in the query part of the hash. `viewNameOf` in `App.tsx` returns
`interactions`. Header link. Tests beside each file. No pane yet — the route
renders a placeholder.

## Wave 2

**T2 — the routes.** Five GETs in `research_team/interfaces/web/app.py` per
the spec, `interaction_reader` parameter on `create_app`, wiring in `web.py`.
Tests in `tests/interfaces/test_interaction_read_routes.py`, seeded through
`POST /api/interactions`, asserting on data.

**T3 — the data layer.** DTOs, `HttpInteractionLogRepository`, domain types,
React Query keys, container entry. Tests over a stubbed http client.

## Wave 3

**T5 — the panes.** Health strip, filter bar, summary, feed, session
drill-down. Per-kind payload rendering. Filters read and write the route.

**T6 — docs and gates.** README section, `CLAUDE.md` entry if anything was
learned, full four-gate run, PR.

## Rules every task inherits

- Four gates: `uv run ruff check .`, `uv run ruff format --check .`,
  `uv run pytest`, `cd frontend && npm run verify`. Ruff runs repo-wide.
- Never `@app.middleware("http")`.
- A test that asserts a request succeeded is not a test of a projection or a
  port. Assert on the data.
- Do not run the full pytest suite; run your own files. The controller runs
  the suite.
- Commit nothing. The controller commits.
- Report what should connect to the rest of the system that you did not wire.
