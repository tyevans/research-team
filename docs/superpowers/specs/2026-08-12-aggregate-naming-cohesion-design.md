# Aggregate naming cohesion

The domain reads as if five people named it. Six aggregates follow three
grammatical patterns, two disagree with their own state classes, and the
events use five prefixing conventions between them. None of this is a
modelling problem — the boundaries are right and stay where they are. This
is a rename, deliberately breaking stored events, so that the names say what
the model already does.

## Why now, and what it costs

`aggregate_type` is a string persisted with every event. Renaming aggregates
invalidates every event row written by an older build. That is allowed here
and it is deliberate: the project is pre-release and `CLAUDE.md` asks that a
break be written down rather than done quietly. This document is that record.

What no longer loads: every event stored under `aggregate_type` of
`"CodingSession"` or `"AutoResearchRun"`, and every event whose class name
changes below. There is no shim and no migration. Existing development
databases are discarded, not upgraded.

`tests/infrastructure/test_schema_evolution.py` must be updated to assert the
*refusal* — an old-shaped payload naming `"CodingSession"` should fail to
load, and the test should say so — rather than having its cases deleted.

## The rule

**Prefix an event with its aggregate when the event's leading noun is not
exclusively owned by that aggregate.** A noun fails to be exclusively owned
when:

1. another module owns it (`Stage` and `Workflow` are value objects in
   `domain/workflow.py`, not Project's),
2. it is generic enough to belong to anything (`Item`), or
3. it names something that is not the aggregate at all
   (`SourceDocument` on `Corpus`).

The rule is a floor, not a ceiling. It says when a prefix is *required*; it
does not say a prefix is forbidden elsewhere. `Topic` is already prefixed
throughout and stays that way — stripping `TopicFindingRecorded` down to
`FindingRecorded` would be churn bought with nothing.

The rule deliberately does not fire on "a future aggregate might want this
noun." That is prefix-on-anxiety, and it is how `SessionFileWritten` gets
justified. If artifacts ever become their own aggregate, *that* is the commit
where `FileWritten` gets renamed.

## Aggregate renames

Both qualifiers come off. Neither distinguishes anything: there is no manual
research run and no non-coding session. In both cases the state class already
dropped the qualifier, which is the codebase saying which name it prefers.

| Before | After | State class |
|---|---|---|
| `CodingSession` | `Session` | `SessionState` (already correct) |
| `AutoResearchRun` | `ResearchRun` | `AutoRunState` → `ResearchRunState` |
| `Project` | unchanged | `ProjectState` |
| `Topic` | unchanged | `TopicState` |
| `Corpus` | unchanged | `CorpusState` |
| `LearnerProgress` | unchanged | `LearnerProgressState` |

`Session` and `ResearchRun` read as a pair at the same altitude as
`Project`/`Topic`/`Corpus`: one conversation, and the loop that drives a
series of them.

Module `domain/auto_research.py` → `domain/research_run.py`. The application
modules `application/auto_research.py` and `application/auto_round.py` follow
to `application/research_run.py` and `application/research_round.py`.

## Event renames

### Corpus — rule 3

The name promises an aggregate called `SourceDocument`, which does not exist.

| Before | After |
|---|---|
| `SourceDocumentStored` | `CorpusDocumentStored` |
| `SourceDocumentDropped` | `CorpusDocumentDropped` |

The `source_id` *field* keeps its name. Topic links sources by that id and
the word is correct there — it is the class name that misleads.

### LearnerProgress — rule 2

`Item` identifies nothing.

| Before | After |
|---|---|
| `ItemAnswered` | `LearnerItemAnswered` |
| `ItemCompleted` | `LearnerItemCompleted` |
| `ChecklistProgressRecorded` | `LearnerChecklistRecorded` |

`ChecklistProgressRecorded` also sheds `Progress`, which was doing the
prefix's job badly — it echoed the aggregate name without naming it.

### Project — rule 1, plus one wrong-side name

`Stage` and `Workflow` belong to `domain/workflow.py`. Read cold,
`StageAdvanced` looks like a `Stage` aggregate's event.

| Before | After |
|---|---|
| `WorkflowSelected` | `ProjectWorkflowSelected` |
| `StageAdvanced` | `ProjectStageAdvanced` |
| `SessionJoinedProject` | `ProjectSessionJoined` |

`SessionJoinedProject` is a separate defect from prefixing: it is a Project
event narrated from the session's point of view, while its sibling
`ProjectTipAdvanced` is narrated from the project's. The new name fixes the
side and satisfies the prefix rule at once.

`ProjectCreated`, `ProjectTipAdvanced` and `ProjectDeleted` are unchanged.

### ResearchRun — abbreviation no longer matches

`Auto` was a prefix for an aggregate name that is going away. `Round` alone
means nothing, so the prefix here is load-bearing under rule 2 as well.

| Before | After |
|---|---|
| `AutoRunStarted` | `ResearchRunStarted` |
| `AutoRunStopped` | `ResearchRunStopped` |
| `AutoRoundStarted` | `ResearchRoundStarted` |
| `AutoRoundCompleted` | `ResearchRoundCompleted` |
| `AutoRoundFailed` | `ResearchRoundFailed` |

### Session — unchanged

All thirteen keep their current names, bare ones included:

```
SessionStarted        UserMessageSent       AssistantMessageAdded
ToolResultRecorded    TurnCompleted         TurnFailed
ConversationCompacted SessionForkedFrom     FileWritten
FileEdited            FileDeleted           ToolCallDecided
AutonomyChanged
```

Messages, turns, tool calls, files and autonomy are owned by Session and by
nothing else, so the rule does not fire. This is also where the rule pays
for itself: `FileWritten` appears in nineteen Python files and nine frontend
ones, and `SessionFileWritten` would buy nothing but keystrokes.

Two are worth naming as considered-and-kept:

- **`TurnCompleted` vs. `ResearchRoundCompleted`.** Turns and rounds are
  genuinely different things that sound similar, and `Budget.max_turns` on
  ResearchRun counts session turns from the run's side. The near-collision is
  in the *domain*, not the names — a prefix would not make a reader who
  confuses turns with rounds any less confused.
- **`ConversationCompacted`** uses a synonym for the aggregate rather than
  its name. `SessionCompacted` would be more literal but less accurate: what
  is compacted is the message history, not the session.

### Topic — unchanged

All twelve are already prefixed. `TopicSourceLinked` names a noun Corpus owns,
but the prefix already resolves it.

## Blast radius

Measured by file count on 2026-08-12, `research_team` + `tests` for Python,
`frontend/src` for TypeScript:

| Symbol | Python files | Frontend files |
|---|---|---|
| `CodingSession` | 29 | 0 |
| `SourceDocument` | 25 | 3 |
| `FileWritten` (unchanged) | 19 | 9 |
| `TurnCompleted` (unchanged) | 15 | 4 |
| `StageAdvanced` | 11 | 4 |
| `AutoRun` | 10 | 4 |
| `WorkflowSelected` | 10 | 4 |
| `SessionJoinedProject` | 5 | 1 |
| `AutoResearchRun` | 5 | 0 |
| `ItemAnswered` | 3 | 0 |

The frontend column is the part that is easy to forget. Event type names
cross the wire, so `npm run verify` is not optional here — and neither are
the two repo-wide ruff jobs, which is where a rename this broad usually
fails CI.

## Sequencing

The renames are independent of each other and each one is mechanical, so they
should land as separate commits rather than one sweep — a failed
`ruff format --check` on a 29-file commit tells you much less than one on a
5-file commit.

1. `SourceDocument*` → `CorpusDocument*` (no aggregate rename; smallest
   change that exercises the whole pipeline including read models and the
   three frontend files)
2. `Item*`/`ChecklistProgressRecorded` → `Learner*`
3. Project's three events
4. `AutoResearchRun` → `ResearchRun` with its five events and both module
   moves
5. `CodingSession` → `Session` (largest, no event renames, so it is purely
   the aggregate and the `aggregate_type` string)
6. `test_schema_evolution.py` asserts the refusals; `docs/domain-model.md`
   regenerated against the new names

Each commit runs all four gates. Read models project from `aggregate_type`,
so per `CLAUDE.md` each commit must also be run against a database that
predates it — which here means confirming it *fails* to load, since that is
the deliberate break rather than a bug.

## Explicitly not in scope

- Any change to aggregate boundaries. `Project` doing double duty as
  session-container and stage-machine, `LearnerProgress` having no id-level
  link to anything, and ResearchRun counting findings that Topic also counts
  are all real and all separate questions.
- Renaming state *fields*. `source_id`, `turn_index`, `tip_at_event` and
  friends stay as they are.
- Command class names. They mostly mirror the events and can follow later if
  the mismatch grates; nothing here depends on it.
