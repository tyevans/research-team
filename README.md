# research-team

An in-memory, event-sourced coding agent. The whole session — every user message,
every model reply, every tool call, and every file the agent writes — is a single
ordered event stream, and all state is derived by folding that stream. Nothing is
written to the real disk and the agent has no shell, so replay is pure: refolding
the log reproduces the exact workspace, every time. That buys three things at once:
time-travel (rewind and fork to any point), a total audit trail of what the agent
did and in what order, and a virtual filesystem with per-file history and provenance.

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

## REPL commands

| Command | Effect |
|---|---|
| `/log [n]` | last `n` events (default 20) |
| `/files` | files in the workspace, with revision counts |
| `/cat <path>` | current contents of a file |
| `/history <path>` | every event that touched a path |
| `/rewind <n>` | continue from a fork at event `n` |
| `/fork <n>` | fork at event `n` and switch to it |
| `/state` | session id, event count, turn count, file count |
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
source of truth. A turn is atomic: all of its events append at the end, or none do.

Module map: `events.py` (event definitions), `session.py` (aggregate: commands
validate, reducers fold), `messages.py` (pure langchain conversion), `backend.py`
(the seam overrides), `runtime.py` (wiring, turn loop, `history`/`fork`/`rewind`),
`repl.py` (terminal loop and formatting).

Full design: `docs/superpowers/specs/2026-08-01-event-sourced-coding-agent-design.md`.

## Tests

```bash
uv run pytest
```

88 tests, no network. The live smoke test in `tests/test_live.py` is marked `live`
and deselected by default; run it explicitly with:

```bash
uv run pytest tests/test_live.py -m live -v
```

## Status

Working. The live smoke test was run once against a local `qwen3.6-27b-mtp` server
at `http://192.168.1.14:8080/v1/` on 2026-08-01 and **passed in 48s**: asked to
create `/fizzbuzz.py`, the model emitted a well-formed `write_file` tool call, the
backend recorded a `FileWritten` event, and the resulting workspace contained a
fizzbuzz file. No malformed tool calls were observed. Local models of this size are
slow relative to the fake-model suite — allow a minute per live turn.
