"""LLM provider wrappers, date normalization, and reporting helpers for redstring."""

import logging
from datetime import UTC, datetime
from typing import Any

from redstring import LlmProvider

from research_team.infrastructure.knowledge.temporal_expressions import (
    RAW_TEMPORAL_PROPERTY,
    normalize_for_parsing,
)
from research_team.knowledge.application import (
    ExtractionNote,
    ExtractionReporter,
)

logger = logging.getLogger(__name__)

__all__ = [
    "_CountingProvider",
    "_DatingProvider",
    "_batches",
    "_no_announcement",
    "_parse_published_at",
    "_reporting",
    "_with_respelled_dates",
]


class _CountingProvider:
    """An `LlmProvider` that says how many calls have been made through it.

    `build_graph` takes no callbacks and is one opaque await containing domain
    classification, chunking and a call per chunk -- the longest part of an
    ingest, and the part a watcher most needs to see moving. `LlmProvider` is
    a single-method protocol, so wrapping it is the whole cost of getting
    inside.

    It counts **calls, not chunks.** The chunk count is not knowable before
    extraction runs, and "chunk 4 of 9" would be a denominator invented here
    that nobody could check.
    """

    def __init__(self, inner: LlmProvider, announce) -> None:
        self._inner = inner
        self._announce = announce
        self._calls = 0

    @property
    def model(self) -> str:
        return self._inner.model

    @property
    def calls(self) -> int:
        return self._calls

    async def extract(self, text, schema, *, system_prompt=None):
        self._calls += 1
        self._announce(self._calls)
        return await self._inner.extract(text, schema, system_prompt=system_prompt)


class _DatingProvider:
    """An `LlmProvider` that respells dates on the way back from the model.

    **The only seam available.** The correction has to land between the model
    answering and redstring parsing, and `map_extraction` runs inside
    `build_graph`, which writes the graph store and builds the
    `DocumentExtracted` event together. Correcting the entities afterwards
    would fix the event and leave the store disagreeing with it, so the
    correction goes in the input where there is exactly one copy of it.

    Wraps `_CountingProvider` rather than replacing it: counting calls and
    respelling dates are unrelated jobs, and one class doing both would be
    harder to read than two doing one each. See
    `temporal_expressions.py` for what is respelled and the measurements
    behind each rule.
    """

    def __init__(self, inner: LlmProvider) -> None:
        self._inner = inner

    @property
    def model(self) -> str:
        return self._inner.model

    async def extract(self, text, schema, *, system_prompt=None):
        answer = await self._inner.extract(text, schema, system_prompt=system_prompt)
        return _with_respelled_dates(answer)


def _with_respelled_dates(extraction):
    """`extraction` with every entity's temporal expression normalised.

    Rebuilt by `model_copy` rather than mutated: the pipeline holds the same
    answer object for gleaning and carryover, and editing it in place would
    make what a later stage reads depend on whether this ran first.
    """
    entities = []
    changed = False
    for candidate in extraction.entities:
        # `properties` first, and that is not a fallback -- it is where the
        # date usually is. Traced against qwen3.8-27b-mtp on the real 'Edict
        # of Milan' article: across three chunks every `temporal_expression`
        # field came back None while `properties` held
        # {"temporal_expression": "AD 380", "outcome": ...}. The model files
        # the date beside `outcome`, `role` and `creator`, which is where the
        # domain schema's own per-type properties go, and the prompt's phrase
        # "that entity's `temporal_expression` field" does nothing to single
        # it out. The schema field is read second because the model does
        # sometimes use it, and when it does it is the more direct answer.
        raw = candidate.properties.get(RAW_TEMPORAL_PROPERTY) or candidate.temporal_expression
        if not isinstance(raw, str) or not raw.strip():
            entities.append(candidate)
            continue
        changed = True
        entities.append(
            candidate.model_copy(
                update={
                    "temporal_expression": normalize_for_parsing(raw),
                    "properties": {**candidate.properties, RAW_TEMPORAL_PROPERTY: raw},
                }
            )
        )
    if not changed:
        return extraction
    return extraction.model_copy(update={"entities": entities})


def _reporting(report: ExtractionReporter | None, source_id: str):
    """A guarded `report`, or a no-op.

    Guarded rather than trusted: a listener that raises must not cost a
    document that has already been fetched and paid for. The work is what
    matters; the telling about it is not. A no-op when `report` is None so
    every call site can announce unconditionally rather than guard twice.
    """

    def announce(stage: str, **fields: Any) -> None:
        if report is None:
            return
        try:
            report(ExtractionNote(source_id=source_id, stage=stage, **fields))
        except Exception:
            # Broad on purpose -- see the docstring: a listener is arbitrary
            # caller code and any failure in it must cost nothing. No `noqa`,
            # because `exc_info=True` is ruff's own signal that this handles
            # the exception rather than swallowing it.
            logger.warning("an extraction reporter raised; carrying on", exc_info=True)

    return announce


def _batches(items, size: int):
    """Consecutive slices of at most `size`. The last may be short.

    Same shape as redstring's own `_batches`, duplicated rather than imported
    because it is private there and a four-line generator is a cheaper thing
    to own than a dependency on another package's underscore.
    """
    for start in range(0, len(items), size):
        yield items[start : start + size]


def _no_announcement(stage: str, **fields: Any) -> None:
    """The default announcer: says nothing.

    `_consolidate` has two callers and only one of them is watching. A default
    here beats a required parameter that `reconsolidate` would have to satisfy
    with a throwaway lambda at every call site -- and beats an
    `announce=None` sentinel that every announcement inside the loop would
    have to test for.
    """


def _parse_published_at(raw: str | None) -> datetime | None:
    """Read a source's publication date, or give up quietly.

    redstring wants a `datetime`; sources supply prose. ISO-8601 is what
    structured metadata actually emits (`article:published_time`, JSON-LD,
    sitemaps), so it is the only format worth accepting -- a date-guessing
    library would turn ambiguity into confident wrong answers, and a wrong
    date on a citation is worse than an absent one.

    Anything else returns None and the caller keeps the raw string in the
    document's metadata: the date is still there for a human reading the
    citation, it just cannot be sorted or filtered on. Refusing the ingest
    over it would trade the whole document for one field.

    redstring rejects a naive datetime outright, so a bare `YYYY-MM-DD` --
    the most common thing a source publishes -- is read as UTC. That is a
    guess of up to a day either way, which no citation cares about, and the
    alternative is discarding every date that came without a zone.
    """
    if raw is None:
        return None
    candidate = raw.strip()
    if not candidate:
        return None
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
