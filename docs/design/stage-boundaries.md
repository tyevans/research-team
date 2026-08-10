# Where a stage ends

Read out of the working tree at `research_team/domain/project.py`,
`research_team/application/session_service.py`,
`research_team/application/stage_exit.py`,
`research_team/application/autonomy.py`,
`research_team/application/auto_research.py`,
`research_team/application/topic_dispatch.py`,
`research_team/infrastructure/agent/workflow_tools.py` and
`research_team/composition.py` on branch `main` (at `f88dfba`, after #74).
Line numbers are pointers, not contracts — several of these files are being
edited concurrently by other work in flight, so check before trusting one.

This document answers one proposal from the repo owner: **stop directing the
agent to `advance_stage`, tell it that ending its turn advances the stage, and
have a running workflow start the next stage's turn by itself.** It sits beside
`workflow-engine.md`, whose §3 argued the opposite of part of this and whose
§3.1 driver this both keeps and amends. Where the two disagree, this document
says so by name rather than quietly winning; `landing-page.md` §8 is the
convention and the reason for it.

**How the load-bearing claims were checked.** Most of what follows turns on
what happens *when*, and ordering is the easiest thing here to assert from a
docstring that is out of date — #74 corrected exactly such a docstring in
`gate_review`. Each claim below was read out of the code named:

- *Nothing is durable before a turn ends.* `SessionService._run_turn`
  (`session_service.py:670`) builds one aggregate, and `_save_turn` (`:742`) is
  the only call that appends. Every failure arm discards the aggregate and
  appends a lone marker on a freshly loaded one. #74 verified the other half —
  `DeepAgentTurnExecutor` is constructed with no repository — and I did not
  re-verify it.
- *The advance is a single forward step and nothing else is expressible.*
  `_advanced` (`project.py:293`) computes `ids[at + 1]` and raises for
  everything else, including going back. `StageAdvanced` (`project.py:82`) has
  `from_stage`, `to_stage`, `decided_by`, `gate_decision` and no decision value.
- *Nothing switches session when a stage advances.*
  `grep -rn 'release_project\|start_in_project' research_team/` returns
  `topic_dispatch.py`, `topic_seeding.py`, `interfaces/cli/repl.py` and
  `interfaces/web/app.py`, and no workflow code at all. §2.3 is about what that
  means for a sentence #74 shipped.
- *Every stage in every shipped preset declares at least one output.*
  Walked `PRESETS` for a stage with an empty `outputs`; there are none across
  `ubd.pure` (6 stages), `addie.pure` (12) and `hybrid.default` (15). §3.4 is a
  rule for a case that does not currently arise, and says so.
- *The one existing route to an unattended stage gate.*
  `AutonomyPolicy.relax_all(include_stage_gates=True)` (`autonomy.py`), reached
  from `AllowAll` in `web/app.py`. `TOOL_FLOORS` floors `advance_stage` at
  `ask`; `level_for` takes the stricter of default and floor, and an explicit
  `set` beats both.

**What I did not check, and cannot.** Nothing here has been run. There is no
driver, no stage has ever been driven, and the prompts that would make a stage
produce anything are being written concurrently by other work. Every timing
claim is an ordering read off the code, not an observation of a run. **The
whole suite passing carries no information about any of this** — `CLAUDE.md`
on read models, and `landing-page.md` §8 for what "it works on my fresh
database" cost the last time. Where I say a test would fail, I mean a test that
does not exist yet.

Short version, so the rest reads as argument rather than suspense:

- **The owner is right about the direction and wrong about the mechanism.**
  Moving the advance decision to *between* turns is correct and fixes three
  things at once. "Ending the turn advances the stage" is not the way to say
  it, because it is false in the cases that matter and a false prompt is worse
  than a missing one. §2, §5.
- **Turn-end is when the advance is *evaluated*, never when it is *taken*.**
  A turn can end from success, from the model running dry, from a failure, or
  from a cancellation, and three of those four must not advance anything. What
  advances a stage is an exit condition computed over committed state. §3.
- **The human stands at the boundary, between turns, and the default is
  attended.** One decision per boundary — the same count as today, 5 for
  `ubd.pure` and 14 for `hybrid.default` — but for the first time made against
  work that is committed and visible. §4.
- **This closes B36 structurally rather than working around it.** The gate is
  posed after the turn that produced the evidence, so the artifacts are in the
  store and the file viewer answers. The `gate_context` extension B36 proposes
  is still worth having and stops being load-bearing. §4.3.
- **The unattended course the owner wants is one existing HTTP route away, and
  always was.** `relax_all(include_stage_gates=True)` is built, deliberate, and
  logged as `AutonomyChanged`. The architecture should stop treating autonomy
  as something a driver grants and start treating it as something an operator
  has already decided. This is the amendment to `workflow-engine.md` §3.2. §4.4.
- **`StageAdvanced.decision` goes from "cheap and worth doing" to "required
  before this ships".** Once a runner writes `gate_decision`, that field stops
  being about the human at all, and the human's verdict has nowhere to live. §7.2.
- **The runner is `DispatchRun.run` with a stage where the topic is.** Fresh
  session per unit of work, `release_project` in a `finally`, one holder at a
  time — all shipped, all tested, all pointing the right way. §6.

---

## 1. What the boundary is for, restated before it is moved

`workflow-engine.md` §3.2 puts this as strongly as it can be put, and it is
worth agreeing with in full before proposing to move the machinery, because
the temptation in a document like this is to weaken the guarantee by relocating
it and call that a design.

The stage boundary is the guarantee the workflow engine exists to provide. Its
content is: **an artifact produced without the stage that was supposed to
constrain it looks identical to one produced with it.** That is `_advanced`'s
own argument for refusing a skip, and it is the reason a structural check
cannot substitute for the boundary — every check in the registry is a graph or
schema query, so a well-formed artifact of the wrong provenance passes all of
them. `workflow-engine.md` §4.4 works that failure through in detail and it is
the most expensive thing in this system to get wrong.

Two consequences hold under any redesign, including this one:

**A stage may only be left by a route that produces a recorded human
decision,** unless a human has previously and explicitly said otherwise in a
way that is itself recorded. That is what `TOOL_FLOORS`' floor buys and what
`relax_all`'s exclusion of `STAGE_GATE_TOOLS` protects.

**A component that could lower its own gate makes the gate advisory.** Stated
in `auto_research.py`'s module docstring for the research loop — "a loop that
could lower its own floors would make `TOOL_FLOORS` advisory" — and it is the
same rule here. Nothing in this document proposes a runner that writes the
autonomy policy.

What §3.2 additionally forbids is a driver holding a repository and calling
`Project.execute(AdvanceStage(...))` directly: no tool call, no approval, no
interrupt, no `ToolCallDecided`, and — checked — no existing test that would
fail. **That prohibition is where this document and `workflow-engine.md` part
company, and §4.4 is the argument.** The short form: §3.2 identified the right
hazard and closed it in the wrong place. It closed *who may execute the
command* when the property that matters is *what must have happened before the
command is executed*. Those coincide today only because the tool is the sole
caller.

## 2. What is actually wrong with stage gating as assembled

Three problems, and they are separable. It matters that they are, because the
owner's proposal fixes all three and only one of them needs the part of the
proposal that is wrong.

### 2.1 The gate fires while its own evidence is uncommitted

`advance_stage` floors at `ask`, so the interrupt is raised *before* the tool
body runs, which is before `_attempt` executes `AdvanceStage`, which is inside
a turn that has appended nothing. `_save_turn` is the only thing that writes,
and it runs after the executor returns. So at the instant the reviewer is asked
whether this stage's work is finished, **none of that work exists anywhere the
reviewer can look.** `GET /api/sessions/{id}/files` loads from the store and
answers with the state before the turn.

#74 established this and corrected a docstring in `gate_review` that had
claimed the opposite ("in the log and in the viewer immediately") for some
time. B36 carries the workaround: put the artifact contents into `gate_context`
so the evidence travels with the request even though it is not yet stored.

This is the problem the owner is really pointing at, and the fix is structural
rather than a workaround: **if the decision is made between turns, the evidence
is committed before the decision is posed, and the file viewer already works.**
Nothing has to be shipped inline to make the gate see; the gate simply happens
later.

### 2.2 The stage's exit condition is decided by the model

Today the only thing that can propose a boundary is the model calling
`advance_stage`. Its own `rationale` is what a reviewer reads. `WORKFLOW_PROMPT`
tries to constrain this — advancing is "for when this stage's outputs exist,
not for when the model has run out to say" — and a prompt is a tendency.

Meanwhile `stage_exit.review_stage` is pure over the course directory, needs no
approval in flight, runs 21 implemented checks and costs no model call. And
`stage_artifact_paths(preset, stage)` derives from the preset alone exactly
which files the stage owes. **The two facts that decide whether a stage is done
are computable, and the current design asks the model instead.** That is the
inversion worth fixing, and it is independent of when the turn ends.

### 2.3 The fresh session #74 promised does not exist

#74 added this to the tool's success prose:

> This turn ends here, so that the transition is durable before anything is
> built on it and the next stage starts from a fresh session rather than
> inheriting this one's conversation.

The first clause is true and enforced by `EndTurnOnStageAdvance`. **The second
is not implemented.** Nothing in the workflow path calls `release_project` or
`start_in_project`; a human whose agent just advanced types their next message
into the same session, which still holds the previous stage's entire
conversation. The turn broke; the session did not.

This is not a criticism of #74 — the sentence is a description of what the turn
boundary is *for*, and #74 shipped the half it owned. It is a note that the
promise is outstanding, that the runner is the first thing that could keep it,
and that the mechanism to keep it is already built and used twice (§6.2).

## 3. What signals "this stage is done"

**Turn-end cannot mean it, and this is the crux of the owner's proposal being
right in direction and wrong as written.**

A turn ends for four reasons and they are not the same event:

| Turn ended because | Should the stage advance? |
|---|---|
| The model wrote the stage's artifacts and stopped | Yes, if a reviewer agrees |
| The model ran out of things to say | No |
| The turn raised, and `_record_failure` appended a marker | No |
| A human cancelled it (`TurnSupervisor.cancel`) | No, emphatically |

Nothing in a `TurnOutcome` distinguishes the first from the second. A model
asked whether it has finished says yes fluently — `auto_research.py`'s module
docstring already refuses to trust that for the research loop, on the grounds
that "a loop that trusts that terminates early and reports success" — and a
turn that simply stops is a weaker signal than prose, not a stronger one.

### 3.1 The exit condition

**A stage is a candidate for advancing when, computed over the committed
aggregate after a turn:**

1. **Every path in `stage_artifact_paths(preset, stage)` exists** in the
   session's files. This is `workflow-engine.md` §3.1's artifact-presence
   condition, unchanged, and it is the reason `stage_artifact_paths` documents
   its one-file-per-declared-output rule as "what makes a missing artifact a
   detectable gap rather than something nobody can tell was supposed to exist".
2. **Each of those files parses**: `parse_frontmatter` returns a mapping, and
   the mapping names the `ArtifactType` the output declared. A file present but
   unreadable is the case `StageReview.unreadable` already reports, and it is
   worth failing the condition on rather than passing it and letting the
   reviewer find out.
3. **`review_stage(preset, stage, files)` produces no invariant failure.**
   `StageReview.blocked` is that predicate and it exists. Invariants are the
   two failures `stage_exit.py` describes as invisible in the output, and its
   argument for refusing rather than asking applies verbatim here: handing one
   to a reviewer "converts an invariant back into advice, and hands them a
   judgement with nothing to look at".

Non-invariant findings — blocking, advisory — do **not** fail the condition.
`stage_exit.py` is explicit that findings inform and do not block, and that a
pipeline refusing to advance on an advisory finding "teaches people to switch
checks off". They travel to the reviewer in `gate_context`, which is what they
already do.

### 3.2 What this condition is not

**It is necessary and it is not sufficient, and the design must not pretend
otherwise.** A model can write four files at the declared paths, with correct
frontmatter, naming the right artifact types, that pass every structural check
and are nonsense — `workflow-engine.md` §4.4 is the detailed version and the
short version is that all 21 checks are graph and schema queries. Presence
plus checks says *the shape is right*. Nothing computable says the content is.

This is the single strongest argument in this document for keeping a human at
the boundary by default, and it is worth stating plainly because it cuts
against what the owner is asking for. **The exit condition is good enough to
decide when to ask, and not good enough to decide instead of asking.**

### 3.3 Relation to `workflow-engine.md` §3.1

§3.1 proposed artifact-presence as the driver's *stop* condition: the driver
starts a turn "when the previous turn ended and the stage's declared artifacts
are not all present", and stops when they are. That is kept and its role
changes. Under §3.1 the condition ends the driver's involvement and a human
picks the run back up. Here it **triggers the gate**, and the driver's
involvement continues past an approval into the next stage.

The addition is item 3, the invariant check. §3.1 already has the driver
running `review_stage` between turns and feeding findings back — "the single
highest-value thing a driver does, and it costs nothing" — so the machinery is
in §3.1's design already; this only makes one class of its output decisive.

### 3.4 Two cases the condition gets wrong on its own

**A stage with no declared outputs is satisfied immediately.** Every stage in
all three shipped presets declares at least one output, so this does not arise
today — but `stage_artifact_instructions` handles the zero-output case
explicitly ("This stage produces no artifact of its own"), a `FieldStage` has
neither generator nor critic and per `workflow-engine.md` §2.3 "an agent cannot
execute it at all". The rule: **a stage with no declared outputs is never
advanced by the runner.** It is a human's stage, the run stops there, and the
human advances it with `advance_stage` by hand (§5). Writing the rule now costs
one branch; discovering it later costs a preset that silently skips a stage.

**The condition is satisfied the instant the runner starts, if the stage was
already worked by hand.** A human who wrote the artifacts in a session and then
started a runner would have the gate posed before any turn ran. That is
arguably correct — the work is done — but it is surprising, so the runner
should evaluate the condition before its first turn and pose the gate rather
than running a turn that has nothing to do. Say it in the code, because the
alternative reads as a bug.

## 4. Where the human stands, and what it costs

### 4.1 The recommendation

**Per-stage approval, between turns, against committed artifacts. Attended by
default. Unattended reachable only by the operator's existing, recorded,
explicit act.**

Concretely, the runner's loop for one stage:

```
loop:
  evaluate exit condition over the committed aggregate
    invariant failure       -> stop the run, report the refusal    (§3.1.3)
    not satisfied           -> start another turn, findings in     (§4.5)
    satisfied               -> pose the gate                       (below)

pose the gate:
  ask through the ApprovalPort, with gate_context carrying the review
    approve                 -> execute AdvanceStage, release the
                               session, start the next stage in a
                               fresh one                           (§6.2)
    reject / respond        -> stop the run and hand back to the
                               human, with their message           (§4.6)
```

The count of human decisions is unchanged: one per boundary, five for
`ubd.pure`, eleven for `addie.pure`, fourteen for `hybrid.default`.
`workflow-engine.md` §3.2's corollary stands — "that is not a limitation of the
driver; it is the product" — and §7 of that document is right that fourteen
real reviews, not eighty model calls, is the actual price of a course.

**What changes is not how often the human is asked but what they are looking
at.** Today: a model's rationale, a findings summary carried inline, and a file
viewer showing the state before the turn. Under this: a committed course
directory, the same findings, and a file viewer that answers. That is the
argument for between-turns being a *better* place for a human than mid-turn,
and it is a better place for exactly one reason — it is the first moment there
is something to review.

### 4.2 The mechanism, and the one new thing it needs

The runner is not a model and has no tool call to intercept. The approval path
that exists is wired into the agent harness: a gated tool call raises an
interrupt, `GateReviewer` supplies context, `ApprovalPort` poses it, and
`ToolCallDecided` records the answer. **A runner proposing a boundary between
turns is outside all of that.**

Two ways to close it, and the cheap one is defensible:

**(a) The runner poses an `ApprovalRequest` with `tool_name="advance_stage"`
and `args={"rationale": ...}`, then executes `AdvanceStage` only on an
approve.** No new port, no new event, and `ToolCallDecided` records something
true: it *is* a decision about an `advance_stage` call, made by a human,
against arguments — the only difference is who proposed it. `decided_by` stays
`human` or `policy` and means what it says.

**(b) A `StageGate` port and a new event.** More honest about the fact that no
tool was called, and it is a new name in the permanent vocabulary, a new thing
for projections to know, and a second path to the same decision. Rejected on
`workflow-engine.md` §3.4's principle: new events are for facts the existing
ones cannot carry, and this one they can.

Take (a), with one non-negotiable constraint: **asking and advancing must be
one function, and `Project.execute(AdvanceStage(...))` must appear in exactly
one place in the runner.** A test asserting that — grep-shaped, over the
application layer — is the thing that keeps §3.2's real guarantee once §3.2's
literal rule is amended. `workflow-engine.md` §3.2 asked for a test that drives
a stage to completion and checks no `StageAdvanced` was appended; the amended
version of that test is *no `StageAdvanced` was appended without a
corresponding approval*, which is strictly stronger and is the one worth
writing.

### 4.3 B36 mostly evaporates

B36 exists because the gate is posed against uncommitted evidence, and it
proposes carrying artifact contents inline in `gate_context` as the cheap fix.
Under this design the gate is posed after `_save_turn`, so:

- The artifacts are in the store. `GET /api/sessions/{id}/files` answers.
- The `check-findings` artifact `review_stage` writes is in the store too.
- The durability half of B36 — which #74 explicitly rejected as breaking
  `run_turn`'s all-or-nothing guarantee and disturbing #69's retry baseline —
  is not needed and nothing about `run_turn` changes.

What remains worth doing is smaller and is a UI job: the reviewer should be
handed the *list* of paths this stage produced, so they do not have to know
where to look. That is `gate_context` gaining `artifact_paths`, four lines, no
contents, no new invariant.

**B36 should be reworded rather than closed**, because its diagnosis is right
and its scope shrinks. Not done in this PR; this document proposes only itself.

### 4.4 The amendment to `workflow-engine.md` §3.2

§3.2 says a driver may never make the stage boundary pass without a human, and
closes two routes: `relax_all(include_stage_gates=True)`, and executing the
domain command directly. The second is what this design does, deliberately.

**The reconciliation is that §3.2 protected the right property through the
wrong invariant.** The property is: *no stage advances without a recorded human
decision, unless an operator has recorded a standing decision that it may.*
§3.2 achieved it by making the tool the only caller. That is sufficient and it
is not necessary, and it has a cost §3.2 does not price: it makes the model the
only thing that can propose a boundary, which is §2.2's inversion.

The amended rule, which I would append to `workflow-engine.md` as a new section
rather than editing §3.2 — the `landing-page.md` §8 convention, and §3.2's
reasoning stays readable because it is most of this document's foundation:

> **A component may execute `AdvanceStage` if and only if it has, immediately
> beforehand and in the same function, obtained an approval through
> `ApprovalPort` for that advance, or observed that the operator has set
> `advance_stage` to `auto`.** It may never write `AutonomyPolicy`. The
> prohibition in §3.2 on calling `Project.execute(AdvanceStage(...))` is
> narrowed to this: the hazard was an advance with no decision behind it, not
> the identity of the caller.

Note what the second clause admits. **`advance_stage` at `auto` means the
boundary passes unattended, and that is already true today** — it is what
`relax_all(include_stage_gates=True)` does, it has an HTTP route (`AllowAll` in
`web/app.py`), `autonomy.py` argues at length for keeping it, and every level
change is recorded as `AutonomyChanged`. A runner that reads the policy and
respects it is not creating that capability; it is the first thing that would
*use* it.

So: **the unattended course the owner wants is a configuration the operator
already has, not an architecture this design has to invent.** The honest
statement of the default is that a runner asks at every boundary, and an
operator who has said "I am the review" gets a run that does not ask — because
they said so, once, on the record, at a route with a name.

**Where I would not go, and think the owner should not either:** a runner flag.
An `attended=False` parameter on the runner would be a second place that
decides the same thing, disagreeing with `AutonomyPolicy` sooner or later, and
it would be the thing a caller sets without the recorded act. `TOOL_FLOORS` is
already the one answer to "may this happen without me". The runner should have
no opinion.

### 4.5 The unattended case still has a floor

Even at `advance_stage: auto`, the invariant refusal in §3.1 item 3 stands: an
invariant failure stops the run without asking anyone, because `stage_exit.py`
is right that there is nothing there for a human to weigh either. So the fully
unattended run is not unbounded — it stops on a self-reviewing critic or an
uncited verdict, which are the two failures that would otherwise produce a
course claiming reviews it cannot evidence.

### 4.6 A rejected gate stops the run

When the reviewer says no, the stage stays and the run stops. The human's
message becomes available as the next turn's input if they resume by hand.

The alternative — feed the rejection back and try again — is a loop with a
convergence policy in it, which is `LoopPolicy` reimplemented in process state,
which `workflow-engine.md` §3.4 refuses and `ResearchSupervisor`'s docstring
refuses before it. It is also the version that spins: a reviewer who rejects
twice for the same reason is telling you the run is not the thing that will fix
it.

Stopping is cheap to change later and hard to unwind if wrong in the other
direction.

## 5. What `advance_stage` becomes

**Kept, exactly as the owner says, and its job narrows to three things it is
genuinely the best answer for.**

**1. The runner's own route to the boundary.** Under §4.2(a) the runner poses
an approval named after this tool and executes the same command it executes.
The tool's `_attempt`, its four refusal arms, its already-at-final-stage
message and its not-a-stage-of-this-preset message are the vocabulary for that
whether or not a model is in the loop.

**2. The model's way of saying "I am done early", which the exit condition
cannot express.** A stage whose artifacts are deliberately not all produced —
a `FieldStage`, a stage a human has decided to leave partly empty, a preset
edited mid-run — never satisfies §3.1. Without the tool such a stage is
enterable and not leavable, which is the exact failure
`composition.py`'s `- {ADVANCE_STAGE_TOOL}` comment already argues against
("a stage that claims a tool list… would be enterable and not leavable").

**3. A human working a session by hand, with no runner at all.** This is how
the system works today and it must keep working. It is also §5 of
`workflow-engine.md`'s whole first increment: "a human prompting six stages by
hand is how you find out whether the prompts are any good". A runner that
made the manual path impossible would break the only way anyone can currently
evaluate a prompt.

### 5.1 #74's change stays correct, and becomes more so

`EndTurnOnStageAdvance` ends the turn on a successful advance and not on a
refused one. Under this design that is not merely still right — it is what
makes the two routes to a boundary converge. A model that calls the tool ends
its turn; the runner regains control at the same place it regains control after
every other turn; the stage has moved and the next stage starts in a fresh
session by the same code path. Without #74, a model-initiated advance would
leave the runner holding a turn that had crossed a boundary mid-flight, and the
runner would need a second story for it.

The `_refused`/`_advanced` split is what makes that possible and should be
treated as load-bearing rather than an implementation detail of #74.

### 5.2 The prompt, and where the owner's wording is wrong

The owner proposes telling the agent that ending its turn will advance to the
next stage, and making that the preferred path. **The intent is right and the
sentence is false**, in three ways that all matter:

- Ending the turn advances nothing if the artifacts are not present.
- Ending the turn advances nothing if a check invariant failed.
- Ending the turn advances nothing if the reviewer says no.

A prompt that states a mechanism the system does not implement is worse than
one that omits it, and this repository has already paid for that once — the
`gate_review` docstring #74 corrected asserted a visibility that never existed,
and it misled for months. A model told "ending your turn advances the stage"
that then finds itself still in the same stage has been given a false model of
its own situation, and the cheapest thing it can conclude is that its
instructions are unreliable.

**The nearest good version**, which gets the behaviour the owner wants and is
true:

> When this stage's declared artifacts are written, stop. You do not need to
> call `advance_stage`: ending your turn hands control back, and what happens
> next is decided from what you have actually written rather than from what
> you say about it. Calling `advance_stage` does not skip that. If this stage
> cannot produce all of its artifacts, say so and call `advance_stage` with the
> reason — that is what it is for now.

This is a change to `WORKFLOW_PROMPT`, it is scoped where `advance_stage` is
bound for the reason `component_guidance` gives about widget syntax, and it is
not the guarantee — the runner is. #74's own docstring on `WORKFLOW_PROMPT`
already makes that argument and it carries over unchanged.

## 6. What starts the next turn

### 6.1 It is `workflow-engine.md` §3.1's driver, amended, not replaced

Three amendments, and nothing else about §3.1 changes:

| §3.1 as written | Here |
|---|---|
| Start a turn when artifacts are not all present | Unchanged |
| Stop when they are all present | **Pose the gate** when they are |
| Run `review_stage` between turns, feed findings back | Unchanged, plus one class of its output is decisive (§3.1.3) |
| Propose `advance_stage` and wait on the interrupt | **Propose the advance directly through `ApprovalPort`** (§4.2) |
| Report on the SSE feed as `FileWritten` and `StageAdvanced` | Unchanged |
| Stop on budget or `max_consecutive_failures` | Unchanged, plus a per-stage no-progress rule (§7.1) |
| A driver cannot finish a course | **A driver can, if the operator has said it may** (§4.4) |

So: an amendment. Anyone who reads §3.1 and builds it will have built most of
this, and the parts that differ are the last two rows.

### 6.2 The fresh session is already built, twice

`SessionService.start_in_project` and `release_project` are the mechanism, and
`TopicDispatch`'s `DispatchRun.run` is the pattern, in full:

```python
session_id = await self._session.start_in_project(project_id)
try:
    await self._session.attach_project(project_id)
    outcome = await self._turns.run(session_id, understanding_input(...))
finally:
    await self._session.release_project(session_id)
```

Every property the owner wants from "start the next stage in a fresh session"
is in those five lines and is tested by the dispatch work:

- `start_in_project` forks the project's file history and **not** its
  conversation — "a project shares a workspace and not a chat history".
- `release_project` executes `AdvanceTip`, so the next session inherits the
  files at the point this one left them.
- The `finally` is the thing: `topic_seeding.py` and `topic_dispatch.py` both
  say in their docstrings that the failure it prevents is a run that dies
  holding the project, and a stage runner is a longer-lived version of the same
  hazard.
- One holder at a time is `Project.decide`'s refusal of a second
  `JoinProject`, and `dispatch.py` is emphatic that this is "not a limitation
  to be relaxed later; it is the property the queue exists to preserve".

**A stage runner is `DispatchRun.run` with a stage where the topic is.** That
is the most useful single sentence in this document for whoever implements it,
and it means the fresh-session half of the owner's proposal is closer to a
morning than to a design.

### 6.3 One session per stage, not per turn

Turns *within* a stage share a session. The boundary is what breaks the
conversation, and breaking it every turn would throw away the context that
makes turn two of a stage a revision rather than a restart — the findings from
`review_stage` are fed in as input, and a model that cannot see what it wrote
last turn cannot act on a finding about it.

The cost is that a stage taking many turns grows its context. `ContextService`
already compacts, and `run_turn` records a `CompactConversation` event when it
does, so this is a cost the system already prices. A stage that needs so many
turns that compaction is repeatedly triggered is a stage the no-progress rule
(§7.1) should have stopped.

## 7. Failure, and how the loop is stopped from spinning

Four failures, four different answers, and the discipline is that **every stop
reason must be a fold of the log or of a pure computation over committed state,
never a counter that only the running process knows.** That is
`auto_research.py`'s rule ("Every stop reason is a fold of the run's own stream
or of the queue") and `workflow-engine.md` §3.4's prohibition on retry state in
the supervisor, and it is the line between a budget and a `LoopPolicy`.

### 7.1 The model stopped early having written nothing

The exit condition is false and the turn appended no `FileWritten`. This is
`AutoRoundCompleted.produced_nothing` in another aggregate, and it should be
measured the same way: **against the events the turn appended, not against
its prose.** `run_turn` already reports the span (`from_index`, `to_index`), so
"did this turn write anything" is answerable exactly and cheaply.

**Two consecutive turns in the same stage that append no file event stop the
stage.** Two rather than one because the first can legitimately be a turn spent
reading, and more than two is a run paying for a model that has nothing to add.
This is a count over what the log says, not a convergence policy: it does not
decide whether the work is converging, only whether anything is happening.

### 7.2 The turn errored

`_run_turn` discards the aggregate and appends a failure marker on a freshly
loaded one, then raises. The runner counts it. `Budget.max_consecutive_failures`
is the existing shape and `AutoRunState.exhausted()` the existing fold.

A retried stage should get a **new session**, not a resumed one: the failed
turn left a marker and no work, and the session's conversation now ends with a
failure it will otherwise try to explain. `start_in_project` makes that cheap.

### 7.3 A check invariant failed

Stop the run, report the refusal, do not pose the gate. §3.1 item 3, and the
reasoning is `stage_exit.py`'s own. Both invariants name their repair, and
neither repair is something another turn produces — one is a preset edit, the
other a citation the critic machinery does not yet exist to supply.

### 7.4 Non-invariant findings that never clear

A stage whose blocking findings persist across turns will exhaust its per-stage
turn budget and stop. It must not exhaust the *run's* budget silently: the
report should name the stage and the findings, because "the run stopped" and
"the run stopped because `ubd.stage2.evidence` never produced a GRASPS
situation that passed `required_field_nondegenerate`" are different messages
and only one is actionable.

### 7.5 What must not be built

**No convergence check, no iteration counter that means anything, no retry
policy in the runner.** `LoopPolicy.max_iterations` and
`LoopPolicy.convergence_check` are declared in every preset and executable
nowhere — `workflow-engine.md` §3.4 established that four of five `Decision`
values cannot be written to the log at all — and a runner that implements
looping in process state reproduces `LoopPolicy` where nothing can audit it.

The distinction to hold: **a budget bounds how much is spent and needs no
opinion about the work; a loop policy decides whether the work is converging
and does.** Everything in §7 is the first kind. The moment a stop reason
requires comparing this turn's findings to last turn's to see if they improved,
it has become the second kind and belongs in the separate document §3.4 asks
for.

## 8. What this costs, and what breaks

### 8.1 Nothing in the event vocabulary has to change for the core

This is the main reason to believe the design is the right size. `StageAdvanced`
carries the transition; `AdvanceStage` is the command; `_advanced`'s
forward-only rule is untouched and becomes *more* load-bearing, since the runner
computes the next stage by the same `ids[at + 1]` the domain enforces. No new
aggregate, no new event, no projection change. `ToolCallDecided` records the
approval under §4.2(a).

### 8.2 `gate_decision` breaks, and that makes `decision` urgent

`build_workflow_tools` passes the model's free-text `rationale` into
`AdvanceStage.gate_decision`. **Under a runner there is no model rationale.**
The runner has to write something, and what it can honestly write is machine
prose: "4 of 4 declared artifacts present; 3 advisory findings; no invariant
failures".

That is more useful than a model's self-justification and it is a different
kind of thing, and the field cannot be both. So:

- `gate_decision` becomes **the harness's account of why the gate was posed** —
  evidence, not verdict.
- **The human's verdict has nowhere to live**, and today it barely does either:
  `decided_by` says who, and nothing says what.

`workflow-engine.md` §9 open question 3 proposed `decision: Decision =
"approve"` as a clean case-1 schema addition, and §6 argued it is the cheapest
real signal about prompt quality — the `approve_with_edits` delta between
machine output and human-corrected output, which that document calls "the best
available signal for which stages need better prompts".

**This design makes it considerably more urgent, and I would call it a
prerequisite rather than a next step.** Two reasons:

1. Once `gate_decision` is machine prose, the boundary records nothing a human
   decided beyond the fact that they did not stop it. An audit of a driven run
   would be able to say fifteen boundaries were crossed and nothing about how.
2. Under a runner the boundary is the *only* place a human touches the work.
   Today a human is also typing the prompts each turn, so their judgement is
   diffused through the run and partly recoverable from the transcript. Take
   that away and the gate decision is the entire human contribution. Losing it
   is losing the record of the review.

It stays a case-1 addition — absence reads as `approve` — and it stays cheap.
It is just no longer optional.

### 8.3 The four unrepresentable decisions are unchanged, and one gets worse

`amend_upstream`, `send_back`, `halt` and `approve_with_edits` remain
unwritable. §4.6's "a rejected gate stops the run" is a `send_back` in effect
and still is not recorded as one — the log will show a stage that did not
advance and nothing saying a human sent it back rather than a run that ran out
of budget. That gap is not created here, and it is more visible here, because a
driven run has more ways to stop and fewer humans watching which one happened.
The separate document §3.4 asks for is still the answer.

### 8.4 Tests

**Stay green.** #74's four tests are about the tool's refused-versus-accepted
split and none of them involves a runner. `EndTurnOnStageAdvance` is unchanged.
`test_nothing_the_turn_wrote_is_durable_when_the_reviewer_is_asked` pins an
ordering that is still true of the tool path — the runner is a second path, not
a replacement.

**Need writing:**

- `AdvanceStage` is executed in exactly one place in `application`, and that
  place asks first. §4.2. This is the amended form of the test
  `workflow-engine.md` §3.2 asked for and is the guarantee's whole enforcement.
- The runner never calls `AutonomyPolicy.set` or `relax_all`. Mirrors the rule
  `auto_research.py` states for the research loop.
- A stage whose artifacts are absent does not have its gate posed, however many
  turns end.
- A stage with an invariant failure stops the run without posing a gate, at
  `advance_stage: auto` as well as at `ask`.
- Two consecutive file-less turns stop the stage. §7.1.
- The next stage runs in a different session id, and that session's messages do
  not contain the previous stage's. This is the one that would have caught #74's
  outstanding promise (§2.3).

**Would need changing if the prompt lands:** whatever pins `WORKFLOW_PROMPT`'s
text. §5.2 rewrites a paragraph #74 added.

### 8.5 What a reader of the log loses

A driven run appends `FileWritten`, `StageAdvanced` and `ToolCallDecided` in the
same shapes as a hand-run one, and **nothing distinguishes them.** An operator
looking at a project six months later cannot tell whether fifteen boundaries
were reviewed by a person reading artifacts or waved through by a policy set to
`auto` — except by finding the `AutonomyChanged` event on the session and
reasoning about ordering across two aggregates.

That is a real loss and I am not proposing a fix, because the fix is either the
`decision` field carrying `decided_by`-like provenance (§8.2, which mostly
solves it) or a run aggregate (which is `workflow-engine.md` §3.4's separate
document). Naming it here so it is a known cost rather than a discovery.

## 9. What I am not proposing, and what I could not decide

### Not proposing

- **A prompt that says ending a turn advances the stage.** §5.2. It is false in
  the three cases that matter, and this repository has already paid once for a
  docstring that asserted an ordering it did not have.
- **Removing `advance_stage`.** §5. The owner said keep it and the owner is
  right; it is the only route for a stage the exit condition cannot express and
  the only route for a human with no runner.
- **A driver flag for attended/unattended.** §4.4. `AutonomyPolicy` is already
  the one answer to "may this happen without me", and a second one disagrees
  eventually. The runner should have no opinion about its own supervision.
- **Committing mid-turn.** #74 rejected it with reasons — `run_turn`'s
  atomicity, #69's retry baseline, a seam in infrastructure that holds no
  repository — and this design removes the reason anyone wanted it.
- **Feeding a rejected gate back into another turn.** §4.6. That is where a
  spin comes from and where `LoopPolicy` gets reinvented in process state.
- **Executing `LoopPolicy`, `Amendments`, `halt` or the rung ladder.**
  `workflow-engine.md` §3.4, unchanged. Still a separate document, still not a
  driver feature.
- **A new event or aggregate for the stage gate.** §4.2(b). `ToolCallDecided`
  and `StageAdvanced` carry it.
- **Breaking a session per turn.** §6.3. Per stage.

### Open questions

1. **Nothing here has been run, and the thing that would falsify it is a
   prompt.** The exit condition assumes a stage's artifacts get written by some
   number of turns. If the prompts being written concurrently produce a stage
   that writes three of four files and stalls, the runner spends its whole
   per-stage budget on every stage and the design reads as a machine for
   burning tokens. That is not a reason to design differently; it is a reason
   to build the runner *after* `workflow-engine.md` §5's first increment, which
   is what §5 already recommends and what I would keep.
2. **Presence and structure cannot tell a done stage from a populated one, and
   I have no proposal that can.** §3.2. Every mitigation I considered — a
   critic gating the exit condition, a content heuristic, a length floor —
   either costs the subagent machinery `workflow-engine.md` §3.3 prices at
   3–10× tokens or is a check that a model learns to satisfy. **This is the
   one I could not resolve, and it is the argument for the attended default
   surviving contact with the owner's preference for autonomy.** If the owner
   overrides it, the override should be the recorded `AutonomyChanged` and not
   a softening of this section.
3. **Should a rejected gate stop the run or reduce the budget?** §4.6 takes the
   conservative arm. The other arm is defensible and I do not have the evidence
   to choose, because nobody has yet rejected a gate on a driven run.
4. **Does `gate_decision` want renaming once it is machine prose?** §8.2 makes
   it evidence rather than verdict, and the name then says the wrong thing. A
   rename is a stored-shape change on an event that already exists, so it is a
   `domain/events.py` case-1 question rather than a free one, and it is not
   worth doing on its own — but it should ride along if `decision` lands.


---

## 10. Amendment: the tip is a pointer into a stream that keeps moving

Appended rather than woven in, per the `landing-page.md` §8 convention, because
§6.2's reasoning is most of why the runner looks the way it does and stays
worth reading. What follows corrects one sentence in it, and the sentence was
wrong in a way that cost real work.

**§6.2 says:** "`release_project` executes `AdvanceTip`, so the next session
inherits the files at the point this one left them."

**"The point this one left them" is not the point the session stopped working.
It is the point the session was released at**, and those are the same moment
only if nothing happens in the session afterwards. Releasing does not close a
session, does not detach it from its project, and does not stop it accepting
turns. Everything written after a release lands past the recorded offset, on a
stream the project is still pointing at, and is unreachable from the project
from the instant it is written.

### 10.1 What this actually did

Found in the owner's database rather than reasoned about. Project "Tollers"
(`9d6bd8d4`), reading its `Project` stream:

```
v11  SessionJoinedProject   03:40:15  08f37266
v12  ProjectTipAdvanced     03:40:54  08f37266 @ 31
v13  StageAdvanced          03:46:03  tyler.step0.intake -> hybrid.step1.framing
v14  SessionJoinedProject   03:46:15  588102a5
```

and session `08f37266`'s own stream:

```
31  TurnCompleted   03:40:54
32  TurnFailed      03:44:38
33  UserMessageSent 03:44:55
34  FileWritten     03:45:16  /course/00-source-claim.md
35  FileWritten     03:45:17  /course/00-open-question.md
36  FileWritten     03:45:17  /course/00-contested-queue.md
37  FileWritten     03:45:18  /course/00-check-findings.md
38  ToolCallDecided 03:46:03
```

An auto-research run had started that session (`AutoRunStarted` names it) and
released the project in the `after` hook `start_auto_research` passes when the
run stopped at 03:40:54 -- correct behaviour, and the route's own comment
argues for it. The person then kept working in the session the run had left
them in. The stage's four artifacts are events 34-37. The tip was frozen at 31.
`588102a5` forked at 31 and has none of them, and `GET` on the project's files
answered `{}` while four artifacts sat in the stream it was naming.

### 10.2 Three things this is not, and one it is

**It is not the stage runner, and #83 did not introduce it.** The runner has no
route (#83 says so deliberately), and no session in this database was made by
one. The defect is reachable from any two callers of `release_project` and
`start_in_project`, both of which predate the runner: dispatch, seeding, the
REPL and the web app.

**It is not #74.** Ending the turn on an advance is orthogonal. The files were
already stranded before `advance_stage` was called; the advance only made it
visible, by causing a join that forked from the stale pointer.

**It is not "fresh session versus fork".** This is worth stating flatly because
it is the natural first hypothesis and it is wrong: `start_in_project` does not
create an empty session. It calls `_fork_files_from`, which replays the source
stream filtered to `_FILE_EVENT_TYPES` -- **files without the conversation**,
which is precisely the trade §6.2 wanted and already had. A fresh session here
*is* a fork. Nothing needs to change to make a stage inherit its predecessor's
artifacts while inheriting none of its messages; that is what the call has
always done, and `test_inheriting_does_not_copy_the_conversation` has pinned
both halves since before the runner existed. There is no clean-context versus
continuity-of-artifacts trade to make, and a proposal framed as making it is
solving a problem this system does not have.

**What it is: a snapshot pointer with a writer still attached to the stream
behind it.** `ProjectTipAdvanced.at_event` is captured when the release
happens, and read when the next fork happens, and the gap between those two
moments is unbounded and usable.

### 10.3 The fix, and the two it was chosen over

**Taken: catch the tip up.** `AdvanceTip` gains a second accepted case -- the
session the tip already names may move it further along its own stream, while
nobody holds the project, forwards only. `start_in_project` does that before
joining, so `inherited_at` and `SessionForkedFrom.at_event` both name the point
the fork was actually taken from. `project_files` folds the tip session's whole
stream rather than reading to the offset, which is the same correction on the
read side.

Cost: one extra append at a join that had something to catch, and a tip that is
briefly behind between a release and the next join. No reader can observe the
lag, because the two that read the tip both take the newer answer. No event
shape changes; no stored payload is invalidated.

**Rejected: advance the tip after every turn.** Correct and always current, and
it puts a second aggregate load-and-save on the hot path of every turn in every
project for a pointer two callers read. The lag it removes is unobservable.

**Rejected: stop a released session from accepting turns.** The most honest
statement of the invariant -- releasing would mean finished -- and it breaks
the case that produced the bug rather than fixing it. The person had a session
open and kept using it, which is the ordinary thing to do; the auto-research
route released it out from under them. Refusing their next turn would answer a
misfiled release with an error message aimed at them.

### 10.4 What §6.2 should be read as saying now

> `release_project` executes `AdvanceTip`, so the project points at this
> session's stream. Where in that stream is caught up when the next session
> forks, because a released session keeps working and the release offset stops
> being the end of its work the moment it does.

The five lines of `DispatchRun.run` §6.2 recommends are still the pattern, and
the `finally` is still right. What was missing was never in those five lines --
it was in what happens to the session *after* they finish with it.

### 10.5 What is still open

**A released session that keeps working is still surprising**, and nothing
tells anyone it happened. The catch-up makes the work reachable; it does not
make the situation legible. An operator reading the log sees a release, then
file events on a released session, then a second `ProjectTipAdvanced` for the
same session, and has to reconstruct why. Worth a name eventually.

**`start_auto_research` releasing a session the person is still in is its own
question.** The route made the session, so the route puts it away -- the
comment's reasoning is sound and the alternative (a run that dies holding the
project) is worse. But the session it puts away is the one the UI leaves the
person sitting in. Not fixed here, because the catch-up makes it harmless
rather than merely rarer, and because the route's ownership rule is the right
one to keep.
