"""Discovering the classes a document states, and refusing the ones it does not.

Extraction turns "There are six difficulties available in the game: EASY,
NORMAL, HARD, EXPERT, MASTER, and APPEND" into six unrelated `category`
entities. The class name, the membership, the ordering and the count are all in
that one sentence, and none of the four survives. This recovers them.

**Reads the whole document, never chunks.** The rank table's class name lives
entirely in its header row, `| Rank | Reward |`, one line long. A chunk boundary
between that header and `| S rank |` leaves the members in a chunk with no name
for what they belong to -- the pass would be blind to precisely the case it
exists for. The cost is `MAX_DISCOVERY_CHARS`: a longer document is refused
rather than windowed, because a windowed pass reintroduces the split-table
problem with extra bookkeeping, and no measurement yet says how many real
documents exceed the ceiling.

**Verification is against the document, not against plausibility.** A model that
pattern-matches a taxonomy onto a document that does not state one produces
something indistinguishable, by eye, from a real discovery. So every member name
must occur verbatim in the text and every evidence span must lie inside it. What
is dropped is recorded rather than discarded: a class that found five of a
declared six with no explanation cannot be judged, because the reader cannot
tell an invented member from a document that is genuinely short one, and those
are opposite conclusions about whether to trust the pass.
"""

import json
from typing import Any

from research_team.domain.ontology import (
    DiscoveredClass,
    DiscoveredMember,
    EvidenceSpan,
    RejectedMember,
)

#: The longest document this pass will read. Above it the document is refused
#: and stays on the ungrouped list, rather than truncated: a truncated read
#: would drop a document's second half silently and report success, which is
#: the failure mode this whole feature is arranged against.
#:
#: Sized so the SEKAI songs document (4,890 characters, measured 2026-08-15) is
#: comfortable and a long wiki article still fits. **Not tuned against a
#: corpus-wide measurement, because none has been taken** -- and one document
#: already known to exceed it is `sekaipedia-list-of-songs` at 131,701
#: characters, which is mostly one large markdown table and therefore exactly
#: the shape this pass is best at. Take the measurement before raising this;
#: the answer to a long list of refusals is the windowed pass, not a bigger
#: number.
MAX_DISCOVERY_CHARS = 40_000

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
  - evidence: the character offsets of the sentence or table header that states
    this class, as {"start": <int>, "end": <int>}.
  - members: each member as {"name": "<exactly as the document spells it>",
    "ordinal": <int from 0, only for ordered_scale>}.
  - parent_name: the name of the class this one nests under, if any.

Every member name must appear in the document exactly as you write it. A name
that does not will be discarded and reported as a rejection, so copy rather
than paraphrase.

Answer with JSON and nothing else:

  {"classes": [{"name": ..., "kind": ..., "declared_count": ...,
                "evidence": {"start": ..., "end": ...},
                "members": [{"name": ..., "ordinal": ...}],
                "parent_name": ...}]}

If the document states no classes, answer {"classes": []}. That is a normal
answer and is preferred over inventing one.

Document:
"""


def build_prompt(document_text: str) -> str:
    """The whole document, under the rules that constrain what may be said of it.

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
        # A bare array is a reply that did not answer the question asked, not
        # a reply saying there are no classes -- and `payload.get` on a list
        # raises rather than returning None.
        return None
    classes = payload.get("classes")
    if not isinstance(classes, list):
        return None
    return [item for item in classes if isinstance(item, dict)]


def verify_classes(
    proposals: list[dict[str, Any]], *, document_text: str, source_id: str
) -> list[DiscoveredClass]:
    """Only what the document actually supports.

    Three refusals, at two severities, and the split is the part to read twice.

    A **member** not in the text is dropped and *recorded*: the class survives
    minus one, and the reader is told which name went and why. That is what
    keeps a short class judgeable.

    A class whose **evidence span** is outside the document is dropped whole,
    because there is nothing left for a reader to open and judge -- recording
    an artefact nobody can check is worse than losing it.

    A class with an unrecognised **kind** is dropped whole because `kind`
    selects the entire rendering. Coercing it to `unordered_set` would be
    survivable; coercing it to anything turns a misread into a claim about the
    text, and `ordered_scale` in particular asserts an ordering the document
    may never have stated.

    `declared_count` is deliberately *not* reconciled against the members
    found. A class naming nine members against a stated 268 (measured in
    `wiki-roman-economy`, 2026-08-15) is kept with both numbers intact: a
    ratio threshold would be a number nobody could justify, and a reader sees
    "9 of 268" for what it is faster than any rule could classify it.
    """
    verified: list[DiscoveredClass] = []
    for proposal in proposals:
        name = proposal.get("name")
        kind = proposal.get("kind")
        if not isinstance(name, str) or not name.strip() or kind not in _KINDS:
            continue

        span = _span(proposal.get("evidence"), document_text)
        if span is None:
            continue

        members, rejected = _members(proposal.get("members"), document_text)
        if not members:
            continue

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
            )
        )
    return verified


def _span(evidence: Any, document_text: str) -> tuple[int, int] | None:
    """The evidence offsets, if they name a range that exists in the document.

    Bounds-checked rather than clamped: a clamped span still renders, pointing
    at words the model never read, which is the failure a citation is supposed
    to make impossible.
    """
    if not isinstance(evidence, dict):
        return None
    start, end = evidence.get("start"), evidence.get("end")
    if not (isinstance(start, int) and isinstance(end, int)):
        return None
    if not 0 <= start < end <= len(document_text):
        return None
    return start, end


def _members(
    proposed: Any, document_text: str
) -> tuple[list[DiscoveredMember], list[RejectedMember]]:
    """The members the document contains, and the ones it does not.

    Membership is `in document_text` -- a substring test, not a token match.
    It is deliberately the loosest check that still refuses an invented name:
    a stricter one would reject `salt merchants (salinatores)` for its
    parentheses or `S rank` for its space, and the names this pass exists to
    find are exactly the awkwardly-punctuated ones. The cost is that a short
    member name can match incidentally -- "EASY" inside "EASYGOING" -- which
    lets a coincidence through as a member rather than letting a real member
    through as a rejection. That is the right direction for a check whose
    output is shown to a reader beside the sentence it came from.
    """
    members: list[DiscoveredMember] = []
    rejected: list[RejectedMember] = []
    for item in proposed or []:
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        if not isinstance(name, str) or not name.strip():
            continue
        if name not in document_text:
            rejected.append(
                RejectedMember(name=name, reason="not found in the document, verbatim")
            )
            continue
        ordinal = item.get("ordinal")
        members.append(
            DiscoveredMember(name=name, ordinal=ordinal if isinstance(ordinal, int) else None)
        )
    return members, rejected
