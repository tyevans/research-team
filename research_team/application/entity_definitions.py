"""Generating a grounded definition of one entity, and caching it.

**Grounded is the whole feature.** A model asked "what is Acme?" will answer,
fluently, from what it read on the internet years ago -- and that answer is
indistinguishable at a glance from one derived from this project's corpus.
The reader cannot tell, which is exactly why they would trust it. So every
claim has to be attributable to a passage or an edge this service supplied,
and the parts of that rule that a prompt cannot enforce are enforced here:

* An entity with no passages is never sent to the model at all (`define`
  returns `None`). Edges alone are not enough, and not because they do not
  ground -- they legitimately shape the text below -- but because they
  cannot be *cited*: an edge has no character span, only redstring's
  document id, so no reply built from edges only could ever produce a
  citation `_verified` can confirm. Asking anyway guarantees a refused
  reply, so the guard costs one branch and removes a call that was always
  going to fail.
* Text that comes back citing nothing verifiable is refused, not stored.
  What a reader sees when that happens: the same thing they see for an
  undefinable entity -- no definition -- rather than a paragraph that reads
  as checked and is not. The alternative considered was storing the text with
  an empty citation list and letting the UI label it "unsourced"; rejected
  because a label is read once and the paragraph is read every time, and
  because a cached ungrounded definition then has to be invalidated by
  something, where a refusal simply costs one more call the next time
  somebody clicks.

**Citations are `(source_id, start, end)`, never chunk ids.** One citation
shape in the system, and the chunk index stays disposable: re-chunking the
corpus never orphans a citation a reader has already seen.

**No LangChain and no redstring here.** `DefinitionTextPort` and
`DefinitionCachePort` are narrow ports in this layer's own vocabulary, the
same shape as `UsageReadPort` and `GraphReadPort` next door, and composition
supplies the implementations. The project/tenant is likewise implicit on the
cache port for the reason `usages.py` gives for its own: an instance belongs
to one project, so a caller cannot reach another project's rows by passing a
different id. `tests/test_architecture.py` enforces the redstring half.
"""

import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID

from research_team.application.corpus_read import CorpusReadPort
from research_team.application.graph_read import GraphReadPort, Neighborhood
from research_team.application.locators import resolve
from research_team.application.usages import Usage, UsageReadPort

#: How many passages are put in front of the model. Small on purpose: these
#: are the top-ranked usages, and a definition assembled from thirty passages
#: is one the reader cannot check by reading them. It is also the whole of
#: what a citation can point at -- see `_verified`.
MAX_GROUNDING_PASSAGES = 8


@dataclass(frozen=True)
class Citation:
    """One span of one source, as character offsets.

    Deliberately not a chunk id: chunks are an index detail that gets rebuilt,
    and a citation that survives re-chunking is one a reader can still follow
    a month later.
    """

    source_id: str
    start: int
    end: int


@dataclass(frozen=True)
class ServedCitation:
    """A citation as a reader sees it: its span, plus the moment it names, if any.

    `at_seconds` is `None` for the majority case -- a source with no locator
    map, which is every text source today -- and that is the *only* thing
    `None` means here. It is never used for "resolved to zero": a citation
    into the first second of a transcript is a real, distinct answer from
    "this source has no timeline at all", and collapsing them would make a
    citation at the start of a video indistinguishable from a citation into
    an article.

    Deliberately not stored: `resolve` is arithmetic over a source's locator
    map, and the map can be corrected (`CorpusEditor.revise`) after a
    citation was generated. Baking the answer into a cached `Definition`
    would let it go stale without anything ever reprocessing it; computing it
    at serve time means a repaired map is reflected the next time anyone
    reads the citation, for free.
    """

    source_id: str
    start: int
    end: int
    at_seconds: float | None


async def serve_citations(
    read: CorpusReadPort, citations: Sequence[Citation]
) -> list[ServedCitation]:
    """Citations as a reader sees them, each carrying its moment if it has one.

    The first production caller of `locators.resolve` -- see that module's
    docstring, which named a citation renderer as the intended caller before
    one existed. This is the shared place both citation producers
    (`DefinitionService` and `ask.py`'s answer citations) funnel through,
    chosen over resolving at each call site because "does this source have a
    map" is one question with one answer regardless of who is asking, and a
    second implementation is a second place for the majority-case guarantee
    below to go unenforced.

    **A source with no locator map serves unchanged.** That is not an edge
    case: every text source has no map and never will, so this is the
    ordinary path, and `at_seconds` is `None` for it -- see `ServedCitation`
    for why `None` is not interchangeable with a resolved zero.

    One `read_document` per distinct `source_id`, not one per citation: a
    definition or an answer commonly cites the same source more than once,
    and re-fetching its map each time would be work whose result cannot
    differ.

    Only the first `TimeSpan` a citation's span resolves to is carried, per
    the spec's "Seeking" section. `resolve` can return several locators for a
    span that crosses a segment boundary, and the *citation* denotes where
    the quoted text starts, not the interval it spans in the medium -- taking
    the first is where the reader would seek to.  Locator kinds other than
    `time` (`page`, `bbox`, ...) resolve but are not looked at here: a
    citation's moment is meaningless for a source with no timeline, and this
    module is where "is there a `time` locator" is decided, not where a
    reader would want a page number instead.
    """
    maps: dict[str, str | None] = {}
    served: list[ServedCitation] = []
    for citation in citations:
        if citation.source_id not in maps:
            document = await read.read_document(citation.source_id, include_dropped=True)
            maps[citation.source_id] = document.locator_map if document else None
        locator_map = maps[citation.source_id]
        at_seconds: float | None = None
        if locator_map:
            for locator in resolve(locator_map, citation.start, citation.end):
                if locator.get("kind") == "time":
                    start_s = locator.get("start_s")
                    if isinstance(start_s, int | float) and not isinstance(start_s, bool):
                        at_seconds = float(start_s)
                        break
        served.append(
            ServedCitation(
                source_id=citation.source_id,
                start=citation.start,
                end=citation.end,
                at_seconds=at_seconds,
            )
        )
    return served


@dataclass(frozen=True)
class Definition:
    """A generated definition of one entity, with what it was derived from.

    `stale` travels with the text rather than being resolved into it, because
    stale text is still shown -- labelled -- until something regenerates it;
    see `EntityDefinitionStore.mark_stale` for why it is not simply deleted.
    """

    text: str
    citations: list[Citation]
    model: str
    generated_at: str
    stale: bool


class DefinitionTextPort(Protocol):
    """Turning a prompt into text, with the name of whatever did it.

    One method and one property, because that is all this use case needs from
    a language model. Anything wider would put LangChain's vocabulary in this
    layer's contract, which is the thing `tests/test_architecture.py` exists
    to prevent -- and would make the fake in the test suite a mock of a chat
    model rather than four lines.
    """

    @property
    def model_name(self) -> str: ...

    async def generate(self, prompt: str) -> str: ...


class DefinitionCachePort(Protocol):
    """The stored definition for an entity, if one has been generated.

    Backed by `EntityDefinitionStore` at composition time -- there is exactly
    one definition cache in this system and this port is a view onto it, not
    a second one. Stated in this layer's `Definition` rather than the store's
    `EntityDefinitionRow` so that the row's JSON-encoded `citations` column
    stays an infrastructure detail.
    """

    async def get(self, entity_id: UUID) -> Definition | None: ...

    async def put(self, entity_id: UUID, definition: Definition) -> None: ...


PROMPT_HEADER = """\
Define the entity below for a reader browsing this project's knowledge graph.

Every claim in your definition must be attributable to one of the passages or
one of the edges supplied below. Do not use anything you know about this
entity from outside this material -- if the material does not support a
claim, leave the claim out. If the material supports almost nothing, write a
single short sentence rather than padding it.

Answer with JSON and nothing else:

  {"text": "<two or three sentences>",
   "citations": [{"source_id": "<id>", "start": <int>, "end": <int>}]}

Each citation must name a passage supplied below and lie within its offsets.
A definition with no citations will be discarded, so cite the passages you
actually used.
"""


def build_prompt(
    neighborhood: Neighborhood,
    passages: list[Usage],
) -> str:
    """The whole of what the model is shown.

    A plain function rather than a method so a test can read the prompt
    without standing up a service, and so the grounding instructions live
    next to the material they are a rule about.
    """
    root = neighborhood.root
    names = {entity.entity_id: entity.name for entity in neighborhood.entities}
    names[root.entity_id] = root.name

    lines = [PROMPT_HEADER, "", f"Entity: {root.name} ({root.entity_type})"]
    if root.temporal:
        lines.append(f"When: {root.temporal}")

    lines.append("")
    lines.append("Edges:")
    if neighborhood.relationships:
        for edge in neighborhood.relationships:
            source = names.get(edge.source_id, edge.source_id)
            target = names.get(edge.target_id, edge.target_id)
            # Inferred edges are marked, because they are arithmetic over two
            # dates rather than something a document said -- see
            # `GraphRelationship.inferred`. A model that cannot tell them
            # apart will state a computed containment as a reported fact.
            suffix = "  [inferred]" if edge.inferred else ""
            lines.append(f"- {source} --{edge.relationship_type}--> {target}{suffix}")
    else:
        lines.append("- (none)")

    lines.append("")
    lines.append("Passages:")
    if passages:
        for passage in passages:
            span = f"{passage.source_id} {passage.start}-{passage.end}"
            lines.append(f"- [{span}] {passage.text}")
    else:
        lines.append("- (none)")

    return "\n".join(lines)


def _parse(raw: str) -> tuple[str, list[Citation]]:
    """The model's reply, or empty if it is not the shape that was asked for.

    Tolerant of a fenced code block, because "answer with JSON and nothing
    else" is followed most of the time and not all of it. Not tolerant of
    anything else: a reply this cannot read is a reply whose citations cannot
    be checked, and the caller treats that exactly like a reply that cited
    nothing.
    """
    text = raw.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1]
        text = text.rsplit("```", 1)[0]
    try:
        payload = json.loads(text)
    except (ValueError, TypeError):
        return "", []
    if not isinstance(payload, dict):
        return "", []
    body = payload.get("text")
    if not isinstance(body, str):
        return "", []
    citations = []
    for item in payload.get("citations") or []:
        if not isinstance(item, dict):
            continue
        source_id, start, end = item.get("source_id"), item.get("start"), item.get("end")
        if isinstance(source_id, str) and isinstance(start, int) and isinstance(end, int):
            citations.append(Citation(source_id=source_id, start=start, end=end))
    return body.strip(), citations


def _verified(citations: list[Citation], passages: list[Usage]) -> list[Citation]:
    """Only the citations that land inside a passage this service supplied.

    A citation naming a source that was never shown, or an offset outside the
    span that was, is a span the model produced rather than read -- and a
    reader has no way to tell one from the other, because both render as a
    highlighted range over source text they do not otherwise have. Dropping
    it is cheaper than a UI that has to explain a range that does not exist.
    """
    verified = []
    for citation in citations:
        for passage in passages:
            if (
                citation.source_id == passage.source_id
                and citation.start >= passage.start
                and citation.end <= passage.end
                and citation.start < citation.end
            ):
                verified.append(citation)
                break
    return verified


class DefinitionService:
    """One entity's definition: cached if it is fresh, generated if it is not."""

    def __init__(
        self,
        *,
        graph: GraphReadPort,
        usages: UsageReadPort,
        cache: DefinitionCachePort,
        model: DefinitionTextPort,
        passage_limit: int = MAX_GROUNDING_PASSAGES,
    ) -> None:
        self._graph = graph
        self._usages = usages
        self._cache = cache
        self._model = model
        self._passage_limit = passage_limit

    async def define(self, entity_id: UUID, *, force: bool = False) -> Definition | None:
        """This entity's definition, or `None` when there is nothing to ground one in.

        `None` rather than an exception or an empty `Definition`: an entity
        with no passages to cite is an ordinary state of a young corpus,
        not a failure -- the same reasoning `GraphReadPort.neighborhood`
        gives for its own `None`. An empty `Definition` was rejected because
        it is a cacheable-looking object carrying a promise it cannot keep,
        and every caller would have to check `text` anyway. The route above
        renders `None` as a null text, not a 404: the entity exists, it is
        merely undefinable today.

        `force` regenerates a definition that is not stale -- for a reader
        who has just added documents and wants the answer now, rather than
        waiting for an invalidating event that may never come for this
        entity.

        **A failed regeneration falls back to the stale cached row, labelled,
        rather than to `None`.** This is not the ordinary "no definition"
        case above -- it is a reader who has *already seen* a definition
        losing it because a refresh happened to fail (the guard tripped
        after an edit removed every passage, or the model's reply cited
        nothing verifiable). Discarding a definition the reader already
        trusts because *this* attempt to improve it came back empty is a
        worse outcome than showing the older text with `stale=True` -- which
        is exactly what `stale` is for: telling the reader the text may be
        out of date, not hiding it. `GET .../definition` calls this on every
        read (see `read_graph_definition`), so without this fallback a
        single bad extraction could permanently blank an entity's panel
        until someone got lucky with `force=True`.

        This does not cost more model calls than before: the guard in
        `_generate` still runs first, so an entity with no passages to
        ground a definition in is refused before any request reaches the
        model, stale row or not. Only entities that *were* groundable pay
        for the attempt, and most of those succeed.
        """
        cached = await self._cache.get(entity_id)
        if not force and cached is not None and not cached.stale:
            return cached

        definition = await self._generate(entity_id)
        if definition is not None:
            return definition

        # Regeneration produced nothing usable. See the docstring above --
        # the stale row (if any) is still the best answer available.
        if cached is None:
            return None
        if cached.stale:
            return cached
        return Definition(
            text=cached.text,
            citations=cached.citations,
            model=cached.model,
            generated_at=cached.generated_at,
            stale=True,
        )

    async def _generate(self, entity_id: UUID) -> Definition | None:
        """A freshly generated, verified, and cached definition -- or `None`
        if there was nothing to ground one in or the model's reply did not
        hold up. Split out of `define` so the stale-fallback logic there does
        not have to interleave with the generation steps.
        """
        neighborhood = await self._graph.neighborhood(str(entity_id))
        if neighborhood is None:
            return None

        passages = await self._usages.usages(entity_id, limit=self._passage_limit)

        # The guard, not an optimisation. See the module docstring: a bare
        # name sent to a model comes back defined from the model's own
        # memory, which is the one outcome this feature exists to prevent.
        #
        # No passages is enough on its own, edges or not -- and that is not
        # "edges do not count as grounding". Edges legitimately shape the
        # text below; they just cannot be *cited*, because redstring's
        # `Relationship` carries a document id but deliberately no span (see
        # its docstring at `redstring/domain/relationship.py:22-32`: a
        # reconstructed span "reads as evidence while being generation", the
        # same argument this module makes about ungrounded text). No span
        # upstream means no `(source_id, start, end)` `_verified` could ever
        # confirm, so with `passages == []` the refusal at :332 is knowable
        # here, before paying for the call -- not a policy choice this repo
        # is free to loosen, an absence in data this repo does not own.
        # Edge-only grounding is filed rather than built; see `BACKLOG.md`
        # B78 for what it would need and why the obvious wider fix falls
        # short.
        if not passages:
            return None

        raw = await self._model.generate(build_prompt(neighborhood, passages))
        text, claimed = _parse(raw)
        citations = _verified(claimed, passages)
        if not text or not citations:
            # Refused rather than stored -- see `define`'s docstring for what
            # the caller falls back to when this happens.
            return None

        definition = Definition(
            text=text,
            citations=citations,
            model=self._model.model_name,
            generated_at=datetime.now(UTC).isoformat(),
            stale=False,
        )
        await self._cache.put(entity_id, definition)
        return definition
