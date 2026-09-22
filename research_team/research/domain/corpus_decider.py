"""Corpus aggregate decision and event folding rules.

Extracted from corpus.py to isolate command validation, invariant enforcement,
and state transition rules from event/command/record schema definitions.
"""

import hashlib
import json

from eventsource import CommandRejectedError, DomainEvent

from research_team.research.domain.corpus import (
    UNREADABLE_DEGRADATIONS,
    CorpusCommand,
    CorpusDerivedTextStored,
    CorpusDocumentDropped,
    CorpusDocumentStored,
    CorpusMediaStored,
    CorpusState,
    DropSourceDocument,
    MediaRecord,
    StoreDerivedText,
    StoreSourceDocument,
    StoreSourceMedia,
    TextRecord,
)


def decide(command: CorpusCommand, state: CorpusState) -> list[DomainEvent]:
    """Which requests are legal, and what facts they produce.

    Reads as a transition table, the way `project.decide` does.

    The digest is computed here rather than accepted from the caller -- for
    text. A supplied sha256 makes `by_digest` a claim instead of a fact, and a
    wrong one stays invisible until two unrelated documents collide in it.

    **For media the digest is supplied, and that is a deliberate weakening.**
    The bytes never reach the domain -- holding a video in memory to hand it
    to a pure function is not a thing to do -- so `CorpusMediaStored.sha256`
    is what the blob store computed while streaming, and `by_digest` is a
    claim for those entries rather than a fact. `application/blobs.py`
    carries the mitigation: `put` returns the digest and there is no
    parameter by which a caller could offer a different one, so a wrong
    digest requires a bug in the store rather than a mistake at a call site.
    """
    corpus_id = state.corpus_id
    match command, state:
        case (
            StoreSourceDocument(source_id=source_id)
            | StoreSourceMedia(source_id=source_id)
            | StoreDerivedText(source_id=source_id),
            _,
        ) if "/" in source_id:
            raise CommandRejectedError(
                f"source_id {source_id!r} contains '/', a path separator; the "
                "document would be stored but unreachable through every route "
                "that names a source"
            )

        case StoreSourceDocument(source_id=source_id), _ if _is_derived(state, source_id):
            raise CommandRejectedError(
                f"source {source_id!r} is derived from "
                f"{_derived_from(state, source_id)!r}; storing a fetched document "
                "under it would overwrite a transcript with prose nobody perceived"
            )

        case StoreDerivedText(source_id=source_id), _ if _holds_something_not_derived(
            state, source_id
        ):
            raise CommandRejectedError(
                f"source {source_id!r} is not derived; storing perceived text "
                "under it would replace a source with a reading of another one"
            )

        case StoreDerivedText(source_id=source_id, derived_from=parent), _ if (
            _repoints_a_transcript(state, source_id, parent)
        ):
            raise CommandRejectedError(
                f"source {source_id!r} is derived from "
                f"{_derived_from(state, source_id)!r}, not {parent!r}; a re-perception "
                "revises one reading of one medium and cannot move it to another"
            )

        case StoreSourceDocument(source_id=source_id), _ if (
            _kind_of(state, source_id) == "media"
        ):
            raise CommandRejectedError(
                f"source {source_id!r} holds media; storing text under it would "
                "change what the id means rather than revise it"
            )

        case StoreSourceMedia(source_id=source_id), _ if _kind_of(state, source_id) == "text":
            raise CommandRejectedError(
                f"source {source_id!r} holds text; storing media under it would "
                "change what the id means rather than revise it"
            )

        case StoreSourceDocument(), _:
            return [
                CorpusDocumentStored(
                    aggregate_id=command.corpus_id,
                    source_id=command.source_id,
                    text=command.text,
                    sha256=hashlib.sha256(command.text.encode("utf-8")).hexdigest(),
                    uri=command.uri,
                    title=command.title,
                    published_at=command.published_at,
                    note=command.note,
                    fetched_at=command.fetched_at,
                )
            ]

        case StoreSourceMedia(), _:
            return [
                CorpusMediaStored(
                    aggregate_id=command.corpus_id,
                    source_id=command.source_id,
                    sha256=command.sha256,
                    media_type=command.media_type,
                    byte_count=command.byte_count,
                    uri=command.uri,
                    title=command.title,
                    published_at=command.published_at,
                    note=command.note,
                    fetched_at=command.fetched_at,
                )
            ]

        case StoreDerivedText(derived_from=parent), _:
            parent_record = state.documents.get(parent)
            if parent_record is None:
                raise CommandRejectedError(f"unknown source {parent!r}")
            if parent_record.kind != "media":
                raise CommandRejectedError(
                    f"source {parent!r} holds text; there is nothing in it to perceive"
                )
            _reject_unless_json_list_of_strings("degradations", command.degradations)
            _reject_unless_json_list_of_objects("locator_map", command.locator_map)
            return [
                CorpusDerivedTextStored(
                    aggregate_id=command.corpus_id,
                    source_id=command.source_id,
                    derived_from=command.derived_from,
                    text=command.text,
                    sha256=hashlib.sha256(command.text.encode("utf-8")).hexdigest(),
                    locator_map=command.locator_map,
                    perceived_with=command.perceived_with,
                    degradations=command.degradations,
                    title=command.title,
                    note=command.note,
                )
            ]

        case _, CorpusState(status="new"):
            raise CommandRejectedError("corpus is empty")

        case DropSourceDocument(source_id=source_id, reason=reason), _:
            if not reason.strip():
                raise CommandRejectedError("a drop requires a reason")
            record = state.documents.get(source_id)
            if record is None:
                raise CommandRejectedError(f"unknown source {source_id!r}")
            if record.dropped_reason is not None:
                raise CommandRejectedError(
                    f"source {source_id!r} already dropped: {record.dropped_reason}"
                )
            return [
                CorpusDocumentDropped(
                    aggregate_id=corpus_id, source_id=source_id, reason=reason
                )
            ]

    raise CommandRejectedError(f"unhandled command {type(command).__name__}")


def _kind_of(state: CorpusState, source_id: str) -> str | None:
    """Which shape a source id already holds, or None if it is free."""
    record = state.documents.get(source_id)
    return None if record is None else record.kind


def _is_derived(state: CorpusState, source_id: str) -> bool:
    """Whether a source id already holds perceived text rather than fetched."""
    record = state.documents.get(source_id)
    return record is not None and getattr(record, "derived_from", None) is not None


def _holds_something_not_derived(state: CorpusState, source_id: str) -> bool:
    """Whether the id is already taken by something that is not perceived text."""
    return _kind_of(state, source_id) is not None and not _is_derived(state, source_id)


def _derived_from(state: CorpusState, source_id: str) -> str | None:
    """Which medium a source was perceived from, for naming it in a refusal."""
    record = state.documents.get(source_id)
    return getattr(record, "derived_from", None)


def _repoints_a_transcript(state: CorpusState, source_id: str, parent: str) -> bool:
    """Whether this store would move an existing transcript to a different medium."""
    return _is_derived(state, source_id) and _derived_from(state, source_id) != parent


def _reject_unless_json_list_of_strings(field: str, value: str) -> None:
    """Refuse a JSON-encoded degradations list that is not one."""
    try:
        parsed = json.loads(value)
    except (ValueError, TypeError) as error:
        raise CommandRejectedError(
            f"{field} must be a JSON list of strings; got {value!r}"
        ) from error
    if not isinstance(parsed, list) or not all(isinstance(item, str) for item in parsed):
        raise CommandRejectedError(f"{field} must be a JSON list of strings; got {value!r}")


def _reject_unless_json_list_of_objects(field: str, value: str) -> None:
    """Refuse a locator map that the resolver could not walk."""
    try:
        parsed = json.loads(value)
    except (ValueError, TypeError) as error:
        raise CommandRejectedError(
            f"{field} must be a JSON list of objects; got {value!r}"
        ) from error
    if not isinstance(parsed, list) or not all(isinstance(item, dict) for item in parsed):
        raise CommandRejectedError(f"{field} must be a JSON list of objects; got {value!r}")


def _degradations_from(event: CorpusDerivedTextStored) -> tuple[str, ...]:
    """Read an event's degradations, never raising, whatever the payload says."""
    try:
        parsed = json.loads(event.degradations)
    except (ValueError, TypeError):
        return UNREADABLE_DEGRADATIONS
    if not isinstance(parsed, list) or not all(isinstance(item, str) for item in parsed):
        return UNREADABLE_DEGRADATIONS
    return tuple(parsed)


def evolve(state: CorpusState, event: DomainEvent) -> CorpusState:
    """What each fact does to the state.

    Total on purpose: an unknown event leaves the state alone rather than
    raising, so a stream carrying an event this build does not know about still
    replays instead of failing halfway through.
    """
    match event:
        case CorpusDocumentStored():
            previous = state.documents.get(event.source_id)
            by_digest = dict(state.by_digest)
            if previous is not None and by_digest.get(previous.sha256) == event.source_id:
                del by_digest[previous.sha256]
            by_digest.setdefault(event.sha256, event.source_id)
            record = TextRecord(
                source_id=event.source_id,
                sha256=event.sha256,
                char_count=len(event.text),
                uri=event.uri,
                title=event.title,
                published_at=event.published_at,
                note=event.note,
                fetched_at=event.fetched_at,
            )
            return state.model_copy(
                update={
                    "corpus_id": event.aggregate_id,
                    "status": "created",
                    "documents": {**state.documents, event.source_id: record},
                    "by_digest": by_digest,
                }
            )

        case CorpusMediaStored():
            previous = state.documents.get(event.source_id)
            by_digest = dict(state.by_digest)
            if previous is not None and by_digest.get(previous.sha256) == event.source_id:
                del by_digest[previous.sha256]
            by_digest.setdefault(event.sha256, event.source_id)
            record = MediaRecord(
                source_id=event.source_id,
                sha256=event.sha256,
                media_type=event.media_type,
                byte_count=event.byte_count,
                uri=event.uri,
                title=event.title,
                published_at=event.published_at,
                note=event.note,
                fetched_at=event.fetched_at,
            )
            return state.model_copy(
                update={
                    "corpus_id": event.aggregate_id,
                    "status": "created",
                    "documents": {**state.documents, event.source_id: record},
                    "by_digest": by_digest,
                }
            )

        case CorpusDerivedTextStored():
            previous = state.documents.get(event.source_id)
            by_digest = dict(state.by_digest)
            if previous is not None and by_digest.get(previous.sha256) == event.source_id:
                del by_digest[previous.sha256]
            by_digest.setdefault(event.sha256, event.source_id)
            record = TextRecord(
                source_id=event.source_id,
                sha256=event.sha256,
                char_count=len(event.text),
                title=event.title,
                note=event.note,
                derived_from=event.derived_from,
                perceived_with=event.perceived_with,
                degradations=_degradations_from(event),
            )
            return state.model_copy(
                update={
                    "corpus_id": event.aggregate_id,
                    "status": "created",
                    "documents": {**state.documents, event.source_id: record},
                    "by_digest": by_digest,
                }
            )

        case CorpusDocumentDropped():
            record = state.documents.get(event.source_id)
            if record is None:
                return state
            by_digest = {
                digest: source_id
                for digest, source_id in state.by_digest.items()
                if source_id != event.source_id
            }
            return state.model_copy(
                update={
                    "documents": {
                        **state.documents,
                        event.source_id: record.model_copy(
                            update={"dropped_reason": event.reason}
                        ),
                    },
                    "by_digest": by_digest,
                }
            )

        case _:
            return state


__all__ = [
    "decide",
    "evolve",
]
