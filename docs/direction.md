# Direction

What is worth building, what is not, and what is already wrong. This file
exists to be read when deciding what to do next; it is not a plan and nothing
in it is scheduled. `BACKLOG.md` holds deferred work in enough detail to pick
up. This holds the reasoning above that: why a thing is worth doing at all, and
why several plausible things are not.

## The organising observation

This project's distinctive asset is that nearly everything is on the event log.
Six aggregates — `CodingSession`, `Project`, `Topic`, `Corpus`,
`LearnerProgress`, `AutoResearchRun` — cover the whole of what happens here,
and `ToolCallDecided` and `AutonomyChanged` mean even the human's authorization
decisions are durable and replayable.

The gap is not coverage. It is that **the log records what happened and almost
nothing projects what it means.** Most of the opportunities below are the same
move applied to different streams: fold a history that already exists into a
statement about the present, show it to a person, and let them accept or
override it. That move is available here and is not available to software built
on mutable state, which is the closest thing this codebase has to a durable
advantage.

The corresponding constraint, learned the hard way and stated here once: **the
things that make this code good are pinnings — to the event log, to a specific
methodology, to reasoning recorded in comments beside the code it justifies.**
Code quality does not predict whether something can be lifted out into a
library. What predicts it is whether the value survives being unpinned, and for
most of this codebase it does not. That is a reason for confidence in the
design, not a defect.

## Defects and unfinished decisions

**All five are closed.** They are kept here rather than deleted because in each
case the general form outlived the fix, and because two of them were closed by
finding the recorded diagnosis wider than the problem — which is the pattern
worth carrying forward, not the individual bugs.

**`SearchAttempts` was process-wide while claiming to be per-turn. Fixed.**
Every docstring in `infrastructure/agent/search.py` said "this turn" and one
paragraph admitted the contract was false; two concurrent turns shared a
counter, so one turn's empty searches could bound another's first search. The
count now lives in a `ContextVar` holding a mutable counter that the middleware
installs per turn.

The general form is the part to keep: **the recorded blocker was wider than the
problem, and that is why it stayed deferred.** The docstring and the backlog
entry both named the blocker as making the tool and its SearXNG client
rebuildable per turn — a real cost, and not one this needed. What had to be
per-turn was the counter. Rebuilding the client would have discarded connection
pooling to buy nothing. A deferral is a claim about cost, and a claim about cost
is a thing that can be wrong; this one had gone unchallenged long enough to read
as a fact about the code.

**Token counting excluded tool-call arguments. Fixed.** Measured at 224 counted
tokens against roughly 2,600 real ones on the same messages, so the compaction
trigger was not where it said it was and on a tool-heavy session might never
have fired at all. `_billable_text` now counts tool-call names and arguments
alongside content, and the measurement survives in `_tokens`' docstring as the
justification rather than as a bug report.

Kept here rather than deleted, because the general form is the useful part: **a
trigger that silently does not fire is worse than a wrong threshold**, since
nothing reports it. Anything else in this system that measures its own input in
order to decide when to act is exposed to the same failure, and the failure
looks like nothing happening.

**`checks.py`'s last line of domain coupling is gone, and its absence is a
test.** `tyler.criterion_doc_authored` took its type through a `TypeFilter` on
the binding, like every other check. The deliverable was never the line: "shared
checks know no domain" is now enforced by a test that parses `checks.py` and
fails on any reference to a *member* of `ArtifactType`.

Two things worth keeping. **A rule with one live exception erodes at the next
one** — that is how one check library silently becomes three, one per
methodology. And the property as first stated ("`ArtifactType` appears only
inside string literals") was unsatisfiable: the import and two annotations are
legitimate uses committing to no methodology, and forbidding them would leave
the library unable to describe the filter it is handed. The enforceable property
was narrower than the one it was natural to write down.

**The unreadable-page ceiling is decided: the headless browser is refused.**
`fetch.py`'s `UNREADABLE` path stays a dead end for JS-rendered pages. The cost
is not the install but a browser binary, a CI download step, and a new class of
failure on the path to a citation — render timeouts, anti-bot challenges, pages
slow enough to change what a turn costs. Today an app shell fails one way,
immediately, and says which; a rendered fetch that works most of the time
produces an intermittent gap, which the coverage machinery cannot represent and
which is worse than a plain one. `B43` carries the argument and names its own
trigger for revisiting.

The general form: **a default and a decision look identical in a diff and fail
very differently a year later.** The refusal is only worth anything because it
says what would overturn it.

**Search now exposes SearXNG's `engines`, `categories` and `time_range`.** A
capability gap rather than a defect, closed because it sat in the file the first
item was already open in.

The lesson is in the half that was not plumbing. The parameters had to enter the
memo key, because otherwise the same words with a recency bound hit the
unrestricted search's entry and the model is handed — labelled as recalled, and
therefore trusted — an answer to a question it did not ask. **Any cache key that
omits an input the upstream is sensitive to does not miss; it lies**, and it lies
in the one format the reader has been told to believe.

## Worth building

Ordered by confidence, not by size.

### 1. Two upstream contributions to `eventsource-py` — both landed

Both holes are closed in the library, both local versions are gone or reduced,
and this is kept rather than deleted for the reason the defects section keeps
its closed items: what this entry *predicted* is more useful than what it
proposed, because it was wrong three times and each way of being wrong
generalises.

**Aggregate-id targeting.** The library rejects a mistargeted creation event at
`_stamp`, where it sees the event's own `aggregate_id` and needs no
per-aggregate declaration. `domain/targeting.py` and its `ChecksCommandTarget`
mixin are deleted; all five aggregates stamp their creation event from the
command, which is what made the mixin redundant rather than merely duplicative,
and `tests/domain/test_targeting.py` asserts the library's refusal once per
aggregate.

**The prediction above said the ergonomics question would be close, and it was
not.** It said to keep the mixin or not "on ergonomics alone — it fails earlier
and names the command type, which is the better message." Both halves are false
against the actual release. The library's message names the command *and* the
event class *and* both ids *and* the remedy, where the mixin's named the command
and one id. And "earlier" was before `decide` rather than after it, with no
I/O, no persistence and no applied event in between — a distinction with nothing
observable inside it. **The bias worth naming is the direction: the prediction
overvalued the local version**, which is the one whose message and timing were
known in detail. A guess about a library that does not exist yet is a guess, and
it is not evenly distributed.

**Additive column reconciliation for read models.** `apply_schema` in
`infrastructure/persistence/read_models.py` now generates its `ALTER`s with the
library's `generate_additive_migration` instead of reading column definitions
back out of generated DDL with a regex, and `CorpusStore.open` goes through it
rather than its own `executescript`.

**It adopted the *other* function.** The library offers
`reconcile_read_model_schema`, which does the whole of what `apply_schema` does
— and takes a SQLAlchemy `AsyncConnection`, which nothing here owns; every store
holds a raw aiosqlite one. The pure generator, which was the smaller half of the
capability, slotted in unchanged. **An upstream capability arriving is not the
same as the shape you imagined arriving**, and the useful part of an upstream
release is often not the part that matches the pitch.

**The upstream function is stricter than the code it replaced, and that is a
loss as well as a gain.** `generate_additive_migration` refuses a required
column with no default *categorically*, before returning any statement; SQLite
refuses it only on a table that has rows. The spec called that difference pure
gain. It is gain on a populated table — the refusal is now atomic, where the old
loop landed the addable columns and then failed on the impossible one — and a
straight loss on an empty one, where SQLite would simply have added the column.
An empty table is exactly the `SessionSummaryRow.project_id` case the whole
mechanism exists to repair, so applying the plan verbatim broke the regression
test `CLAUDE.md` names. `apply_schema` now recreates an empty table and re-raises
on a populated one.

**A stricter upstream is not automatically a better one**, and the only reason
that showed up before it shipped is that a regression test held the old
behaviour in place. Strictness is a trade against the cases the stricter rule
also forbids, and those are invisible unless something is asserting them.

### 2. Generation as a replay

Stage outputs are markdown files written through `FileWritten`, so the file is
the record. When a stage prompt improves there is no mechanism to say "rebuild
every project's analysis stage against the new prompt"; regeneration is manual
if it happens at all.

Emitting the generation itself — preset version, prompt reference, model,
inputs, output — and projecting the course directory from it makes prompt
improvement a replay rather than a migration, and yields a diff ("this is what
stage 3 would say now versus what it said") that is exactly the surface a human
gate wants. Every ingredient is already present: artifact frontmatter carries
`preset`, `preset_version` and `provenance`, and the viewer already diffs files.
What is missing is only that the file is the truth instead of the derived value.

This is the largest single item here and the one most aligned with how the
knowledge pipeline already works.

### 3. Derived fetch grants, and nothing wider

A `FetchGrant` currently requires naming hosts in advance, which only works if
you already know what a run will do. Approval history can propose one instead:
pre-filled hosts and a budget, never auto-applied, with promotion recorded as an
event so the answer to "why is this authorized" is on the log and folding to
before it restores the gate. No surveyed system keeps provenance through
promotion; several cannot revoke a grant at all.

Four constraints, each of which the design fails without:

- **Filter to human decisions.** Only decisions where `decided_by == "human"`
  may inform a proposal, or the system confirms its own earlier inferences.
  Worth a test rather than a convention.
- **Long approval streaks are the weakest evidence, not the strongest.**
  Repeated prompting produces click-through; "approved forty times, rejected
  none" is indistinguishable from "stopped reading after the fourth prompt," and
  streak length is the variable that predicts exactly that. Approve-after-edit
  is the better signal, because editing proves the arguments were read. Count
  distinct sessions or days, never calls.
- **The pre-check proves less than it sounds like.** Replaying a proposed rule
  against the log can show it would not have auto-approved anything a human
  refused. It cannot show the rule is safe: the log holds only calls the agent
  chose to make, and absence of a rejection is not approval. Say that in the
  words the interface uses, or it becomes the illusion of control.
- **Rejections must be retractable.** A rejection that permanently poisons a row
  leaves an incidental early refusal with no escape but manual override — which
  is the configuration the feature exists to remove.

Restrict this to `fetch`. Host is a genuinely good projection of a fetch's
arguments; there is no safe equivalent for shell, and for file writes the
obvious path-prefix generalization is the one with a long history of granting
more than intended. One solved case is not a method.

### 4. Closing the loop on checks — built

Kept here rather than deleted, for the reason the defects section keeps its
closed items: the general form outlived the work.

A gate now writes `StageChecksEvaluated` on the session stream, and the
`ToolCallDecided` that answers it carries the same `review_id`. A projection
folds the pair into one row per check per review — the review's facts written
when the gate is posed, the decision's columns filled when the decision arrives
— and `/checks` in the REPL reads per-check fire rate, override rate and
time-to-decision out of it. Both gate paths emit, including the refusals and the
denials, because a rejected gate writes no `StageAdvanced` anywhere and was
otherwise the outcome that left no trace.

**The lesson is the denominator: a record modelled on the report you already
have will measure only what that report already shows.** The obvious design
starts from `/course/NN-check-findings.md`, because that is where the findings
are. But that file lists findings, so an event modelled on it counts numerators
forever and never produces a rate — "this check has never fired" and "this check
has never run" arrive as the same observation. The event therefore records every
*bound* check, including the ones that ran and found nothing, and an
unimplemented binding is stored under a status of its own so that its zero
findings can never be read as a pass. That is the single decision the rest of
the feature depends on, and it is invisible from the artefact you would
naturally start from.

What is measured, and what is not, stated plainly because an instrument that
overstates its reach is worse than a missing one:

- **No time-to-decision on the tool path.** There the review and the decision
  both reach the store at `_save_turn`, so the gap between their timestamps
  measures serialization rather than deliberation. Those rows contribute null,
  never zero — zero is a number that reads as an instant approval and is
  actually an absent measurement. Only the runner path, where a human's
  deliberation genuinely sits between two appends, is timed.
- **Policy approvals are reported beside the override rate, not inside it.**
  `decided_by == "policy"` means `advance_stage` was set to `auto` and nobody
  was asked. Folding those into the override rate would describe a system
  ignoring its checks, when what happened is that no human saw anything.
- **The two standing gates are marked, not hidden.** `ubd.uncoverage` and
  `addie.expert_gap_flag` are registered with no `run` and can never pass, so
  their 100% fire rate is a specification rather than a finding. They are
  recognised from the registry, so a third one needs no edit here.

What this does not do is act on the numbers. B22 and B38 are the two questions
it was built to make answerable and both are still open; see `BACKLOG.md`.

### 5. Recording exhausted searches

`Recall` is in-process and non-persistent for good reason: a durable record of
every page fetched would make fetching permanent, which `remember` promises it
is not. That argument is about content. The *fact* that a search ran and
returned nothing is different, and it is the only evidence that distinguishes
"there are no sources on this" from "nobody looked" — a distinction the coverage
and gap machinery is currently unable to make. A small event, retaining no
content, turns an unfalsifiable gap into a cited one.

### 6. Deeper knowledge-graph integration

The graph is currently built from corpus documents only — the input side.

- **Artifacts as documents.** Generated artifacts are prose with entities in
  them. Extracting them into the same graph makes a new class of check writable:
  not "does every objective have an assessment", which is a schema query already
  available, but "does this objective connect to anything the corpus knows".
  `provenance` records where text came from; it cannot tell you whether a claim
  is grounded. Cross-graph reachability can.
- **Topic consolidation.** Two agents in different rounds open topics that are
  the same question. That is entity resolution, which the knowledge layer
  already solves for entities and does not apply to topics.
  `TopicContested`/`TopicContestResolved` is the adjudication mechanism; what is
  missing is something proposing merges on evidence.
- **Temporal queries.** Findings change — a source superseded, a contest
  resolved the other way. "What we believed when" is currently implicit in event
  order.

### 7. Extract the overlay layer host

The one part of this codebase where packaging is the right call. `OverlayHost`,
`useLayer`, `useEscape`, `Overlay` and the bridge contract are roughly 120 lines
of mechanism solving something the React ecosystem genuinely does not expose:
every layer stack that exists is scoped to one library's context or module
state and is invisible to a foreign overlay. Radix, Headless UI and Ariakit each
have an internal version; none is exported, and cross-library stacking failure
is an open issue in more than one of them.

The value is disproportionately in what the file records — the layout-effect
registration ordering, refs-not-registry, `display: contents` against `inert`,
and the fact that jsdom implements `inert`'s presence and none of its behaviour.
A package is the only container that carries findings like those to a second
project.

Three things to fix as part of extraction, none of which this repo needs on its
own: a development-mode warning for the missing-host case (silently rendering no
tooltip is defensible in one application and a support burden in a package), a
`useBlockedProps()` so a consumer cannot forget the property the host's central
guarantee depends on, and using an existing exported AT-hiding primitive rather
than the hand-rolled page wrapper.

### 8. Publish three findings as prose

Each is a verifiable claim about widely-used software that is not written down
anywhere, and each is worth more as writing than as code:

- Rewriting the running message list inside a model hook breaks turn accounting
  for any consumer that identifies a turn by slicing the returned list; the
  wrapping hook does not. Intervening at the fold instead leaves both turn
  accounting and time travel untouched.
- Token counting that excludes tool-call arguments under-reports by an order of
  magnitude and silently disables whatever it triggers.
- A truncated tool result must be marked unmistakably rather than merely cut;
  the practice is common and the reasoning is not published.

## Not worth building

Recorded so the question is not reopened without new information.

**Packaging the web tools.** SearXNG search plus main-content extraction exists
as several free, installable servers; the largest existing tool-collection
package for this ecosystem has been sunset. The one genuinely uncovered piece —
memoization with a normalization rule that refuses to stem, sort or embed — is
sixty lines and a page of reasoning. That is a copy-paste and an essay, not a
dependency.

**Packaging the context strategies.** Two of the four are pure functions of a
message list and too small to install. The summarizing one travels mechanically
but loses its reason to exist without a caller that persists the compaction and
folds it back — so the package is either trivial or demands an event-sourcing
contract from its consumer. The niche is also closing from above as
context management moves server-side.

**Packaging the workflow engine or the check library.** Two libraries hide in
there and neither has an audience. The generic half is a few hundred lines of
real novelty competing with established orchestration and policy tools on their
own ground. The domain half addresses a niche with no existing library, for the
structural reason that instructional designers are not Python developers and the
people building tools for them build products. Splitting the two would put a
still-changing vocabulary on a package boundary, which is worse than either.

**Packaging the approval gate.** The adapter is thin and correct, and every
agent framework is absorbing per-tool approval into its own middleware. What is
left over — floors that configuration cannot lower, grants as bounded
pre-authorization, and enforcement by making a tool invisible rather than by
refusing it — is a vocabulary worth writing down, not a package. Watch for the
framework growing session-scoped grants and a deny tier; if it does, several
hundred lines here become deletable.

**More methodology-specific checks.** The namespaced table is three entries
long, and that shortness is the finding: the generalization was earned by
observing that three traditions collapse into one core. Adding domain-specific
machinery back would undo the only research this subsystem encodes.

**A general promotion interface across all tools.** See §3. The argument
projection that makes derived authorization safe exists for fetch and does not
generalize.
