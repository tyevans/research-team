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
    REMEMBER_TOOL,
    UNMERGE_TOOL,
    IngestReport,
    KnowledgeError,
    KnowledgePort,
    Match,
    SourceRef,
)


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
    knowledge: KnowledgePort, *, limit: int = 10
) -> tuple[BaseTool, ...]:
    """`remember`, `graph_search` and `unmerge` over one project's graph."""

    @tool(REMEMBER_TOOL)
    async def remember(text: str, source_id: str, note: str = "") -> str:
        """Commit text to the graph, extracting entities and relationships from it."""
        try:
            report = await knowledge.ingest(
                SourceRef(source_id=source_id, text=text, note=note or None)
            )
        except KnowledgeError as error:
            return f"Could not record this: {error}"
        return format_ingest(report)

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

    return (remember, graph_search, unmerge)


KNOWLEDGE_PROMPT = (
    "\n\nThis project has a knowledge graph that outlives the session. "
    "`graph_search` finds entities in it by name -- check there before "
    "searching the web for something the project may already have learned. "
    "`remember` commits text to it: extraction runs over what you pass, and "
    "the result is recorded permanently, so pass substantial content you have "
    "actually read rather than your own summary of it, and give each document "
    "a stable `source_id`.\n\n"
    "Committing is not free and not private -- it changes what every later "
    "session in this project sees. Remember what a future session would want "
    "to have been told, not everything you happened to look at.\n\n"
    "`remember` also consolidates: entities that look like the same thing are "
    "merged, and each merge is printed with its id. You have context the "
    "matcher does not. If two things were joined that are not the same thing, "
    "reverse it with `unmerge` and that id."
)
