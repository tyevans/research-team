"""Decision logic and event folding for Topic aggregate.

Decomposed from `topic.py` to separate command validation and event
application rules from the domain schema and events.
"""

from eventsource import CommandRejectedError, DomainEvent

from research_team.research.domain.topic import (
    Acknowledgement,
    AcknowledgeTrigger,
    AddSubQuestion,
    Contest,
    LinkEntity,
    LinkSource,
    OpenTopic,
    RecordContest,
    RecordFinding,
    RecordGap,
    RecordInvestigation,
    ResolveContest,
    ResolveSubQuestion,
    RestateTopicQuestion,
    SetTopicStatus,
    SubQuestion,
    TopicCommand,
    TopicContested,
    TopicContestResolved,
    TopicEntityLinked,
    TopicFindingRecorded,
    TopicGapRecorded,
    TopicInvestigated,
    TopicOpened,
    TopicQuestionRestated,
    TopicSourceLinked,
    TopicSourceUnlinked,
    TopicState,
    TopicStatusChanged,
    TopicSubQuestionAdded,
    TopicSubQuestionResolved,
    TopicTriggerAcknowledged,
    UnlinkSource,
)


def decide(command: TopicCommand, state: TopicState) -> list[DomainEvent]:
    """Which requests are legal, and what facts they produce.

    Reads as a transition table, the way `project.decide` and `corpus.decide`
    do. The "topic does not exist yet" rejection is a single case rather than a
    guard repeated per command.
    """
    topic_id = state.topic_id
    match command, state:
        case OpenTopic(), TopicState(status="new"):
            if not command.question.strip():
                raise CommandRejectedError("a topic needs a question")
            if not command.rationale.strip():
                # The same argument as a drop's reason. A topic that appears
                # with no rationale cannot be told apart from one an
                # autonomous run invented to keep itself busy.
                raise CommandRejectedError("a topic needs a rationale")
            return [
                TopicOpened(
                    aggregate_id=command.topic_id,
                    project_id=command.project_id,
                    question=command.question,
                    rationale=command.rationale,
                    scope=command.scope,
                )
            ]
        case OpenTopic(), _:
            raise CommandRejectedError("topic already opened")

        case _, TopicState(status="new"):
            raise CommandRejectedError("topic not opened")

        case RestateTopicQuestion(question=question, rationale=rationale), _:
            cleaned = question.strip()
            if not cleaned:
                raise CommandRejectedError("a topic question cannot be blank")
            if cleaned == state.question:
                return []
            return [
                TopicQuestionRestated(
                    aggregate_id=topic_id,
                    question=cleaned,
                    previous_question=state.question,
                    rationale=rationale.strip(),
                )
            ]

        case AddSubQuestion(key=key, question=question), _:
            if key in state.sub_questions:
                raise CommandRejectedError(f"sub-question {key!r} already exists")
            if not question.strip():
                raise CommandRejectedError("a sub-question needs a question")
            return [TopicSubQuestionAdded(aggregate_id=topic_id, key=key, question=question)]

        case ResolveSubQuestion(key=key, answer=answer), _:
            sub = state.sub_questions.get(key)
            if sub is None:
                raise CommandRejectedError(f"unknown sub-question {key!r}")
            if sub.answer is not None:
                raise CommandRejectedError(f"sub-question {key!r} is already resolved")
            if not answer.strip():
                raise CommandRejectedError("resolving a sub-question requires an answer")
            return [TopicSubQuestionResolved(aggregate_id=topic_id, key=key, answer=answer)]

        case LinkSource(source_id=source_id, relation=relation, note=note), _:
            if source_id in state.source_ids:
                # Idempotent rather than rejected: an autonomous round that
                # re-reads a source it already linked has done nothing wrong,
                # and a raise here would fail the whole turn over it.
                return []
            return [
                TopicSourceLinked(
                    aggregate_id=topic_id,
                    source_id=source_id,
                    relation=relation,
                    note=note,
                )
            ]

        case UnlinkSource(source_id=source_id, reason=reason), _:
            if source_id not in state.source_ids:
                raise CommandRejectedError(f"source {source_id!r} is not linked")
            if not reason.strip():
                raise CommandRejectedError("unlinking a source requires a reason")
            return [
                TopicSourceUnlinked(aggregate_id=topic_id, source_id=source_id, reason=reason)
            ]

        case LinkEntity(entity_id=entity_id, name=name), _:
            if entity_id in state.entity_ids:
                return []
            return [TopicEntityLinked(aggregate_id=topic_id, entity_id=entity_id, name=name)]

        case (
            RecordInvestigation(
                at_position=at,
                summary=summary,
                by_run_id=run_id,
                outcome=outcome,
            ),
            _,
        ):
            if not at.strip():
                raise CommandRejectedError("an investigation must say where the log stood")
            return [
                TopicInvestigated(
                    aggregate_id=topic_id,
                    at_position=at,
                    summary=summary,
                    by_run_id=run_id,
                    outcome=outcome,
                )
            ]

        case RecordFinding(summary=summary, source_ids=source_ids), _:
            if not summary.strip():
                raise CommandRejectedError("a finding needs a summary")
            return [
                TopicFindingRecorded(
                    aggregate_id=topic_id,
                    summary=summary,
                    source_ids=list(source_ids),
                )
            ]

        case RecordGap(looking_for=looking_for, tried=tried), _:
            if not looking_for.strip():
                raise CommandRejectedError("a gap needs to say what was looked for")
            if not [item for item in tried if item.strip()]:
                # Both required, for `TopicOpened`'s reason. A gap with nothing
                # tried says only "we do not know", which the topic already
                # said by being open.
                raise CommandRejectedError("a gap needs to say what was tried")
            return [
                TopicGapRecorded(
                    aggregate_id=topic_id,
                    looking_for=looking_for,
                    tried=list(tried),
                )
            ]

        case RecordContest(key=key, nature=nature, source_ids=source_ids), _:
            if key in state.contests:
                raise CommandRejectedError(f"contest {key!r} already recorded")
            if not nature.strip():
                raise CommandRejectedError("a contest needs a description")
            return [
                TopicContested(
                    aggregate_id=topic_id,
                    key=key,
                    nature=nature,
                    source_ids=list(source_ids),
                )
            ]

        case (
            ResolveContest(key=key, resolution=resolution, justification=justification),
            _,
        ):
            contest = state.contests.get(key)
            if contest is None:
                raise CommandRejectedError(f"unknown contest {key!r}")
            if contest.resolution is not None:
                raise CommandRejectedError(f"contest {key!r} is already resolved")
            if not justification.strip():
                raise CommandRejectedError("resolving a contest requires a justification")
            return [
                TopicContestResolved(
                    aggregate_id=topic_id,
                    key=key,
                    resolution=resolution,
                    justification=justification,
                )
            ]

        case SetTopicStatus(to_status=to_status, justification=justification), _:
            if not justification.strip():
                # Every status transition is a judgement, and the ones that
                # take a topic out of the queue are exactly the ones a later
                # reader will want explained.
                raise CommandRejectedError("a status change requires a justification")
            if to_status == state.status:
                raise CommandRejectedError(f"topic is already {to_status}")
            return [
                TopicStatusChanged(
                    aggregate_id=topic_id,
                    to_status=to_status,
                    justification=justification,
                )
            ]

        case (
            AcknowledgeTrigger(trigger=trigger, reason=reason, until_position=until),
            _,
        ):
            if not reason.strip():
                raise CommandRejectedError("an acknowledgement requires a reason")
            if not until.strip():
                # An acknowledgement with no expiry is a silenced alarm nobody
                # remembers silencing, which is the failure mode that makes
                # monitoring systems stop being believed.
                raise CommandRejectedError("an acknowledgement requires an expiry position")
            return [
                TopicTriggerAcknowledged(
                    aggregate_id=topic_id,
                    trigger=trigger,
                    reason=reason,
                    until_position=until,
                )
            ]

    raise CommandRejectedError(f"unhandled command {type(command).__name__}")


def evolve(state: TopicState, event: DomainEvent) -> TopicState:
    """What each fact does to the state.

    Total on purpose: an unknown event leaves the state alone rather than
    raising, so a stream carrying an event this build does not know about still
    replays instead of failing halfway through.
    """
    match event:
        case TopicOpened(question=question, rationale=rationale, scope=scope):
            return TopicState(
                topic_id=event.aggregate_id,
                project_id=event.project_id,
                status="open",
                question=question,
                rationale=rationale,
                scope=scope,
            )

        case TopicQuestionRestated(question=question, previous_question=prev):
            return state.model_copy(
                update={
                    "question": question,
                    "previous_questions": [*state.previous_questions, prev],
                }
            )

        case TopicSubQuestionAdded(key=key, question=question):
            return state.model_copy(
                update={
                    "sub_questions": {
                        **state.sub_questions,
                        key: SubQuestion(question=question),
                    }
                }
            )

        case TopicSubQuestionResolved(key=key, answer=answer):
            existing = state.sub_questions.get(key)
            if existing is None:
                return state
            return state.model_copy(
                update={
                    "sub_questions": {
                        **state.sub_questions,
                        key: existing.model_copy(update={"answer": answer}),
                    }
                }
            )

        case TopicSourceLinked(source_id=source_id):
            if source_id in state.source_ids:
                return state
            return state.model_copy(update={"source_ids": [*state.source_ids, source_id]})

        case TopicSourceUnlinked(source_id=source_id):
            return state.model_copy(
                update={"source_ids": [s for s in state.source_ids if s != source_id]}
            )

        case TopicEntityLinked(entity_id=entity_id):
            if entity_id in state.entity_ids:
                return state
            return state.model_copy(update={"entity_ids": [*state.entity_ids, entity_id]})

        case TopicInvestigated(at_position=at):
            return state.model_copy(
                update={
                    "investigations": state.investigations + 1,
                    "last_investigated_at": at,
                    # Snapshot the finding count *as of this look*, so the next
                    # look can tell whether anything came of this one.
                    "findings_at_last_investigation": state.findings,
                    # A look moves a topic out of `open`, which is what stops
                    # the queue from re-offering it as never-investigated.
                    "status": ("investigating" if state.status == "open" else state.status),
                }
            )

        case TopicFindingRecorded():
            return state.model_copy(update={"findings": state.findings + 1})

        case TopicGapRecorded():
            # Counts, and nothing else. Deliberately does not touch status:
            # see the event's docstring.
            return state.model_copy(update={"gaps": state.gaps + 1})

        case TopicContested(key=key, nature=nature, source_ids=source_ids):
            return state.model_copy(
                update={
                    "contests": {
                        **state.contests,
                        key: Contest(nature=nature, source_ids=list(source_ids)),
                    }
                }
            )

        case TopicContestResolved(key=key, resolution=resolution):
            existing = state.contests.get(key)
            if existing is None:
                return state
            return state.model_copy(
                update={
                    "contests": {
                        **state.contests,
                        key: existing.model_copy(update={"resolution": resolution}),
                    }
                }
            )

        case TopicStatusChanged(to_status=to_status):
            return state.model_copy(update={"status": to_status})

        case TopicTriggerAcknowledged(trigger=trigger, reason=reason, until_position=until):
            return state.model_copy(
                update={
                    "acknowledgements": {
                        **state.acknowledgements,
                        trigger: Acknowledgement(reason=reason, until_position=until),
                    }
                }
            )

    return state
