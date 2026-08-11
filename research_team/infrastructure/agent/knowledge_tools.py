"""The knowledge graph, as three tools.

Shaped like `search.py`: results are capped and flattened before they reach the
model, and a failure comes back as text rather than an exception. A tool that
raises turns an outage into a broken turn; a tool that says what happened lets
the model carry on and leaves a readable record.
"""

from uuid import UUID

from langchain_core.tools import BaseTool, tool

from research_team.application.knowledge import (
    GRAPH_SEARCH_TOOL,
    REMEMBER_PAGE_TOOL,
    REMEMBER_TOOL,
    UNMERGE_TOOL,
    ExtractionReporter,
    IngestReport,
    KnowledgeError,
    KnowledgePort,
    Match,
    SourceRef,
)
from research_team.infrastructure.agent.recall import PageMemo


def format_ingest(report: IngestReport) -> str:
    """What one ingest did, including what it merged.

    The merges are listed rather than counted because listing them is what
    makes the agent's override possible at all -- an id it cannot see is an id
    it cannot pass to `unmerge`.
    """
    lines = [
        f"Recorded {report.source_id}: {report.entity_count} entities, "
        f"{report.relationship_count} relationships."
    ]
    if report.domain is not None:
        if report.domain_confidence == 0.0:
            lines.append(
                f"Schema: {report.domain} (confidence 0.0 -- the classifier gave "
                f"up and fell back; treat the shape as unverified)."
            )
        elif report.domain_confidence is not None:
            lines.append(
                f"Schema: {report.domain} (confidence {report.domain_confidence:.2f})."
            )
        else:
            lines.append(f"Schema: {report.domain}.")
    if report.merges:
        lines.append(f"Consolidated {len(report.merges)}:")
        for merge in report.merges:
            absorbed = ", ".join(merge.absorbed_names) or "(none named)"
            reason = merge.reason or "no reason recorded"
            lines.append(
                f"  {merge.canonical_name} absorbed {absorbed} -- {reason} "
                f"[merge_id {merge.merge_id}]"
            )
    if report.consolidation_failures:
        lines.append(
            f"{report.consolidation_failures} entit(ies) could not be consolidated; "
            f"the extraction still stands."
        )
    return "\n".join(lines)


def format_matches(matches: list[Match]) -> str:
    if not matches:
        return "No matching entities."
    return "\n".join(
        f"{match.name} ({match.entity_type}) -- {match.relationship_count} "
        f"relationship(s) [{match.entity_id}]"
        for match in matches
    )


def build_knowledge_tools(
    knowledge: KnowledgePort,
    *,
    limit: int = 10,
    report: ExtractionReporter | None = None,
    pages: PageMemo | None = None,
) -> tuple[BaseTool, ...]:
    """`remember`, `graph_search` and `unmerge` over one project's graph, plus
    `remember_page` when `pages` is supplied.

    `report` is where an ingest's progress goes while it is happening. Optional
    because a build with no web layer has nobody to tell: the CLI and every
    test that wires these tools directly want the same three tools and no
    channel, and requiring one would make them invent a sink to discard.

    `pages` is what `fetch` retained in this process, and is what
    `remember_page` resolves a URL against. Optional and, when absent,
    `remember_page` is not registered at all -- a tool that could never
    resolve anything would cost the model turns to discover.
    """

    @tool(REMEMBER_TOOL)
    async def remember(
        text: str,
        source_id: str,
        note: str = "",
        uri: str = "",
        title: str = "",
        published_at: str = "",
    ) -> str:
        """Commit text to the graph, extracting entities and relationships from it."""
        try:
            ingested = await knowledge.ingest(
                SourceRef(
                    source_id=source_id,
                    text=text,
                    note=note or None,
                    # Empty becomes None rather than travelling as "". A blank
                    # uri in the corpus is indistinguishable from a page
                    # fetched from nowhere, and the tool boundary is where a
                    # model's "I have nothing for this" arrives as "".
                    uri=uri or None,
                    title=title or None,
                    published_at=published_at or None,
                ),
                report=report,
            )
        except KnowledgeError as error:
            return f"Could not record this: {error}"
        return format_ingest(ingested)

    remember_page: BaseTool | None = None
    if pages is not None:
        # Defined inside this branch, rather than unconditionally with a
        # runtime `assert pages is not None`, so the closure over `pages` is
        # narrowed by the type checker without a check that could only ever
        # fire on a wiring bug this branch already prevents.
        @tool(REMEMBER_PAGE_TOOL)
        async def remember_page(url: str, source_id: str, note: str = "") -> str:
            """Commit a page you have already fetched, by its URL, without re-typing it."""
            retained = pages.get(url)
            if retained is None:
                # In band, naming the URL, rather than storing nothing quietly.
                # A silent no-op is indistinguishable from success, and the
                # corpus would be missing a document nobody was told about.
                return (
                    f"Nothing retained for {url} -- it was not read in this "
                    f"process, or was read more than an hour ago. `fetch` it, "
                    f"then call this again."
                )
            try:
                ingested = await knowledge.ingest(
                    SourceRef(
                        source_id=source_id,
                        text=retained.text,
                        note=note or None,
                        uri=retained.uri,
                        title=retained.title,
                        published_at=retained.published_at,
                        fetched_at=retained.fetched_at,
                    ),
                    report=report,
                )
            except KnowledgeError as error:
                return f"Could not record this: {error}"
            return format_ingest(ingested)

    @tool(GRAPH_SEARCH_TOOL)
    async def graph_search(query: str) -> str:
        """Find entities in the project's knowledge graph by name."""
        try:
            matches = await knowledge.search(query, limit=limit)
        except KnowledgeError as error:
            return f"Could not search the graph: {error}"
        return format_matches(matches)

    @tool(UNMERGE_TOOL)
    async def unmerge(merge_id: str) -> str:
        """Reverse a consolidation that joined two entities that are not the same thing."""
        try:
            parsed = UUID(merge_id)
        except ValueError:
            return f"{merge_id!r} is not a valid merge id; use the one `remember` printed."
        try:
            record = await knowledge.undo_merge(parsed)
        except KnowledgeError as error:
            return f"Could not reverse that merge: {error}"
        return (
            f"Reversed: {record.canonical_name} gave back "
            f"{', '.join(record.absorbed_names) or '(none)'}."
        )

    if remember_page is None:
        # A tool that could never resolve anything is worse than an absent
        # one: the model would spend turns on it and be told to fetch a page
        # it had just fetched.
        return (remember, graph_search, unmerge)
    return (remember, remember_page, graph_search, unmerge)


KNOWLEDGE_PROMPT = (
    "\n\nThis project has a knowledge graph that outlives the session. "
    "`graph_search` finds entities in it by name -- check there before "
    "searching the web for something the project may already have learned. "
    "`remember_page` commits a page you have fetched: give it the page's URL "
    "and a stable `source_id`, and the text and its citation details are taken "
    "from what you already read -- you do not retype the page, and you do not "
    "copy its `url:`, `title:` or `date:` lines across. If the page was read "
    "too long ago to still be held, it will say so and you can `fetch` it "
    "again.\n\n"
    "`remember` is for everything else: text you were given, or a passage you "
    "are recording in your own words. Extraction runs over exactly what you "
    "pass, and the result is recorded permanently.\n\n"
    "Committing is not free and not private -- it changes what every later "
    "session in this project sees. Remember what a future session would want "
    "to have been told, not everything you happened to look at.\n\n"
    "`remember` also consolidates: entities that look like the same thing are "
    "merged, and each merge is printed with its id. You have context the "
    "matcher does not. If two things were joined that are not the same thing, "
    "reverse it with `unmerge` and that id."
)
