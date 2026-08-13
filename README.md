# research-team

An event-sourced agent for building courses. Every user message, model reply,
tool call and file write is one ordered event stream, and all state is derived
by folding it.

That buys four things you cannot retrofit: **time travel** — rewind or fork to
any point; a **total audit trail** of what the agent did and in what order; a
**virtual filesystem** with per-file history and provenance; and **resumable
sessions**, because the log is SQLite and outlives the process.

The agent's filesystem is virtual and it has no shell, so nothing it writes
escapes the process. Two tools reach the network and both are off or gated by
default: `web_search` is not registered at all without `AGENT_SEARXNG_URL`, and
`fetch` defaults to `ask`, so it cannot reach anything until a person approves
that call. `tests/integration/test_no_network.py` and `test_no_shell.py` pin
both claims. Results are recorded as ordinary events, so a session refolded
years later reproduces exactly — even if the search instance is long gone.

## Quickstart

Two front ends over the same SQLite log. A session started in one opens in the
other.

```bash
uv run main.py       # terminal REPL
uv run web.py        # http://127.0.0.1:8000
```

The web console is where time travel becomes visible: a timeline you can scrub
to any point (the workspace refolds — no fork, no write), per-file diffs of each
recorded edit, and the fork lineage as a tree. New events reach every open
browser over SSE.

Point at your model server if it is not on the default
`http://localhost:8080/v1/`:

```bash
export AGENT_BASE_URL=http://your-host:8080/v1/
```

In the REPL, type anything to send it as a turn, or a `/`-command to inspect the
log. Every session belongs to a project, so start with `/project use <name>`.

### Working on the console

`frontend/` is a standalone TypeScript app, built and committed into the
directory the server mounts — so `uv run web.py` needs no Node toolchain.
Changing it does:

```bash
cd frontend
npm install
npm run dev      # http://localhost:5173, proxying /api to the server above
npm run build    # rebuilds what web.py serves; commit the result
```

`frontend/README.md` has the layering and the three files carrying most of the
subtlety.

## Configuration

Everything is an environment variable. The ones a first run actually needs:

| Variable | Default | Meaning |
|---|---|---|
| `AGENT_MODEL` | `qwen3.6-27b-mtp` | model name sent to the endpoint |
| `AGENT_BASE_URL` | `http://localhost:8080/v1/` | OpenAI-compatible base URL |
| `AGENT_API_KEY` | `not-needed` | API key; local servers usually ignore it |
| `AGENT_DB` | `~/.research-team/sessions.db` | SQLite file holding all sessions |
| `AGENT_WEB_HOST` / `AGENT_WEB_PORT` | `127.0.0.1` / `8000` | where the web UI binds |
| `AGENT_SEARXNG_URL` | *(unset)* | SearXNG base URL; unset means no search tool exists |
| `AGENT_CONTEXT` | `full` | `full`, `elide`, `compact` or `delegate` |

**[`docs/configuration.md`](docs/configuration.md) has the rest** — the graph
and vector stores, embeddings, Neo4j and pgvector, tracing, and the two places
where the obvious setting is the wrong one.

Durable backends need nothing beyond `docker compose up -d`; the schema is
created on first project open. Both defaults keep everything in-process.

## REPL commands

| Command | Effect |
|---|---|
| `/project` | every project, with its id |
| `/project new <name>` | create a project |
| `/project use <name>` | start a session inheriting the project's files — the only way to start one |
| `/files` | files in the workspace, with revision counts |
| `/cat <path>` | current contents of a file |
| `/history <path>` | every event that touched a path |
| `/diff <path>` | each recorded edit to a path, old → new |
| `/log [n]` | last `n` events (default 20) |
| `/state` | session id, event count, turn count, file count |
| `/rewind <n>` | continue from a fork at event `n` |
| `/fork <n>` | fork at event `n` and switch to it |
| `/sessions` | every stored session, newest first |
| `/resume <n\|id>` | switch to a stored session by position or id prefix |
| `/autonomy [tool] [level]` | show, or set a gated tool to `auto`, `ask` or `deny` |
| `/research [n]` | work this project's topic queue autonomously |
| `/checks` | per-check fire rate, override rate and time-to-decision |
| `/health` | whether the session list's projection is healthy |
| `/rebuild` | derive the session list from the log again; safe at any time |
| `/help`, `/quit` | |

Anything not starting with `/` is sent to the agent as a turn.

## Autonomy and approvals

Gated tools have three levels: `auto` runs it, `ask` interrupts the turn for a
person, `deny` refuses without asking. Read-only tools are not gated — there is
nothing to approve about a read. A change takes effect on the *next tool call*,
including one made partway through a running turn, and a pending approval can be
answered from either front end.

`fetch` floors at `ask` and configuration cannot lower it. That is what makes an
unattended run read-only: a loop that tried to reach the network would deadlock
on an approval nobody is there to answer.

## Projects and the knowledge graph

A session is one conversation. A **project** is a set of sessions sharing a
filesystem lineage and a knowledge graph, one at a time — `/project use` starts a
session that inherits the project's files where the last one left them, and
refuses if another session holds it. That inheritance is forking applied across
sessions, which is why a project's filesystem still folds out of one event
stream and time travel still works on it.

Three tools make the graph: `remember` extracts entities and relationships from
text and records them permanently, `unmerge` reverses a consolidation the
matcher got wrong, and `graph_search` reads it back. The first two are gated,
because both change what every later session sees.

The graph is not a second source of truth — it is a projection folded from the
same log, rebuilt whenever a project opens, and costing nothing to lose.
Extraction runs once, when `remember` is called; what it produced is what
replays thereafter. So a project reopened years later reproduces the same graph
without depending on a live model call.

**One thing to be exact about:** content passed to `remember` leaves the process
to be extracted, reaching the same model endpoint every turn already uses. With
`AGENT_GRAPH_STORE=neo4j` the graph leaves too, and with embeddings on — the
default — every extracted entity's name is sent to an embedding endpoint.

## Autonomous research

A **run** works a project's topic queue without anybody typing. One round is one
topic and one turn.

```
> /research          # until the queue empties or the budget stops it
> /research 5        # capped at five rounds
```

Ctrl-C stops it after the round it is in, rather than leaving a turn
half-written. The same is available over HTTP only when `AGENT_RESEARCH_RUN=1`
is set; without it those routes are absent and answer 404 — not 403, which would
tell an unauthenticated caller there is a research loop here.

**A run cannot decide it is finished.** Every stop reason is a fold of its own
stream or of the queue: `queue_empty`, `max_rounds`, `no_new_findings`,
`error_rate`, `cancelled`. There is no `agent_decided_it_was_done`, because a
model asked whether it has finished says yes fluently, and a loop that believes
it terminates early and reports success. For the same reason progress is counted
by folding the topic before and after the turn rather than by reading the reply:
a round that describes a breakthrough and records nothing is an empty round.

## Tests

```bash
uv run pytest
```

No network. `tests/` mirrors the source layout, plus `tests/integration` for the
cross-layer ones. Two suites are deselected by default:

```bash
uv run pytest -m integration      # needs docker-compose.test.yml
uv run pytest tests/integration/test_live.py -m live -v
```

CI runs four gates, and passing three is not passing: `ruff check`,
`ruff format --check`, `pytest`, and `cd frontend && npm run verify`.

## Where to read more

| | |
|---|---|
| [`docs/configuration.md`](docs/configuration.md) | every environment variable, and the costly defaults |
| [`docs/design/architecture.md`](docs/design/architecture.md) | the four layers, the decider, concurrency, what the live feed can and cannot show |
| [`docs/design/context-management.md`](docs/design/context-management.md) | the four context modes, and why the obvious alternative is wrong three times |
| [`docs/design/interactive-components.md`](docs/design/interactive-components.md) | widgets in course markdown, and learner progress |
| [`docs/direction.md`](docs/direction.md) | what is worth building next, what is not, and why |
| [`BACKLOG.md`](BACKLOG.md) | deferred work, in enough detail to pick up |
| [`CLAUDE.md`](CLAUDE.md) | the rules that hold across all of it |
