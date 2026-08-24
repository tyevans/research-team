"""Discovering the classes a document states, and refusing the ones it does not.

Extraction turns "There are six difficulties available in the game: EASY,
NORMAL, HARD, EXPERT, MASTER, and APPEND" into six unrelated `category`
entities. The class name, the membership, the ordering and the count are all in
that one sentence, and none of the four survives. This recovers them.

**Chunks the document, and used to refuse to.** This module said, until
2026-08-24, that it read the whole document and never chunked, because the rank
table's class name lives entirely in its header row, `| Rank | Reward |`, one
line long: a chunk boundary between that header and `| S rank |` leaves the
members in a chunk with no name for what they belong to, and the pass would be
blind to precisely the case it exists for.

That objection was answered before it was written.
`infrastructure/knowledge/markdown_table_chunker.py` carries a table's header
into every chunk of that table, and names taxonomy discovery as the consumer
that makes it more than tidiness. The split-table problem is not a reason to
avoid chunking here; it is a solved problem this pass declined to use. What is
left of the old reasoning is the *offset* hazard, and it is real: a chunk with a
repeated header is no longer a contiguous slice of the document, so a quote
located in chunk coordinates points at the wrong words unless it is
translated. `_to_document_span` is that translation and
`DocumentChunk.prefix_start_char` is what makes it possible.

What forced the change was a document, not a preference. `One Piece -
Wikipedia` in the owner's corpus is 218,584 characters -- about 55,000 tokens
before the prompt and the answer -- against a configured model window of
64,000. Sent whole it does not fit, discovery fails outright, and because
ontology feeds course creation, the course fails with it.

**Two sizes, not one.** `MAX_DISCOVERY_CHUNK_CHARS` is how much document text
goes into one model call; `MAX_DISCOVERY_CHARS` is the point above which the
pass refuses a document rather than making an unbounded number of calls. They
were one constant, which is exactly how a 218,584-character article reached one
prompt.

**Verification is against the document, not against plausibility.** A model that
pattern-matches a taxonomy onto a document that does not state one produces
something indistinguishable, by eye, from a real discovery. So every member name
must occur verbatim in the text, and so must the sentence cited as evidence for
the class -- the model quotes it and `_span` finds it, rather than the model
giving character offsets nothing but arithmetic could check. What is dropped is
recorded rather than discarded: a class that found five of a declared six with
no explanation cannot be judged, because the reader cannot tell an invented
member from a document that is genuinely short one, and those are opposite
conclusions about whether to trust the pass.
"""

import json
from dataclasses import dataclass
from typing import Any, Protocol

from research_team.application.corpus_read import CorpusReadPort
from research_team.domain.ontology import (
    DiscoveredClass,
    DiscoveredMember,
    EvidenceSpan,
    RejectedMember,
)

#: How much *document text* goes into one model call. Not a document ceiling
#: -- that is `MAX_DISCOVERY_CHARS` below, and the two being one constant is
#: the whole of the defect this replaced.
#:
#: **The arithmetic, so the next person can redo it against their own model
#: rather than inherit a number chosen by feel.** The configured model's window
#: is 64,000 tokens. Reserved out of it:
#:
#:   - the answer: up to 8,000 tokens. A document stating a dozen classes with
#:     twenty members each is a long JSON object, and a reply truncated by the
#:     output budget parses as nothing at all -- `parse_ontology` returns None
#:     and the chunk is lost.
#:   - `PROMPT_HEADER` and the chat framing: ~700 tokens, measured by length
#:     (2,700 characters) rather than tokenised.
#:
#: That leaves ~55,000 tokens for text. 40,000 characters is 20,000 tokens at a
#: **pessimistic 2 characters per token** -- pessimistic on purpose, because
#: pipe-heavy markdown tables tokenise far worse than prose, and the documents
#: this pass exists for are exactly the table-heavy ones. Ordinary English runs
#: nearer 4. So the estimate can be wrong by a factor of two in the direction
#: that hurts and the prompt still fits.
#:
#: The headroom is not timidity: nothing here counts tokens, and a chunk that
#: overruns the window is a provider error that costs a full call to discover.
#: A build that starts counting tokens properly can raise this.
#:
#: **What it costs: one call per chunk, where there used to be one per
#: document.** `One Piece - Wikipedia` at 218,584 characters becomes 6 calls
#: instead of 1 -- but the 1 did not fit, so the honest comparison is 6 calls
#: against a failure.
MAX_DISCOVERY_CHUNK_CHARS = 40_000

#: How much of one chunk repeats the end of the one before it. Small, and it
#: exists for one case: a class stated in a single sentence that a boundary
#: cuts in half is invisible to both neighbours. 2,000 characters is longer
#: than any sentence, and the duplicate classes it produces where a boundary
#: falls mid-table are what `merge_classes` is for -- a member found twice does
#: not appear twice.
DISCOVERY_CHUNK_OVERLAP_CHARS = 2_000

#: The longest document this pass will read. Above it the document is refused
#: and stays on the ungrouped list, rather than truncated: a truncated read
#: would drop a document's second half silently and report success, which is
#: the failure mode this whole feature is arranged against.
#:
#: **Its old justification is gone and this is the new one.** Until 2026-08-24
#: this constant was also the chunk size, and its reason for existing was that
#: one prompt cannot hold more -- "if the corpus stored it, this pass can read
#: it", kept deliberately equal to `MAX_DOCUMENT_CHARS`. Chunking removes that
#: reason entirely: any document fits, one chunk at a time. What is left is a
#: ceiling on **call count**, and that needs its own argument:
#:
#: 500,000 / `MAX_DISCOVERY_CHUNK_CHARS` is 13 calls, so this bounds one
#: document's discovery at roughly a dozen model calls. Without a ceiling a
#: single pathological document could issue hundreds, serially, against a
#: locally served model -- and the sweep that calls this walks every ungrouped
#: document in the project. Cost and latency, not context.
#:
#: The value is unchanged from 2026-08-17, when it was raised to 500,000 with
#: `MAX_DOCUMENT_CHARS`, and keeping the two equal is still the simplest
#: policy: a document the corpus accepted is one this pass will examine. The
#: difference is that equality is now a convenience rather than a necessity, so
#: lowering this to cap spend is a legitimate change where it used to create a
#: class of document nobody could examine at all.
#:
#: **The deployment note survives the rewrite**, because it is about the
#: serving stack rather than the window. Measured 2026-08-15 on the development
#: machine with Ollama's `qwen3.5:9b` standing in for a downed endpoint: a
#: 19,644-character prompt did not return within 500 seconds while a trivial
#: one answered instantly. Chunking makes that better rather than worse -- the
#: longest prompt is now `MAX_DISCOVERY_CHUNK_CHARS`, not the document -- but a
#: slow deployment now pays that latency per chunk, and a document at this
#: ceiling is a dozen of them in series.
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


@dataclass(frozen=True)
class DocumentChunk:
    """A slice of a document as the model will be shown it, and where it came from.

    `text` is what goes into a prompt. It is `prefix + document[start_char:end_char]`
    -- the prefix being text the document does **not** contain at `start_char`,
    which is how `MarkdownTableChunker` gives a chunk of table rows the header
    that names them. `prefix_start_char` is where that prefix really lives in
    the document, so a span landing inside it can still be cited.

    An ordinary chunk has an empty prefix and `prefix_start_char` of 0, and
    every offset in it translates by a single addition.

    Declared here rather than in `infrastructure/` because the application
    layer may not import it (`tests/test_architecture.py`), and declared as a
    dataclass rather than reusing redstring's `Chunk` for the same reason:
    `Chunk` carries a chunker's vocabulary -- overlap, chunking method,
    metadata keys -- none of which this pass has an opinion about.
    """

    text: str
    start_char: int
    prefix: str = ""
    prefix_start_char: int = 0


class DocumentChunkPort(Protocol):
    """Cutting a document into pieces one model call can hold.

    One method, and deliberately no size parameter: the size is a property of
    the model behind the chunker, and composition is where the two meet. A
    caller able to pass a size is a caller able to pass one the model cannot
    serve.
    """

    def chunk(self, text: str) -> list[DocumentChunk]: ...


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
        # A bare array is a reply that did not answer the question asked, not
        # a reply saying there are no classes -- and `payload.get` on a list
        # raises rather than returning None.
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
    chunk: DocumentChunk | None = None,
) -> list[DiscoveredClass]:
    """Only what the document actually supports.

    Three refusals, at two severities, and the split is the part to read twice.

    A **member** not in the text is dropped and *recorded*: the class survives
    minus one, and the reader is told which name went and why. That is what
    keeps a short class judgeable.

    A class whose **evidence quote** is not in the text is dropped whole,
    because there is nothing left for a reader to open and judge -- recording
    an artefact nobody can check is worse than losing it.

    That drop reads differently since 2026-08-24, and the change is not the one
    it looks like. It used to fire on an arithmetic slip -- the model was asked
    for character offsets and estimated them -- which was a harsh penalty for a
    failure saying nothing about whether the class was real. In practice it
    almost never fired: measured over 12 chunks of five real documents, 0 of 15
    proposed classes were dropped here, because an estimate into a 40,000-
    character chunk lands *inside* it nearly every time. The gate was not
    costing classes; it was waving through citations that pointed somewhere
    else (14 of those 15 did -- see `_span`).

    Now the model is asked for the words, so this fires only when the quote is
    absent from the text, which is the model having written a sentence the
    document does not contain. Dropping a fabricated citation is the right
    answer to that, and it stays. Same code, same severity, an entirely
    different population reaching it -- and the value of the change is in the
    spans that *pass*, not in the ones this refuses.

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

    **`chunk` decides what coordinate system the evidence was located in**, and
    it is the likeliest place for a silent wrong answer in this whole module.
    With no chunk the offsets are the document's, as they always were. With one
    they are offsets into `chunk.text`, and every one of them is plausible and
    wrong until `_to_document_span` has moved it -- a span from the ninth chunk
    of a long article resolves, renders, and quotes words nobody read. Nothing
    raises. `test_a_class_found_in_a_later_chunk_cites_the_document_not_the_chunk`
    is what fails if the translation is dropped.

    Membership is checked against `chunk.text` when there is a chunk, not
    against the whole document: the model can only copy from what it was shown,
    so a name found elsewhere in the document is a name this call did not
    justify. That is strictly the tighter check, and it is the one the module
    docstring's promise is about.
    """
    search_text = chunk.text if chunk is not None else document_text
    verified: list[DiscoveredClass] = []
    for proposal in proposals:
        name = proposal.get("name")
        kind = proposal.get("kind")
        if not isinstance(name, str) or not name.strip() or kind not in _KINDS:
            continue

        span = _span(proposal.get("evidence"), search_text)
        if span is None:
            continue
        if chunk is not None:
            translated = _to_document_span(span, chunk, document_text)
            if translated is None:
                continue
            span = translated

        members, rejected = _members(proposal.get("members"), search_text)
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


def _span(evidence: Any, text: str) -> tuple[int, int] | None:
    """Where the quoted evidence occurs in `text`, or None if it does not.

    **The model is asked for the words, not for the offsets, and this is where
    that decision is spent.** Until 2026-08-24 the prompt asked for
    `{"start": ..., "end": ...}` and this function bounds-checked the pair.
    Language models do not count characters; they estimate them. So the check
    had two failure modes: an estimate landing outside the text dropped the
    whole class for an arithmetic slip, and an estimate landing *inside* it
    passed while pointing at words the model never read.

    **Measured 2026-08-24 against `qwen3.8-27b-64k-txt`, both prompts over the
    same 12 chunks of five real corpus documents.** The second failure mode is
    effectively the only one. Under the offsets prompt the bounds check dropped
    **0 of 15** proposed classes -- an estimate into a 40,000-character chunk is
    almost always *some* range inside it -- so the gate was not costing classes.
    What it was doing was passing wrong citations: of those 15 stored spans,
    **14 pointed at text containing neither the class name nor any of its
    members.** `four seas`, whose members are North/East/West/South Blue, was
    cited to "11 consecutive years (2008-2018) and remains the only series
    with ove".

    Under the quote prompt, over the identical chunks: 16 proposals, 1 refused
    here, **14 classes verified and 13 of them citing text that names the class
    or one of its members.** So the change is close to free in volume (15
    survivors to 14; 11 merged classes to 9) and is worth roughly the whole of
    the citation: 1 correct in 15 becomes 13 correct in 14.

    That is worth stating plainly because it inverts the obvious reading of the
    old code. The `if span is None: continue` looks like the expensive line and
    is nearly dead; the silent line is `EvidenceSpan(...)` two statements
    later. Nothing about a wrong-but-inside span is visible from the running
    system, and `graph_reader.py` has been rendering these offsets into an
    `instance_of` edge's `derivation` string -- reaching `GraphCanvas.tsx` --
    for as long as the feature has existed. The citations were already on
    screen; they were just wrong.

    **What the exactness costs, measured rather than guessed.** The one class
    refused in the after arm is `four seas`, and it was refused for a reason
    worth knowing before tightening anything here: the corpus stores Wikipedia
    as markdown, so the sentence carries inline citation markup between the
    member names --
    `four seas: North Blue,<sup>[\\[Jp 7\\]](#cite_note-NB-8)</sup> East Blue,...`
    -- and the model quoted the sentence as a *reader* sees it, with the markup
    gone. The quote is honest and the document does not contain it. A
    markup-tolerant locator would recover this class, and would have to map
    offsets from normalised text back to the raw document to stay correct;
    that is a heuristic with a real failure mode of its own and it is
    deliberately not built here. On citation-dense prose this is the shape of
    what the pass now loses.

    Locating a quote with `str.find` removes both. A quote that is in the text
    yields the range it actually occupies, which is a correct citation rather
    than a plausible one; a quote that is not in the text is a fabrication, and
    there is no third answer to confuse them with. This is the same substring
    mechanism `_members` uses, and it is loose for the same reason: a stricter
    match would refuse a table header for its pipes.

    Chunking made the old shape worse rather than better -- offsets are
    chunk-relative and `_to_document_span` translates them, so the model's
    estimate was compounded by a translation of an estimate. A located quote
    goes into that translation as a real range, and the translation is the only
    arithmetic left in the path.

    `text` is what the model was shown -- a chunk when there is one -- so the
    range returned is in the coordinate system the answer was written in.
    Translation to document coordinates happens after, in `_to_document_span`.

    The first occurrence is taken. A header repeated by `MarkdownTableChunker`
    is the case that makes this matter, and the first occurrence in a chunk is
    the prefix copy, which `_to_document_span` maps to where the header really
    lives. A later duplicate would be cited into the rows.

    **The old dict shape is refused rather than accepted for a transition
    window.** The worry was that a live model handed the new prompt would keep
    emitting `{"start": ...}` some of the time, and that refusing it would cost
    classes for no gain. Measured over the 12 chunks above: **16 of 16
    proposals came back with a string**, none with the old shape, so the
    transition branch would have been dead code. It is refused rather than
    accepted on principle as well as on the count -- accepting it would keep
    exactly the guessed offsets this change exists to stop trusting, and once
    stored a class cited from an estimate is indistinguishable from one cited
    from a quote. Nothing stored needs the old shape: the stored columns are
    offsets either way, and this reads model replies, not storage.
    `test_evidence_given_as_character_offsets_is_refused` is where that
    decision lives, since the code no longer mentions it.
    """
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
    span: tuple[int, int], chunk: DocumentChunk, document_text: str
) -> tuple[int, int] | None:
    """A span in chunk coordinates, moved to the document's, or None if it cannot be.

    Three cases, and the middle one is the whole reason this pass can chunk at
    all:

    * **Entirely past the prefix.** Add `chunk.start_char - len(chunk.prefix)`.
      This is every span in an ordinary chunk, where the prefix is empty and
      the shift is just `start_char`.
    * **Entirely inside the prefix.** The prefix is a table's header, copied
      verbatim from `prefix_start_char`, so the span moves there instead. This
      is the case the old "never chunks" reasoning said was impossible to
      serve: `| Rank | Reward |` is *where the class name is stated*, and a
      pass that could not cite it would find the class and lose its evidence.
    * **Straddling the two.** The header and the chunk's first row are not
      adjacent in the document -- rows the model never saw sit between them --
      so no single half-open range covers exactly what the model quoted. The
      header's own span is returned: it is the part that names the class, it is
      text the model actually read, and it overstates nothing. Returning
      `header_start .. row_end` was rejected because it would cite intervening
      rows as evidence.

    A span that lands outside the document after translation is refused rather
    than clamped, for the reason `_span` gives: a clamped citation still
    renders, pointing at words nobody read.
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
    -- so **a member found twice must not appear twice**, which is the one
    property a reader would notice immediately and the one a naive
    concatenation gets wrong.

    Merged on the class's exact name after stripping. Not case-folded: the
    model is instructed to copy the document's own words, so two chunks of the
    same table produce the same spelling from the same header, and folding
    would merge `PRODUCER` the column heading with `Producer` the prose term on
    a document where those are genuinely two things. The cost of exactness is
    the opposite error -- one class arriving twice under two capitalisations --
    which is visible on screen, where a wrongly merged class is not.

    Everything else takes the **earliest chunk's** answer:

    * `evidence` -- the first place in the document that states the class, which
      is what a reader wants to open. A later chunk's span is a repetition of
      the same header.
    * `kind`, `declared_count`, `parent_name` -- first non-`None`, so a chunk
      that saw the sentence stating "there are six" wins over the chunks that
      only saw rows. `kind` is taken from the first chunk outright rather than
      reconciled: two chunks disagreeing about whether a scale is ordered is a
      disagreement no rule here can settle, and `ordered_scale` asserts an
      ordering the document may not have stated.
    * members -- union in arrival order, first spelling kept, and the first
      non-`None` `ordinal` for a name that arrives with and without one.

    `rejected_members` are unioned by name too, so a model inventing the same
    member in every chunk is recorded once rather than eleven times.
    """
    merged: dict[str, DiscoveredClass] = {}
    for classes in per_chunk:
        for found in classes:
            existing = merged.get(found.name)
            if existing is None:
                merged[found.name] = found
                continue
            merged[found.name] = existing.model_copy(
                update={
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
    """Both chunks' members, each name once, in the order they first arrived.

    A name seen twice keeps its first appearance, except that an ordinal fills
    in a missing one -- the chunk holding the header row is the one likely to
    state a position, and the chunk holding a later row may not.
    """
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
    """The members the document contains, and the ones it does not.

    Membership is `in search_text` -- the text the model was shown, which is
    one chunk when the pass is chunking. A substring test, not a token match.
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
        if name not in search_text:
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
        chunker: DocumentChunkPort,
    ) -> None:
        self._corpus = corpus
        self._model = model
        self._recorder = recorder
        self._chunker = chunker

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

        **One chunk whose reply is unreadable is counted and skipped; only a
        document where *every* chunk failed is `None`.** Both halves were
        argued and neither is free.

        Failing the whole document on one bad chunk is the tidier rule and was
        rejected on arithmetic: a document at `MAX_DISCOVERY_CHARS` is a dozen
        chunks, the sweep retries the document rather than the chunk, and a
        per-chunk failure rate that is merely non-zero makes a long document
        one that never completes -- it burns twelve calls per attempt to
        discover the same one chunk failing, forever. The document most likely
        to hit that is the longest, which is the one this change exists for.

        What it costs, stated plainly: a document with a partial failure is
        recorded as examined, comes off the sweep, and the classes stated only
        in the failed chunk are lost until someone re-runs that document by
        hand. The count returned does not say a chunk was skipped. That is a
        real gap and the honest place to close it is a per-chunk record on the
        event, which this change does not build.

        All-chunks-failed stays `None` because that is the shape of a
        transient: an endpoint down, a model refusing every prompt, a
        deployment timing out. Recording it as "examined, no classes" would
        retire every document in a project during one bad ten minutes.
        """
        document = await self._corpus.read_document(source_id)
        if document is None:
            return None
        if len(document.text) > MAX_DISCOVERY_CHARS:
            # Before the model call, not after: refusing afterwards would cost
            # exactly as much as doing the work.
            return None

        chunks = self._chunker.chunk(document.text)
        per_chunk: list[list[DiscoveredClass]] = []
        unreadable = 0
        for chunk in chunks:
            proposals = parse_ontology(await self._model.generate(build_prompt(chunk.text)))
            if proposals is None:
                unreadable += 1
                continue
            # Reached with `proposals == []` (the model said there are none)
            # and with a list every member of which fails verification (the
            # model said there are some and the chunk disagreed). Both are
            # "examined, states none": the reply was understood, and re-running
            # would produce the same answer at the same cost.
            per_chunk.append(
                verify_classes(
                    proposals,
                    document_text=document.text,
                    source_id=source_id,
                    chunk=chunk,
                )
            )

        if chunks and unreadable == len(chunks):
            return None

        # An empty document produces no chunks and no calls, and is recorded as
        # examined rather than refused -- there is nothing transient about it,
        # and leaving it on the sweep would re-read it forever.
        classes = merge_classes(per_chunk)
        await self._recorder.record(source_id, self._model.model_name, classes)
        return len(classes)
