# Context management


Every turn re-sends the conversation, so a session's cost grows with its
length and eventually hits the window. Four modes, chosen per instance with
`AGENT_CONTEXT`, differ in what they do about it:

| Mode | What it does | Costs | Best when |
|---|---|---|---|
| `full` | sends everything | nothing | short sessions; the default |
| `elide` | shortens older tool results, keeping the recent ones whole | nothing — pure and deterministic | the context is mostly file reads |
| `compact` | summarizes the older conversation, recording the summary as an event | one model call per compaction | the context is mostly prose |
| `delegate` | gives the agent a `worker` subagent so bulky work happens in a fresh context | more model calls, less parent context | work that would fill the log with tool output |

**Where the intervention happens matters more than which one you pick.** It
happens at the *fold* — the log always holds every message, and a strategy
decides which of them, and in what form, the model is shown next turn.

That is not a stylistic choice. Measured against this codebase, langchain's
`SummarizationMiddleware` rewrites the running message list via
`RemoveMessage(REMOVE_ALL_MESSAGES)`, and doing so silently breaks how a turn
is recorded: we identify what a turn produced by slicing the agent's returned
list at the length we sent, and rewritten history makes that slice meaningless.
Turns then land in the log missing their assistant messages and tool results —
`UserMessageSent → FileWritten → TurnCompleted`, a log claiming the agent wrote
a file with no reply and no tool call. It does not even fail loudly. Middleware
that only rewraps the outbound request is safe by the same reasoning:
`ContextEditingMiddleware` hooks `wrap_model_call`, leaves state alone, and is
what `elide` is modelled on.

`compact` records its decision as a `ConversationCompacted` event rather than
recomputing a summary each turn. So it costs one model call rather than one per
turn, two replays of a log produce the same context, and folding to a point
before the compaction shows the conversation as it was. The messages it
summarizes are never removed — only hidden from the model.

`delegate` is the odd one out: it does not transform anything. Subagents share
the backend, so a subagent's file writes are recorded on the same stream, while
its reads and reasoning never enter the parent's context. Measured here, a
delegated turn left four messages in the parent — the request, the `task` call,
the subagent's report, and the reply.

**Delegation is the mode with two-sided evidence, and it is worth knowing which
side you are on.** Anthropic reports a large quality win for a research system
of one lead plus subagents — and also that token spend alone explained most of
the performance variance, at three to ten times the tokens. Much of the win is
paying more, not organising better. Cognition argues the opposite for
*constructive* work: subagents each producing part of an artifact make
conflicting implicit decisions that the parent then has to reconcile.

That second warning applies here, because our subagents write to a shared
filesystem later turns build on. So `delegate` steers towards investigation —
reading, searching, surveying — where a subagent returns a conclusion rather
than a piece of something that has to fit with other pieces. It is the right
mode for "which of these forty files mentions X", and the wrong one for
splitting a refactor three ways.

Three choices are worth explaining, because the obvious alternative is wrong in
each case:

**Keep the `compact` trigger well above the size of one turn.** If a turn costs
a meaningful fraction of the trigger, the conversation re-crosses it almost
immediately and you pay a summarizer call every turn. The default leaves a wide
margin; a trigger set near per-turn size will thrash. A compaction that would
not actually shrink the context is refused outright — a four-section summary of
very little is bigger than the little it replaced, and recording it would
burden every later turn permanently.

**The trigger counts tool call arguments, not just message content.** A
`write_file` carries the whole file in its arguments and answers with one line
of confirmation, so counting content alone saw 224 tokens where the real
payload was nearer 2,600 — the trigger would have fired long after it should
have, or never.

**The `compact` trigger is high** (≈120k tokens). Anthropic's server-side
compaction defaults to 150k input tokens and refuses to be configured below
50k; its tool-result clearing triggers at 100k. A trigger an order of magnitude
lower costs a summarizer call on nearly every turn and discards detail that
would have fit comfortably.

**`compact` never cuts between a tool call and its result.** A result whose
call was summarized away is a malformed request — an answer to a question the
model cannot see itself having asked. The boundary snaps backwards until the
first kept message is not a tool result, which summarizes strictly more and is
therefore always safe.

**`elide` offers no way to retrieve what it cleared, on purpose.** The obvious
improvement is a handle back to the original, which the log still holds. It
would be wrong here. Every tool the agent has -- `read_file`, `ls`, `glob`,
`grep` -- is a cheap, deterministic read of an in-memory filesystem, so
re-running one costs almost nothing and returns the file as it is *now*. A
recalled result is a snapshot from an earlier turn, which may since have been
edited: it would be slower to reach for and sometimes wrong. The advice to keep
a retrievable handle comes from systems whose cleared output was expensive or
impossible to reproduce; ours is neither.

**`elide` clears a result rather than truncating it.** A cut-off head reads as
a whole result, so the model trusts it — and a half-read file or half-finished
command output is exactly how an agent concludes something succeeded when it
did not. The marker says how much was removed and that it is *not* the result.
The tool call itself is untouched, so the model can still see what it asked and
ask again, which is what Anthropic's `clear_tool_uses` does and why.
