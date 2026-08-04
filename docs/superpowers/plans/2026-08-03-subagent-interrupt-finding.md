# Finding: `interrupt_on` reaches subagent tool calls

**Question.** Does `create_deep_agent(interrupt_on=...)` on the parent gate a
tool call made by a delegated `worker` subagent (via the `task` tool), or only
the parent's own tool calls?

**What was run.** A throwaway probe (`/tmp/probe_subagent_interrupt.py`, not
committed) built two independent agent graphs, each with its own
`ToolAwareFakeChatModel` instance(s) so response queues could not be consumed
out of order between the two cases:

- **Control**: a parent agent (`create_deep_agent(interrupt_on={"write_file":
  {"allowed_decisions": ["approve", "reject"]}}, checkpointer=MemorySaver())`)
  whose scripted model calls `write_file` directly.
- **Subagent case**: the same `interrupt_on` and checkpointer, but with
  `subagents=[WORKER]` (`research_team/infrastructure/agent/delegation.py`),
  where the `worker` has its own scripted model. The parent's scripted model
  calls `task` to delegate to `worker`, whose scripted model then calls
  `write_file`.

Both used `EventSourcedBackend(session)` built from a bare `CodingSession`
aggregate (`CodingSession(uuid4())`, then `.start(...)`), the same backend the
production `DeepAgentTurnExecutor` uses.

**Control result.** `astream` yielded `__interrupt__` naming `write_file` with
the parent's args. Confirms the probe and `interrupt_on` wiring are sound.

**Subagent result.** `astream` also yielded `__interrupt__` naming
`write_file`, this time with the worker's args (`/worker.txt`). Crucially, the
write did **not** land: `session.state.files` was empty after the interrupt.
A follow-up run resumed the same thread with
`Command(resume={"decisions": [{"type": "approve"}]})`, and the file then
appeared in `session.state.files` (`['/worker.txt']`) — the gate is not just a
notification, it genuinely blocks the subagent's tool call until a decision is
supplied, exactly as it does for the parent.

**Consequence: subagent file writes DO gate — Task 8 needs no extra work.**

`interrupt_on` on the top-level `create_deep_agent` call reaches tool calls
made inside a `task`-delegated subagent, because the interrupt is raised by
the `HumanInTheLoopMiddleware` wrapping the shared graph's tool-execution step,
not by anything scoped to which agent issued the call. The parent's
`interrupt_on` is sufficient; no per-subagent `interrupt_on` (a field
`SubAgent` also happens to support) is required for this case.

**Notes for later tasks (the real resume loop).**

- A `checkpointer` is mandatory to resume at all — `checkpointer=None`
  produces `__interrupt__` in the stream but `Command(resume=...)` then raises
  `RuntimeError: Cannot use Command(resume=...) without checkpointer`. Use a
  real checkpointer (e.g. `MemorySaver`, or whatever this codebase's
  production checkpointer ends up being) and a `config` carrying a stable
  `thread_id` across both the initial `astream` and the resuming `astream`.
- The resume payload shape is `Command(resume={"decisions": [{"type":
  "approve"}]})` — a dict with a `"decisions"` list, not a bare list of
  decisions. Passing a bare list raises `TypeError: list indices must be
  integers or slices, not str` deep in
  `human_in_the_loop.py:after_model` (it does `interrupt(hitl_request)["decisions"]`).
  One decision object per pending `action_request`, in order.
- The interrupt payload's `action_requests[].name` is the tool name regardless
  of whether the call originated in the parent or a subagent — there is no
  marker distinguishing "this interrupt came from inside a `task` call" other
  than inspecting the surrounding message history/state for the `task` call
  that's still in flight. If a later task needs to show the user *which*
  agent (parent vs. worker) is asking, it will need to derive that from
  context, not from the interrupt payload itself.
- `session.state.files` (i.e. the `EventSourcedBackend`/aggregate) is a
  reliable way to assert whether a gated write actually happened yet — it
  stayed empty across the entire interrupted period and only picked up the
  file after the approving resume.
