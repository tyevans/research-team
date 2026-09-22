"""The Ontology discovery and reading HTTP surface.

Extracted from `knowledge.py`: ontology discovery passes and discovered class
readings are a distinct surface from the graph and timeline browsing endpoints.
"""

import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from uuid import UUID

from fastapi import APIRouter, FastAPI, HTTPException
from pydantic import BaseModel

from research_team.infrastructure.persistence import CorpusRunner
from research_team.infrastructure.persistence.corpus_reader import ProjectCorpusReader
from research_team.infrastructure.persistence.read_models import OntologyRunner
from research_team.knowledge.application.ontology_discovery import OntologyDiscoveryService
from research_team.platform.shared.blobs import BlobStorePort

OntologyDiscoverers = Callable[[UUID], OntologyDiscoveryService]
"""One project's `OntologyDiscoveryService`, built on demand.

A callable for `TopicReaders`' reason -- the project is bound at construction,
so no caller can run a pass against a project it was not handed.

Synchronous and never `None`, unlike `DefinitionReaders` below, and the
difference is what each needs. A definition is assembled from a project's graph
store and chunk store, so building one is asynchronous and can fail when
chunking is off. Discovery needs the document text and a model; neither can be
absent, so there is no `None` for a route to render as 503.
"""


class OntologyTriggerBody(BaseModel):
    strict: bool = True


@dataclass(frozen=True)
class OntologyDeps:
    """What ontology routes need from the application closure."""

    require_project: Callable[[UUID], Awaitable[None]] | None = None
    ontology: OntologyRunner | None = None
    ontology_discoverers: OntologyDiscoverers | None = None
    corpus: CorpusRunner | None = None
    blob_store: BlobStorePort | None = None
    reader_of: Callable[[UUID], ProjectCorpusReader] | None = None


def ontology_router(deps: OntologyDeps) -> APIRouter:
    """The ontology discovery and reading router, ready for `app.include_router`."""
    router = APIRouter()

    async def _check_project(project_id: UUID) -> None:
        if deps.require_project is not None:
            await deps.require_project(project_id)

    def _reader(project_id: UUID) -> ProjectCorpusReader:
        """This project's `ProjectCorpusReader`, over the corpus and blob store.

        503 rather than 404 when `corpus`/`blob_store` was not wired, for the
        reason `catalog_of` gives: a build with no corpus read model is a
        valid thing to serve, and the caller needs to know the server cannot
        answer rather than that the project has no sources.
        """
        if deps.reader_of is not None:
            return deps.reader_of(project_id)
        if deps.corpus is None or deps.blob_store is None:
            raise HTTPException(status_code=503, detail="no corpus read model is configured")
        return ProjectCorpusReader(deps.corpus, project_id, deps.blob_store)

    @router.post("/api/projects/{project_id}/sources/{source_id}/ontology")
    async def discover_ontology(
        project_id: UUID,
        source_id: str,
        strict: bool = True,
        body: OntologyTriggerBody | None = None,
    ):
        """Read one document for the classes it states. 200, because it has run.

        **Synchronous, unlike extraction, and for `read_graph_definition`'s
        reason.** `ExtractionQueue` exists because extraction is long-running
        and a request that loses a queued extraction loses an intention the
        caller cannot easily re-express. A discovery pass is one model call over
        one document, produces the same answer from the same inputs, and a
        failed request costs the caller a second click -- so the whole retry
        story is "click again".

        It also *could not* reuse that queue as it stands. `ExtractionQueue`
        deduplicates on `(project_id, source_id)` and reads
        `report.entity_count` off whatever it awaited, so queuing a pass for a
        document already queued for extraction would be silently dropped and
        answered `queued: false` -- which the client reads as "this is going to
        happen", when what is going to happen is the extraction, not the pass.
        Making it fit means changing a component another lane owns.

        **`strict=false` reads the document under the weaker rule** that
        `verify_classes` documents: a class whose quoted sentence is not in the
        text survives if all its members are, cited to the first member's
        occurrence and flagged `evidenceQuoted: false` on the way back out.
        Default true, because a reader who has not asked for it must not be
        handed classes the document may never have grouped.

        A query parameter and not a body field, on a POST, which is the odd
        choice here. The body is `{}` and stays that way: this route already
        carries its subject in the path, and a caller reading the URL sees the
        whole request -- which matters more than usual for a lever whose two
        settings answer different questions about the same document.

        **`found: null` rather than 404 when the pass declines.** The three
        declines -- an unreadable reply, a document over
        `MAX_DISCOVERY_CHARS`, and a source that is not there -- are told apart
        above by the 404 and below by nothing, deliberately: see
        `OntologyDiscoveryService.discover`. `found: 0` is a different answer
        again, and the important one to keep distinct: it means the document was
        read and states no classes.
        """
        await _check_project(project_id)
        if deps.ontology_discoverers is None:
            raise HTTPException(status_code=503, detail="no ontology service is configured")
        if await _reader(project_id).read_document(source_id) is None:
            raise HTTPException(
                status_code=404, detail=f"no source {source_id!r} in project {project_id}"
            )
        actual_strict = (
            body.strict if body is not None and "strict" in body.model_fields_set else strict
        )
        found = await deps.ontology_discoverers(project_id).discover(
            source_id, strict=actual_strict
        )
        return {"sourceId": source_id, "found": found}

    @router.get("/api/projects/{project_id}/ontology")
    async def read_ontology(project_id: UUID):
        """Every class discovered in this project, with what it was derived from.

        **503 when the runner is unwired, not an empty 200.** An empty list is
        the correct answer for a project nobody has run a pass on, so a
        misconfigured build answering the same thing would be indistinguishable
        from a working one with nothing to show -- which is the whole failure
        this feature is arranged against, arriving at the last layer.

        Every field a reader needs to judge a class travels with it. `evidence`
        is offsets into the source document, not a quotation: the view opens the
        document there, and quoted text proves only that the model wrote a
        sentence, where opening the document proves the sentence is in it.
        `declaredCount` beside `memberCount` is the checksum, and
        `rejectedMembers` is what explains a gap between them -- a class short
        one member with no explanation cannot be judged, because an invented
        member and a document genuinely missing one look identical.
        """
        await _check_project(project_id)
        if deps.ontology is None:
            raise HTTPException(status_code=503, detail="no ontology service is configured")
        classes = []
        for row in await deps.ontology.classes_for(project_id):
            members = await deps.ontology.members_for(row.id)
            classes.append(
                {
                    "id": str(row.id),
                    "name": row.name,
                    "kind": row.kind,
                    "declaredCount": row.declared_count,
                    "memberCount": row.member_count,
                    "parentClassId": str(row.parent_class_id) if row.parent_class_id else None,
                    "evidence": {
                        "sourceId": row.source_id,
                        "start": row.evidence_start,
                        "end": row.evidence_end,
                    },
                    "rejectedMembers": json.loads(row.rejected_members),
                    # Travels beside `evidence` rather than being inferred from
                    # it, because nothing about the offsets says which they are
                    # -- a member fallback and a located sentence are both a
                    # pair of integers into the same document.
                    "evidenceQuoted": row.evidence_quoted,
                    "stale": row.stale,
                    "members": [
                        {"name": member.member_name, "ordinal": member.ordinal}
                        for member in members
                    ],
                }
            )
        return {"classes": classes}

    return router


def mount_ontology_routes(app: FastAPI, deps: OntologyDeps) -> None:
    """Mount the ontology router on the given FastAPI app."""
    app.include_router(ontology_router(deps))


__all__ = [
    "OntologyDeps",
    "OntologyDiscoverers",
    "OntologyTriggerBody",
    "mount_ontology_routes",
    "ontology_router",
]
