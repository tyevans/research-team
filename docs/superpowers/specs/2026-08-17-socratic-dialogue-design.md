# Socratic dialogue

A guided conversation that leads a reader toward understanding by questioning
rather than answering. The reader names a topic; the system sets a goal, asks,
responds to what the reader says, and stops when the reader has demonstrated
the thing — not when the reader stops typing.

**It is its own experience, not a markdown widget.** A widget lives inside one
answer, and this is the answer. That decision is the user's and is treated here
as binding; what follows is what it costs.

## 1. The two facts that decide the architecture

**Build on the ask machinery. The session machinery is disqualified, and by one
line of domain code rather than a preference.** `JoinProject`
(`domain/project.py:283-293`) matches only when `active_session_id is None`, so
a session that joins a project takes it **exclusively**. A reader in a dialogue
would lock the author out of their own project. The weaker alternative
(`session_service.py:465-468`) gives no holder and no inherited filesystem, at
which point almost nothing of the session machinery remains. `ask.py:3-6`
already made this argument for the ask surface; it transfers verbatim.

**But the ask aggregate cannot be re-prompted into this.**
`AskConversationState` (`ask_conversation.py:97-108`) is four fields —
`conversation_id`, `project_id`, `status`, `turns`. There is nowhere to put a
goal or a stopping condition, and nothing in it can express "this dialogue is
trying to reach X and has not yet". A stopping condition **is** state.

So: a `SocraticDialogue` aggregate alongside `AskConversation`, reusing the SSE
frame vocabulary, the executor shape, the activity plumbing, the two-table
projection pattern, and the frontend's streaming repository and transcript
fold. The reuse is real and large; what is genuinely new is the state.

## 2. The bug this surface may not inherit

**An evicted ask conversation resumes with no history, on a fresh stream.**
`ConversationRegistry` is 64 entries / one hour idle, and
`Conversation.conversation_id` is minted per registry entry
(`ask.py:100-115`). The spec that built it explicitly declined a read-through
cache, and for an ask that is an accepted cost — a dropped chat is a lost
convenience.

**For a goal-directed dialogue it is a correctness problem.** A reader who
comes back after lunch to a dialogue that has forgotten its goal, its progress
and its stopping condition has not resumed anything; they have started over
while believing otherwise. So a socratic dialogue **resumes from its own read
model**, not from the registry: the registry stays a live-turn cache, and a
miss rehydrates `history` and the dialogue state from stored turns rather than
minting a new stream.

This is the single largest piece of new machinery in the spec, and it is not
optional. Stated plainly because the cheap version — reuse the registry as-is —
looks identical until an hour has passed.

## 3. The identity question, answered narrowly

BACKLOG B33 records that `LearnerProgress` keys on a session, because a session
is the only identity in this codebase meaning "one person working through this
material". That is why the ask attempts route grades but **records nothing**
(`app.py:3129-3133`), and why a refresh blanks the widgets.

A stopping condition is a claim about what a reader has demonstrated, so this
surface cannot avoid the question the ask path was allowed to skip.

**The dialogue is its own principal.** A `SocraticDialogue` has a durable id,
survives eviction (§2), and means exactly "one reader working toward one goal"
— which is the thing `LearnerProgress` needs and an ask does not have. So
progress keys on the dialogue id.

This answers B33 **for this surface only**, deliberately. It does not decide
what an ask should do, and it must not be generalised into one on the way past:
the reason it works here is the durable, goal-scoped identity, and an ask has
neither half.

The payoff is the part worth having: **this is the surface where the components
can finally be graded and remembered.** A socratic dialogue that asks an `mcq`
and records the attempt can use the answer as evidence toward its stopping
condition, which is the whole point of having a stopping condition at all.

## 4. The agent

**The prompt is already a parameter.** `DeepAgentAskExecutor.__init__`
(`ask_agent.py:178-186`) takes `system_prompt: str = ASK_PROMPT` and passes it
straight into `create_deep_agent`. A differently-prompted agent over the same
streaming plumbing costs one constructor argument.

**Compose the socratic prompt from the pieces; do not concatenate onto
`ASK_PROMPT`.** `ASK_PROMPT` is *rebound* at `ask_agent.py:133` to include
`ASK_COMPONENT_PROMPT`, which now carries the full reference for eight
component types — measured at 7,947 characters as of the data-bound components
work. Building a socratic prompt by appending to it inherits all of that
silently, including the five resolved types, whether or not a dialogue should
offer them.

**Which components a dialogue may author is a deliberate choice, not an
inheritance** — the same defect `COMPONENTS_FOR` was just fixed to avoid. The
first release offers `mcq` and `cloze`: they are gradeable, and grading is what
feeds the stopping condition. `flashcards` and the five resolved types are not
offered initially, not because they are wrong but because nothing in a dialogue
yet uses them.

**What is not injectable, and is therefore scope:** the tool allowlist
(`READ_ONLY_TOOLS`), the file tools, and `CITED_BY_TOOL` are module constants
filtered with no injection point (`ask_agent.py:34-41,60,78`). If a socratic
agent needs a different tool set, that is a parameter to add, not a refactor —
but it is work, and the allowlist's shape is deliberate (an allowlist, so a
tool added to `open_graph` later is excluded until someone names it).

**Composition is single-instance.** `composition.py:1923-1939` builds one
executor inside one `AskService`, closing over `open_graph` assembled from that
build's stores. A second, differently-prompted executor is a few lines there
plus a parameter on `create_app`. Not a refactor; not free either.

**No langgraph-level memory to hang a state machine on.** The agent is built
fresh per question with no checkpointer (`ask_agent.py:229-238`) — a
`MemorySaver` was tried and raised because `astream` passes no `thread_id`.
Continuity lives in `history`, which is fine, but the dialogue's *state* must
therefore live in the aggregate rather than in the agent. That is the right
place for it anyway: a stopping condition decided inside an LLM's context is a
stopping condition nothing can test.

## 5. Shape of the domain

- **Events**: `SocraticDialogueStarted` (`project_id`, `topic`, `goal`,
  `stopping_condition`, `opened_at`), `SocraticTurnRecorded` (`prompt`,
  `reply`, `citations`), `SocraticProgressObserved` (what the reader
  demonstrated, and the evidence — a graded attempt or the model's assessment),
  `SocraticDialogueConcluded` (`reason`: `met` | `abandoned`).
- **State**: the ask's four fields plus `goal`, `stopping_condition`,
  `observations`, `status: new | started | concluded`.
- **Read model**: the two-table pattern (`AskConversationStore`'s shape), with
  `position` **stored rather than inferred** — the ask read model records that
  a read leaning on insertion order breaks under `rebuild()`.

A turn records only on success, as `AskTurnRecorded` does: the event is a fact
about an exchange that happened, not an attempt that was made.

**The goal and the stopping condition are set once, at the start, by the
model** from the reader's topic — and are then **visible to the reader**. A
dialogue whose goal the reader cannot see is a quiz pretending to be a
conversation, and a reader who disagrees with the goal should be able to see
that they disagree before spending twenty minutes on it.

## 6. Frontend

Cheap, and measured: a new place on a project is one entry in `FACETS`
(`routes.ts:67`) and one arm in `regionOf`, which is **total over `Facet` by
design, so a new facet fails to compile until it is registered**
(`ProjectView.tsx:60-63`). A full-page experience adds one intercept line in
`App.tsx:151`, exactly as `ask` does.

A dialogue with a durable id has a **better** claim to a URL segment than an
ask does — the ask facet deliberately selects nothing — and the grammar already
supports it unchanged. This is the one part of the wave that is genuinely
inexpensive.

## 7. Scope of the first release

In: the aggregate, its projection, resumption from the read model (§2), a
second prompted executor, the route and SSE stream, the facet and view, goal
and stopping condition visible to the reader, and `mcq`/`cloze` gradeable
in-dialogue with attempts recorded against the dialogue id.

Out, deliberately:

- **Changing the tool allowlist.** The first dialogue uses the ask's read-only
  tools.
- **Generalising B33.** Progress keys on a dialogue id here and nothing else
  changes.
- **Any multi-reader notion.** One dialogue, one reader; there is no principal
  below the dialogue and inventing one is a bigger question than this surface.
- **Resuming a dialogue in a *different* project.** The aggregate carries
  `project_id` and that is the boundary.

## 8. The risk worth stating before building

`docs/research/research-intake.md:305` argues *against* an agent-run
elicitation loop, and part of it transfers: a bad follow-up question is
expensive, and noticing a hesitation — the thing a human tutor steers by — is
exactly what an async text interface removes. The mitigation here is that the
goal and the stopping condition are explicit, visible and testable, so a
dialogue that is going badly is legible to the reader rather than merely
tedious. That is a mitigation, not a refutation, and if the first release feels
like a quiz, this is the paragraph that predicted it.

## 9. Testing

The four gates plus the fifth (`research_team/interfaces/web/static` is a
committed build artefact).

- **Schema evolution**: new events must be readable against payloads an older
  build stored — `tests/infrastructure/test_schema_evolution.py` is the file
  that enforces it.
- **The projection must be constructed.** CLAUDE.md's "Events" section records
  that an event no projection handles counts as APPLIED, not rejected, so a
  missing subscription is a silently EMPTY read model answering 200. The
  assertion must be that a **row exists with the value the event carried**, not
  that the request succeeded — an earlier feature's tests "confirmed the
  endpoint worked" while `EntityDefinitionRunner` was never constructed in
  `composition.py`.
- **Resumption is the test that matters** (§2): a dialogue evicted from the
  registry and resumed must carry its goal, its stopping condition and its
  prior turns, and must record onto the **same** stream. Write it first; it is
  the requirement whose absence looks exactly like working software for an
  hour.
- **Read models against a database that predates the change** — a copy of a
  real one, via
  `uv run python -m research_team.infrastructure.persistence.local_copy`.
  "It works on my fresh database" is the sound of the bug CLAUDE.md documents.
