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
from typing import Any, Protocol

from research_team.application.corpus_read import CorpusReadPort
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
#: **Deliberately equal to `MAX_DOCUMENT_CHARS`**, the cap the corpus itself
#: enforces on a stored document. That is the whole justification, and it is
#: the reason this is not a round number chosen for comfort: if a document is
#: in the corpus at all, this pass can read it. Any smaller value creates a
#: class of document that a project holds and this feature silently cannot
#: examine -- and the refusals do not fall evenly, which is the part that made
#: the first number actively harmful.
#:
#: The first number was 40,000, and the measurement that condemned it was taken
#: on 2026-08-15 against the recovery database: **6 of 15 documents exceeded
#: it, holding 70% of the corpus by text.** Among them were
#: `wiki-roman-religion` (173,258) and `wiki-roman-economy` (82,764), which
#: between them hold 100 of Ancient Rome's 116 `category` entities -- so the
#: ceiling refused precisely the documents most likely to contain classes, and
#: a class count taken under it would have reported "this corpus states no
#: classes" when what happened is that nobody read it. A cap that biases the
#: evidence toward its own designer's prediction is worse than no cap.
#:
#: **What it costs: one larger model call per document, not per chunk.** This
#: pass makes exactly one call whatever the document's length -- it does not
#: chunk, by design (see the module docstring on the table header). So the cost
#: of raising it is a longer prompt on the few documents that need one, not a
#: multiplier on all of them.
#:
#: **This is a policy, and a deployment still has to be able to honour it.**
#: The cap says "if the corpus stored it, this pass may read it"; it cannot say
#: the serving stack will. Measured 2026-08-15 on the development machine, with
#: the configured endpoint (`localhost:8080`, `qwen3.6-27b-mtp`) down and
#: Ollama's `qwen3.5:9b` standing in: a 19,644-character prompt did not return
#: within 500 seconds, while a trivial one answered instantly. So on that
#: machine, that day, a document a third of this cap was already unservable --
#: and the largest real document in the corpus is 173,258.
#:
#: That is a property of the deployment rather than of this code, and it is
#: recorded here because the failure it produces is a timeout rather than a
#: refusal: the document stays ungrouped, which is the correct outcome, but it
#: costs the whole timeout to reach it. A deployment that cannot serve long
#: prompts wants a *lower* value here, set deliberately and with this note
#: read, rather than the 40,000 that was here before -- which was low for no
#: stated reason and biased the evidence (above).
#:
#: **What would make this wrong later**, in the order it is likely to happen: a
#: model whose context window cannot hold 500,000 characters of prompt, which
#: is where the refusal would start being a real limit rather than a formality;
#: or `MAX_DOCUMENT_CHARS` rising, at which point this must rise with it or
#: quietly reintroduce the gap. It is not pinned to that constant in code --
#: importing it would point the application layer at a sibling for a number
#: that is a judgement rather than a shared fact -- so the two are kept equal
#: by this comment and by whoever reads it next.
#:
#: The windowed pass stays **deliberately unbuilt**. It is what a document
#: genuinely larger than a context window needs, and its boundaries reintroduce
#: the split-table problem this pass exists to avoid, so it wants its own
#: design rather than an increment here.
#:
#: **The first of those two has now happened at the same time as the second.**
#: Raised from 200,000 to 500,000 on 2026-08-17 with `MAX_DOCUMENT_CHARS`, to
#: keep the equality above. 500,000 characters is roughly 125,000 tokens of
#: prompt, which is past the context window of a good many locally served
#: models -- so on such a deployment this ceiling is now the formality the note
#: above warns about, and the real refusal comes from the model. That failure
#: is a provider error rather than a silent truncation, which is the outcome
#: this feature is arranged for, but it is not free: it costs a full call to
#: reach. A deployment serving a short-context model wants a lower value here,
#: set deliberately.
MAX_DISCOVERY_CHARS = 500_000

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


class OntologyTextPort(Protocol):
    """Turning a prompt into text, with the name of whatever did it.

    One method and one property, mirroring `DefinitionTextPort` and for the
    identical reason: anything wider would put LangChain's vocabulary in this
    layer's contract, which is what `tests/test_architecture.py` exists to
    prevent, and would make the fake in the test suite a mock of a chat model
    rather than six lines.
    """

    @property
    def model_name(self) -> str: ...

    async def generate(self, prompt: str) -> str: ...


class OntologyRecordPort(Protocol):
    """Appending the discovery event, without naming an event store here.

    The application layer states what it needs recorded; where that lands is
    infrastructure's business -- the same division `KnowledgePort.ingest` keeps
    between "extract this document" and redstring's own append.
    """

    async def record(
        self, source_id: str, model_version: str, classes: list[DiscoveredClass]
    ) -> None: ...


class OntologyDiscoveryService:
    """One document's classes: read it, ask, verify, record.

    Bound to one project through the `CorpusReadPort` and the recorder it is
    handed, never through a parameter -- the same implicit binding
    `GraphReadPort` documents at length, and for the same reason: a project id
    a caller can pass is a knob that can be turned to the wrong project.
    """

    def __init__(
        self,
        *,
        corpus: CorpusReadPort,
        model: OntologyTextPort,
        recorder: OntologyRecordPort,
    ) -> None:
        self._corpus = corpus
        self._model = model
        self._recorder = recorder

    async def discover(self, source_id: str) -> int | None:
        """How many classes were recorded, or `None` when nothing was.

        **An empty result is recorded, and that is not the same as `None`.**
        Zero says "examined, states no classes" and takes the document off the
        sweep. `None` says "not examined" and leaves it on. Two of the three
        `None` paths below are transient -- a reply that failed to parse, and a
        document over the ceiling that a windowed pass would later reach -- so
        recording either as "done" would retire a document nobody has actually
        looked at.

        The three `None` cases are deliberately not distinguished in the return
        type. They differ in cause and agree in consequence: nothing recorded,
        still ungrouped, and retry is the answer to all three. A richer result
        would be three cases every caller has to handle in order to do one
        thing.
        """
        document = await self._corpus.read_document(source_id)
        if document is None:
            return None
        if len(document.text) > MAX_DISCOVERY_CHARS:
            # Before the model call, not after: refusing afterwards would cost
            # exactly as much as doing the work.
            return None

        proposals = parse_ontology(await self._model.generate(build_prompt(document.text)))
        if proposals is None:
            return None

        # Reached with `proposals == []` (the model said there are none) and
        # with a list every member of which fails verification (the model said
        # there are some and the document disagreed). Both are "examined,
        # states none": the reply was understood, and re-running would produce
        # the same answer at the same cost.
        classes = verify_classes(proposals, document_text=document.text, source_id=source_id)
        await self._recorder.record(source_id, self._model.model_name, classes)
        return len(classes)
