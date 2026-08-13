# Task 1: retiring `domain/targeting.py`

Executed from the plan `docs/superpowers/plans/2026-08-13-adopting-0140.md`,
Task 1 only. Nothing from Task 2 or Task 3 was touched.

## What changed

- **Added** `tests/domain/test_targeting.py` — five tests, one per aggregate,
  each executing that aggregate's creation command with a foreign id and
  asserting `AggregateIdMismatchError` naming the foreign id and the command
  class.
- **Deleted** `research_team/domain/targeting.py`.
- **Removed** the `ChecksCommandTarget` base, its import and the `target_field`
  declaration from `project.py`, `session.py`, `auto_research.py`, `corpus.py`
  and `topic.py`.
- **Deleted** `tests/domain/test_topic.py::test_the_aggregate_refuses_a_command_aimed_at_a_different_topic`.
  It was the mixin's only direct test (its docstring named `ChecksCommandTarget`
  and it matched on the mixin's wording, `match="targets"`). Its coverage is
  carried by `test_a_topic_refuses_a_command_naming_another_topic`, which asserts
  the same scenario against the mechanism that now answers. This deletion is not
  in the plan, which did not know the test existed; it is a rename of an
  assertion, not a loss of one.
- `research_team/domain/__init__.py` exported neither name — nothing to remove
  there (checked, as Step 5 directs).

Ruff's import sorter then rewrote the now-shortened import blocks in
`auto_research.py`, `corpus.py` and `topic.py`, and the formatter closed a blank
line in `corpus.py`. Both are mechanical consequences of the deleted import line.

## Step 2, per aggregate: does `decide` stamp the creation event from the command?

This is the step that decides whether deleting the mixin is safe, because the
library inspects only the event. **All five stamp from the command.** Four of the
five carry a comment saying why (on a fresh aggregate the state's id is still
`None`), which is corroboration rather than the finding itself — each `decide`
case was read.

| Aggregate | Creation command | `decide` case | Stamps from |
|---|---|---|---|
| `Project` | `CreateProject(project_id, name)` | `project.py:255-259` | **command** — `case CreateProject(project_id=new_id, ...)` binds the command's field and passes it as `ProjectCreated(aggregate_id=new_id, ...)` |
| `CodingSession` | `StartSession(session_id, …)` | `session.py:131-143` | **command** — `case StartSession(session_id=new_id, …)`, then `SessionStarted(aggregate_id=new_id, …)` |
| `AutoResearchRun` | `StartRun(run_id, …)` | `auto_research.py:328-340` | **command** — `AutoRunStarted(aggregate_id=command.run_id, …)` |
| `Corpus` | `StoreSourceDocument(corpus_id, …)` | `corpus.py:161-176` | **command** — `SourceDocumentStored(aggregate_id=command.corpus_id, …)`; the confirmed example the spec cites |
| `Topic` | `OpenTopic(topic_id, …)` | `topic.py:467-483` | **command** — `TopicOpened(aggregate_id=command.topic_id, …)` |

No aggregate stamps the creation event from state, so no aggregate needed to keep
the mixin. Non-creation commands stamp from state (`aggregate_id=session_id`,
`aggregate_id=topic_id`, and so on, where those locals are `state.<id>`), which is
correct and was never what the mixin checked — none of those commands carries a
`target_field`.

The five tests are one per aggregate rather than one parametrised case precisely
because this table is the claim being tested, and it is a fact about five
separate `decide` functions.

## Red, then green

### Red — Step 4, with the mixin still present

```
$ uv run pytest tests/domain/test_targeting.py -v
collected 5 items

tests/domain/test_targeting.py::test_a_project_refuses_a_command_naming_another_project FAILED [ 20%]
tests/domain/test_targeting.py::test_a_session_refuses_a_command_naming_another_session FAILED [ 40%]
tests/domain/test_targeting.py::test_an_auto_research_run_refuses_a_command_naming_another_run FAILED [ 60%]
tests/domain/test_targeting.py::test_a_corpus_refuses_a_command_naming_another_corpus FAILED [ 80%]
tests/domain/test_targeting.py::test_a_topic_refuses_a_command_naming_another_topic FAILED [100%]
```

The failures are behavioural, not import errors. Two of the five, verbatim:

```
    def execute(self, command: Any) -> list[Any]:
        target = getattr(command, self.target_field, None)
        if target is not None and target != self.aggregate_id:
>           raise CommandRejectedError(
                f"{type(command).__name__} targets {target}, but this "
                f"{type(self).__name__} is {self.aggregate_id}"
            )
E           eventsource.domain.exceptions.CommandRejectedError: StoreSourceDocument targets 09b02bdd-fcd0-4f37-85ca-229ee76e9add, but this Corpus is 906eb54d-9978-4734-8ca1-c20acb65ad8d

research_team/domain/targeting.py:45: CommandRejectedError
```

```
E           eventsource.domain.exceptions.CommandRejectedError: OpenTopic targets 69fbf404-d52c-480c-ba44-4b6f19e971a4, but this Topic is 1fbcace3-77be-4aac-8fea-7789a709779b

research_team/domain/targeting.py:45: CommandRejectedError
```

That is the evidence the task asked for: the mixin is what answers today, raising
from `targeting.py:45` before `decide` ever runs. The final green is therefore a
change of mechanism, not a test that never constrained anything.

### Green — Step 6, mixin deleted

```
$ uv run pytest tests/domain/test_targeting.py -v
collected 5 items

tests/domain/test_targeting.py::test_a_project_refuses_a_command_naming_another_project PASSED [ 20%]
tests/domain/test_targeting.py::test_a_session_refuses_a_command_naming_another_session PASSED [ 40%]
tests/domain/test_targeting.py::test_an_auto_research_run_refuses_a_command_naming_another_run PASSED [ 60%]
tests/domain/test_targeting.py::test_a_corpus_refuses_a_command_naming_another_corpus PASSED [ 80%]
tests/domain/test_targeting.py::test_a_topic_refuses_a_command_naming_another_topic PASSED [100%]

============================== 5 passed in 0.15s ===============================
```

### Step 7 — `tests/domain/` and `tests/application/`

First run, one failure, and it is the expected one:

```
$ uv run pytest tests/domain/ tests/application/ -q
E       eventsource.domain.exceptions.AggregateIdMismatchError: TopicOpened names aggregate_id=0455e5a1-… but is emitted from Topic(98d8b265-…) while handling OpenTopic. An event's aggregate_id is its stream key, so an event emitted here cannot belong to another aggregate. Drop the aggregate_id (the aggregate stamps it) or load 0455e5a1-… and emit from that aggregate.

.venv/lib/python3.13/site-packages/eventsource/domain/aggregate.py:483: AggregateIdMismatchError
FAILED tests/domain/test_topic.py::test_the_aggregate_refuses_a_command_aimed_at_a_different_topic
1 failed, 1018 passed in 74.49s
```

That is the mixin's own test, superseded as described above; deleted, and
`tests/domain/test_topic.py` then passes 38/38. No test anywhere in `domain` or
`application` caught `CommandRejectedError` for a mistargeted command.

### Step 8 — `tests/interfaces/`

```
$ uv run pytest tests/interfaces/ -q
334 passed in 117.09s (0:01:57)
```

## The exception-type change, and the check the plan asked for

Deleting the mixin turns a caught `CommandRejectedError` into an uncaught
`AggregateIdMismatchError` at `infrastructure/agent/workflow_tools.py:37`,
`interfaces/cli/repl.py:16` and `interfaces/web/app.py:19`. The spec's argument is
that this is correct **because no user input reaches a `target_field`**. I checked
every site that issues one of the five creation commands rather than taking that
on trust:

- `interfaces/cli/repl.py:309` and `interfaces/web/app.py:500` —
  `CreateProject(project_id=aggregate.aggregate_id, …)`. The id is the aggregate's
  own; only `name` comes from the request body.
- `application/session_service.py:501` and `:593` —
  `StartSession(session_id=session_id, …)` against
  `self._repository.create(session_id)`, the same local.
- `application/auto_research.py:191` — `StartRun(run_id=run.aggregate_id, …)`.
- `infrastructure/agent/topic_tools.py:94` — `OpenTopic(topic_id=topic.aggregate_id, …)`
  on a freshly created `uuid4()`. The agent supplies `question`, `rationale` and
  `scope`; it cannot supply the id.
- `infrastructure/knowledge/redstring_adapter.py:527` —
  `StoreSourceDocument(corpus_id=self._project_id, …)` against the corpus loaded
  for that same project id.

In all five the target is an id the composition root or a use case is already
holding. There is no site where a user can reach a `target_field`, so the spec's
argument holds everywhere and nothing was papered over.

## Ruff

```
$ uv run ruff check .
All checks passed!
$ uv run ruff format --check .
216 files already formatted
```

Both run repo-wide.

## What the plan got wrong, and what is flagged

- **Step 1's premise.** The plan says `tests/domain/test_targeting.py` "may
  already exist and test the mixin". It did not exist. The mixin's only test was
  one case inside `tests/domain/test_topic.py`, found by grep rather than by `ls`,
  and only `Topic` had one — the other four aggregates carried the mixin with no
  test of it at all. The plan's Step 7 anticipates production catch sites failing
  but not a *test* of the mixin failing, so the deletion above is a step the plan
  does not contain.
- **The plan's test sketch omits required fields**, as it says it might. Real
  signatures used: `CreateProject(project_id, name)`, `StartSession(session_id,
  system_prompt, model_name, project_id)`, `StartRun(run_id, project_id,
  session_id)`, `StoreSourceDocument(corpus_id, source_id, text)`,
  `OpenTopic(topic_id, project_id, question, rationale)`. `StartSession` lives in
  `domain/commands.py`, not `domain/session.py`.
- **Nothing flagged rather than fixed.** No aggregate had to keep the mixin, no
  user-reachable `target_field` was found, and the full `domain`, `application`
  and `interfaces` suites pass. Per the plan's constraints the full `pytest` run
  and the frontend gate were not run and are left to CI.
