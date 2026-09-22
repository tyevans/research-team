"""Ontology proposal prompt construction, parsing, span translation,
verification, and cross-chunk merging.

Extracted from ontology_discovery.py to isolate algorithmic verification and
coordinate translation rules from document reading and service orchestration.
"""

import json
from typing import TYPE_CHECKING, Any

from research_team.knowledge.domain.ontology import (
    DiscoveredClass,
    DiscoveredMember,
    EvidenceSpan,
    RejectedMember,
)

if TYPE_CHECKING:
    pass

_KINDS = frozenset({"ordered_scale", "unordered_set", "taxonomy"})

PROMPT_HEADER = """\
Find the classes this document states outright, and nothing else.

A class is a named group whose members the document actually lists -- a
sentence that enumerates them, a table whose header names them, or a section
that introduces them as a set. Report only classes the document names. Do not
group things yourself, do not use anything you know about this subject from
outside the document, and do not report a class the document merely implies.

Report a class only where the document gives the members it has, not where it
offers examples of a larger set. "There are six difficulties: EASY, NORMAL,
HARD, EXPERT, MASTER, and APPEND" states its members. "attested for a wide
range of occupations, including fishermen, salt merchants, olive oil dealers"
gives three examples of many and is not a class. "including", "such as", "for
example" and "among others" all mark a list you should not report.

Two things contrasted are not a class either. "Official cults were state
funded. Non-official cults were funded by private individuals" names no group
and lists no members; it is a sentence about two things, not a set.

For each class give:
  - name: what the document calls the group, in its own words.
  - kind: "ordered_scale" if the document states an order or a progression,
    "taxonomy" if the class has named subclasses, "unordered_set" otherwise.
    Do not report an order the document does not state.
  - declared_count: the number the document states, if it states one ("There
    are six difficulties" -> 6). Omit it if the document gives no number. Do
    not count the members yourself.
  - evidence: the sentence or table header that states this class, copied from
    the document exactly as it appears.
  - members: each member as {"name": "<exactly as the document spells it>",
    "ordinal": <int from 0, only for ordered_scale>}.
  - parent_name: the name of the class this one nests under, if any.

Every member name must appear in the document exactly as you write it. A name
that does not will be discarded and reported as a rejection, so copy rather
than paraphrase.

The same holds for evidence: quote the document, do not summarise it. A class
whose evidence cannot be found in the document is discarded whole, so keep the
quote short enough to copy without a slip -- one sentence, or one table header
row -- and copy it character for character, including any punctuation and
table pipes.

Answer with JSON and nothing else:

  {"classes": [{"name": ..., "kind": ..., "declared_count": ...,
                "evidence": "...",
                "members": [{"name": ..., "ordinal": ...}],
                "parent_name": ...}]}

If the document states no classes, answer {"classes": []}. That is a normal
answer and is preferred over inventing one.

Document:
"""


def build_prompt(document_text: str) -> str:
    """One chunk of document text, under the rules that constrain what may be said of it.

    The prompt calls its material "the document" and still does, though it is
    now a chunk of one. That is deliberate: the wording was argued out against
    what the model should refuse to claim, and telling it "this is an excerpt"
    invites exactly the hedging this pass does not want -- a model that thinks
    it is seeing part of something reports classes it expects the rest to
    complete. Every rule in `PROMPT_HEADER` reads correctly about a chunk.

    The rules sit in the same string as the material, for the reason
    `ChatModelDefinitionText` gives for using a single `HumanMessage`:
    splitting them across two messages would put half the contract somewhere
    the application-layer test of the prompt could not see it.
    """
    return f"{PROMPT_HEADER}\n{document_text}\n"


def parse_ontology(raw: str) -> list[dict[str, Any]] | None:
    """The model's proposals, or `None` if the reply is not the asked-for shape.

    **`None` and `[]` are different answers and callers act differently on
    each.** `[]` is the model saying "this document states no classes", which
    records the document as examined and takes it off the sweep. `None` is a
    reply nobody could read, which has to leave the document on the sweep --
    otherwise a single transient failure marks it permanently done and nobody
    retries it. Collapsing the two into `[]` is the bug this signature exists
    to prevent.

    Returns raw dicts rather than `DiscoveredClass`: nothing here is believed
    yet, and constructing the domain type before verification would make an
    invented class and a discovered one the same type at exactly the point
    where they still have to be told apart.

    Tolerant of a fenced code block, because "answer with JSON and nothing
    else" is followed most of the time and not all of it. Not tolerant of
    anything else.
    """
    text = raw.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1]
        text = text.rsplit("```", 1)[0]
    try:
        payload = json.loads(text)
    except (ValueError, TypeError):
        return None
    if not isinstance(payload, dict):
        return None
    classes = payload.get("classes")
    if not isinstance(classes, list):
        return None
    return [item for item in classes if isinstance(item, dict)]


def verify_classes(
    proposals: list[dict[str, Any]],
    *,
    document_text: str,
    source_id: str,
    chunk: Any | None = None,
    strict: bool = True,
) -> list[DiscoveredClass]:
    """Only what the document actually supports.

    Three refusals, at two severities, and the split is the part to read twice.

    A **member** not in the text is dropped and *recorded*: the class survives
    minus one, and the reader is told which name went and why. That is what
    keeps a short class judgeable.

    A class whose **evidence quote** is not in the text is dropped whole,
    because there is nothing left for a reader to open and judge -- recording
    an artefact nobody can check is worse than losing it.

    `strict=False` keeps a class whose quote is absent, and cites a member
    instead. The lenient pass asks a weaker question and says so in the answer.

    A class with an unrecognised **kind** is dropped whole because `kind`
    selects the entire rendering.

    `chunk` decides what coordinate system the evidence was located in.
    With no chunk the offsets are the document's. With one they are offsets into
    `chunk.text`, translated to document coordinates via `_to_document_span`.
    """
    search_text = chunk.text if chunk is not None else document_text
    verified: list[DiscoveredClass] = []
    for proposal in proposals:
        name = proposal.get("name")
        kind = proposal.get("kind")
        if not isinstance(name, str) or not name.strip() or kind not in _KINDS:
            continue

        members, rejected = _members(proposal.get("members"), search_text)
        if not members:
            continue

        quoted = True
        span = _span(proposal.get("evidence"), search_text)
        if span is None:
            if strict:
                continue
            span = _span(members[0].name, search_text)
            if span is None:  # pragma: no cover - `_members` proved it is there
                continue
            quoted = False
        if chunk is not None:
            translated = _to_document_span(span, chunk, document_text)
            if translated is None:
                continue
            span = translated

        declared = proposal.get("declared_count")
        parent = proposal.get("parent_name")
        verified.append(
            DiscoveredClass(
                name=name.strip(),
                kind=kind,
                evidence=EvidenceSpan(source_id=source_id, start=span[0], end=span[1]),
                members=members,
                declared_count=declared if isinstance(declared, int) else None,
                parent_name=parent if isinstance(parent, str) and parent.strip() else None,
                rejected_members=rejected,
                evidence_quoted=quoted,
            )
        )
    return verified


def _span(evidence: Any, text: str) -> tuple[int, int] | None:
    """Where the quoted evidence occurs in `text`, or None if it does not."""
    if not isinstance(evidence, str):
        return None
    quote = evidence.strip()
    if not quote:
        return None
    start = text.find(quote)
    if start < 0:
        return None
    return start, start + len(quote)


def _to_document_span(
    span: tuple[int, int], chunk: Any, document_text: str
) -> tuple[int, int] | None:
    """A span in chunk coordinates, moved to the document's, or None if it cannot be.

    Three cases:
    * Entirely past prefix: add `chunk.start_char - len(chunk.prefix)`.
    * Entirely inside prefix: mapped to `chunk.prefix_start_char + offset`.
    * Straddling prefix and body: maps to the header's own span in document.
    """
    start, end = span
    prefix_length = len(chunk.prefix)
    shift = chunk.start_char - prefix_length

    if start >= prefix_length:
        moved = (start + shift, end + shift)
    elif end <= prefix_length:
        moved = (chunk.prefix_start_char + start, chunk.prefix_start_char + end)
    else:
        moved = (chunk.prefix_start_char, chunk.prefix_start_char + prefix_length)

    if not 0 <= moved[0] < moved[1] <= len(document_text):
        return None
    return moved


def merge_classes(per_chunk: list[list[DiscoveredClass]]) -> list[DiscoveredClass]:
    """One document's classes, from the several chunks that each stated part of one.

    Two chunks of one table both report the class its header names, and with
    `DISCOVERY_CHUNK_OVERLAP_CHARS` of overlap the rows on the seam are in both
    -- so a member found twice must not appear twice.
    """
    merged: dict[str, DiscoveredClass] = {}
    for classes in per_chunk:
        for found in classes:
            existing = merged.get(found.name)
            if existing is None:
                merged[found.name] = found
                continue
            upgrade = (
                {"evidence": found.evidence, "evidence_quoted": True}
                if found.evidence_quoted and not existing.evidence_quoted
                else {}
            )
            merged[found.name] = existing.model_copy(
                update={
                    **upgrade,
                    "members": _merge_members(existing.members, found.members),
                    "declared_count": (
                        existing.declared_count
                        if existing.declared_count is not None
                        else found.declared_count
                    ),
                    "parent_name": existing.parent_name or found.parent_name,
                    "rejected_members": _merge_rejections(
                        existing.rejected_members, found.rejected_members
                    ),
                }
            )
    return list(merged.values())


def _merge_members(
    existing: list[DiscoveredMember], found: list[DiscoveredMember]
) -> list[DiscoveredMember]:
    """Both chunks' members, each name once, in the order they first arrived."""
    by_name: dict[str, DiscoveredMember] = {}
    for member in [*existing, *found]:
        seen = by_name.get(member.name)
        if seen is None:
            by_name[member.name] = member
        elif seen.ordinal is None and member.ordinal is not None:
            by_name[member.name] = seen.model_copy(update={"ordinal": member.ordinal})
    return list(by_name.values())


def _merge_rejections(
    existing: list[RejectedMember], found: list[RejectedMember]
) -> list[RejectedMember]:
    """Every refused name once, with the reason it was first refused."""
    by_name: dict[str, RejectedMember] = {}
    for rejection in [*existing, *found]:
        by_name.setdefault(rejection.name, rejection)
    return list(by_name.values())


def _members(
    proposed: Any, search_text: str
) -> tuple[list[DiscoveredMember], list[RejectedMember]]:
    """The members the document contains, and the ones it does not."""
    members: list[DiscoveredMember] = []
    rejected: list[RejectedMember] = []
    for item in proposed or []:
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        if not isinstance(name, str) or not name.strip():
            continue
        cleaned_name = name.strip()
        if cleaned_name not in search_text and name not in search_text:
            rejected.append(
                RejectedMember(name=cleaned_name, reason="not found in the document, verbatim")
            )
            continue
        ordinal = item.get("ordinal")
        members.append(
            DiscoveredMember(
                name=cleaned_name, ordinal=ordinal if isinstance(ordinal, int) else None
            )
        )
    return members, rejected


__all__ = [
    "PROMPT_HEADER",
    "build_prompt",
    "merge_classes",
    "parse_ontology",
    "verify_classes",
]
