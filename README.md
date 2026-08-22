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

A project's third page asks it about what it gathered. The answer comes from
that project's own material — its knowledge graph and the sources behind it —
and the agent cites the documents it opened rather than the ones it found by
searching. The page starts no session and appends no events: the conversation
is held in server memory, is dropped when you leave, and the tools it can reach
are an allowlist of four readers with no write and no network among them.

The agent answering that page may write an mcq, cloze, or flashcard component
into its reply instead of just prose, and the block renders and grades live in
the chat turn — a reader can attempt it right there. **Nothing about the
attempt is recorded**: there is no conversation state to hold it in, so a
refresh blanks the widget back to its unanswered form. The withholding is
weaker here than on a course file, because the answer key travels in the same
response as the block rather than behind a second request — see B105.

A project's fourth page asks a different question: **what is there to learn
here?** It folds the knowledge graph into *learning areas* — clusters of
entities the corpus actually connects — orders them into a path by which areas
the others depend on, and will write each one a course: a UbD unit plan and
numbered lesson files, in markdown, into the project's own workspace.

**The graph decides the shape and embeddings close the gaps in it.** A stated
relationship is the strongest evidence there is that two entities belong
together; two names in one passage is weaker; and an entity's nearest
neighbour in embedding space is a hypothesis no document ever made, so it is
weighted below both and drawn only above a similarity floor. What that last
channel buys is the case the graph cannot see at all: an entity nothing links
and nothing co-mentions is simply dropped from a graph-only projection, and a
semantic edge places it.

What gets embedded is the entity's **card** — its name, type, properties and
named relations, the same text the lexical index matches — rather than the
bare name. And the vectors are on the event log, so a project folds them back
at open along with the graph and the corpus. Neither was true before
2026-08-22: every vector this system computed was dropped when its process
ended, which is why a project older than that clusters on the graph alone
until you press **Embed entities**. `docs/design/learning-areas-and-paths.md`
§1 records what was fixed and which of the original arguments against
embeddings was simply wrong.

Nothing about the projection is stored. It is a pure function of a graph that
is itself folded from the log, and every view shows the entity, relationship
and passage counts it was built from — so a thin result is visible as thin
rather than merely looking like a small project. The ordering is derived too,
never asked of a model: each step carries the evidence that placed it, and
where two areas genuinely depend on each other the path says so instead of
quietly picking one.

Writing the courses is the one part that costs model turns — three per area,
run in sequence so that backward design is enforced by the arrangement rather
than requested in a prompt. The lessons they write can carry the same
interactive components the ask page uses, including the six that resolve
against this project's own graph, so a lesson quotes and links the material it
came from.

Point at your model server if it is not on the default
`http://localhost:8080/v1/`:

```bash
export AGENT_BASE_URL=http://your-host:8080/v1/
```

In the REPL, type anything to send it as a turn, or a `/`-command to inspect the
log. Every session belongs to a project, so start with `/project use <name>`.

### Working on the console

`frontend/` is a standalone TypeScript app that builds into the directory the
server mounts, so **the console has to be built once before `uv run web.py`
serves anything** — until then `/` answers 503 and says so:

```bash
cd frontend
npm install
npm run build    # what web.py serves; required once, and after any src change
npm run dev      # http://localhost:5173, proxying /api to the server above
```

The build output is *not* committed. It was until 2026-08-18, so that running
the server needed no Node toolchain; the price was that every branch touching
`frontend/src/` rewrote the same chunk files, and any two such branches
conflicted over bytes nobody reads. A merge driver and a CI staleness gate
existed only to manage that, and both are gone with it.

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
| `AGENT_INTERACTION_LOG` | `on` | capture what the console user does; set `0`/`false`/`no`/`off` to disable |
| `AGENT_INTERACTION_DB` | `~/.research-team/interactions.db` | SQLite file holding the interaction log |

**`AGENT_INTERACTION_LOG` is the only default-on boolean in this project, and
what it turns on is worth reading before turning it off.** The React console
records what a user does — navigation, dwell (with hidden tab time counted
separately), and semantic actions like search and approval decisions — and
POSTs it to a second, separate event store from the one holding sessions.
**Two fields carry text the user typed, and nothing else in the vocabulary
does: `AskSubmitted.query_text` — the research prompt itself, whatever someone
typed to ask the agent something — and `SearchPerformed.query_text`, every
entity search run in the console.** The first is the most sensitive field in
the system, and both are logged by default. Everything else is structure: ids,
view names, counts and durations, with a zero-result search recorded as its
length rather than its text. Each of the two is truncated at 4,000 characters
— roughly 700 words — so a document pasted into the ask box is stored as its
opening rather than in full.

Setting `AGENT_INTERACTION_LOG=0` removes the dependency entirely, and the
ingest route then answers 503 rather than silently accepting and discarding —
the same "unset means the route is not there" pattern `AGENT_RESEARCH_RUN`
uses. It stops collection, not the file: `interactions.db` is still created
and its schema applied, so the database existing is not evidence that the
switch failed. **The remedy for data already collected is deleting that file**
— `rm ~/.research-team/interactions.db`. Nothing reads it back and nothing
migrates it, which is what makes deleting it safe.

The log has no reader today: no read API, no browser view, nothing consumes it
yet. It exists to build a real corpus before later work designs friction
detection against it.

**[`docs/configuration.md`](docs/configuration.md) has the rest** — the graph,
vector and chunk stores, embeddings, Neo4j and pgvector, tracing, and the two
places where the obvious setting is the wrong one.

**Media search has a deployment prerequisite, not a code one.** If
`AGENT_SEARXNG_URL` points at an instance with `image_proxy` off — the
default — the media review pane's thumbnails hotlink the viewer's browser
straight to whoever indexed the image, leaking IP and referrer. Set
`image_proxy: true` in that instance's `settings.yml` before turning media
search on for anyone but yourself. Details and the measurement in
`docs/configuration.md`.

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
