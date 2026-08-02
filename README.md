# research-team

An event-sourced coding agent with an in-memory workspace. The whole session — every
user message, every model reply, every tool call, and every file the agent writes — is
a single ordered event stream, and all state is derived by folding that stream.

The agent's filesystem is purely virtual and it has no shell, so nothing it does
escapes the process and replay is pure: refolding the log reproduces the exact
workspace, every time. The log itself is stored in SQLite, so sessions outlive the
process and can be listed and resumed.

That buys four things: time travel (rewind and fork to any point), a total audit
trail of what the agent did and in what order, a virtual filesystem with per-file
history and provenance, and resumable sessions.

## Quickstart

```bash
uv run main.py
```

You get a prompt. Type anything to send it to the agent as a turn; type a
`/`-command to inspect or manipulate the event log.

## Configuration

The model is an OpenAI-compatible endpoint, configured entirely by environment
variable:

| Variable | Default | Meaning |
|---|---|---|
| `AGENT_MODEL` | `qwen3.6-27b-mtp` | model name sent to the endpoint |
| `AGENT_BASE_URL` | `http://192.168.1.14:8080/v1/` | OpenAI-compatible base URL |
| `AGENT_API_KEY` | `not-needed` | API key; local servers usually ignore it |
| `AGENT_DB` | `~/.research-team/sessions.db` | SQLite file holding all sessions |

## REPL commands

| Command | Effect |
|---|---|
| `/files` | files in the workspace, with revision counts |
| `/cat <path>` | current contents of a file |
| `/history <path>` | every event that touched a path |
| `/diff <path>` | each recorded edit to a path, old → new |
| `/log [n]` | last `n` events (default 20), with timestamps |
| `/state` | session id, event count, turn count, file count |
| `/rewind <n>` | continue from a fork at event `n` |
| `/fork <n>` | fork at event `n` and switch to it |
| `/sessions` | every stored session, newest first; current one marked `*` |
| `/resume <n\|id>` | switch to a stored session by list position or id prefix |
| `/new` | start a fresh session |
| `/help` | the command list |
| `/quit` | exit |

Anything not starting with `/` is sent to the agent as a turn.

## How it works

One `CodingSession` aggregate owns one event stream carrying both the conversation
and the filesystem, so the ordering between "the model said X" and "file Y changed"
is total. Messages are stored as langchain's own `message_to_dict` payloads, so
there is no message schema of our own to maintain. File tools come from deepagents'
`StateBackend`: `EventSourcedBackend` overrides only its two private state seams
(`_read_files` / `_send_files_update`) plus `edit()` for intent capture, which means
line numbering, edit-ambiguity checks, glob/grep, and error strings are all
inherited rather than reimplemented. `create_deep_agent` is built with
`checkpointer=None` so LangGraph stays stateless and the event log is the sole
source of truth. A turn is atomic: all of its events append at the end, or none do —
so an interrupted or failed turn leaves the log at the last completed turn rather
than half-applied.

The log lives in SQLite. Listing sessions is a fold over `read_category`, not a
separate table we maintain. Turns are streamed with `stream_mode="values"`, which
gives both live tool-by-tool progress and the final message list in one pass.

Module map: `events.py` (event definitions), `session.py` (aggregate: commands
validate, reducers fold), `messages.py` (pure langchain conversion), `backend.py`
(the seam overrides), `runtime.py` (wiring, turn loop, `history`/`fork`/`rewind`),
`repl.py` (terminal loop and formatting).

Full design: `docs/superpowers/specs/2026-08-01-event-sourced-coding-agent-design.md`.

## Tests

```bash
uv run pytest
```

115 tests, no network. The live smoke test in `tests/test_live.py` is marked `live`
and deselected by default; run it explicitly with:

```bash
uv run pytest tests/test_live.py -m live -v
```

## Status

Working, and exercised against a real model rather than only against fakes.

On 2026-08-01, against a local `qwen3.6-27b-mtp` server at
`http://192.168.1.14:8080/v1/`, a two-turn session was driven end to end: turn one
asked for `/fizzbuzz.py` and the model emitted a well-formed `write_file` tool call;
turn two asked for a docstring and it used `edit_file`, producing a `FileEdited`
event carrying both the new content and the `old_string`/`new_string` intent.
`/history /fizzbuzz.py` then showed the two revisions, and a cold refold of the
stream through a fresh repository with no snapshot cache reproduced the live state
exactly. Rewind was verified separately: rewinding past the second write restored
the earlier file content while leaving the original stream intact and readable.

On 2026-08-02, after moving the log to SQLite, persistence was verified across two
**separate OS processes**: the first created `/greet.py` and exited; the second
started fresh, resumed the session by id, saw the file already present, and
continued the conversation — the model read the file back and edited it with full
prior context. `/diff /greet.py` then showed the docstring being added, and
`/sessions` listed the session with its turn and file counts.

No malformed tool calls were observed. Local models of this size are slow relative
to the fake-model suite — allow a minute per live turn, which is why turns now
report each tool call as it happens instead of sitting silent.

**One bug was found this way and fixed** (`e97020b`): `to_langchain` prepended a
`SystemMessage` while `create_deep_agent` was also given `system_prompt`, so the
prompt had two owners. Because LangGraph echoes back every message it is handed,
that extra leading message shifted the new-message suffix by one and each turn
recorded a spurious `AssistantMessageAdded` containing the user's own text. The
unit suite missed it because it asserted which event *types* appeared rather than
how many; reading the actual event log from a live run is what surfaced it. The
regression tests now pin the exact per-turn event sequence.
