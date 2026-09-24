"""Dependency injection containers for web routes.

Route parameter records for sessions, turns, sources, exports, settings, and
catalog. Grouped into records rather than long parameter lists so adding fields
does not break callers or route signatures.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from research_team.curriculum.application import Curriculum
from research_team.curriculum.application.learner_progress import LearnerProgressService
from research_team.infrastructure.persistence import CorpusRunner
from research_team.infrastructure.persistence.corpus_reader import ProjectCorpusReader
from research_team.infrastructure.persistence.read_models import OntologyRunner
from research_team.interfaces.web.activity import TurnActivity
from research_team.interfaces.web.approvals import WebApprovals
from research_team.interfaces.web.authoring import AuthoringActivity
from research_team.interfaces.web.extraction import ExtractionActivity
from research_team.interfaces.web.extraction_queue import ExtractionQueue
from research_team.knowledge.application.graph_read import GraphReadPort
from research_team.platform.shared.blobs import BlobStorePort
from research_team.research.application.corpus_editing import CorpusEditor
from research_team.research.application.document_extraction import (
    DocumentExtractor,
)
from research_team.research.application.perception import (
    MediaPerceiver,
    PerceptionPort,
)
from research_team.session.application.autonomy import AutonomyPolicy
from research_team.session.application.session_service import SessionService
from research_team.session.application.turn_supervisor import TurnSupervisor
from research_team.settings.application import (
    ModelProfileStorePort,
    ProviderProbePort,
    SecretBoxPort,
    SettingsStorePort,
)

__all__ = [
    "ExportDeps",
    "SessionDeps",
    "SettingsDeps",
    "SourceDeps",
]


@dataclass(frozen=True)
class SessionDeps:
    """What the session, turn, approval, and autonomy routes need from
    `create_app`'s closure.

    A record rather than a long parameter list, matching `TopicDeps`,
    `KnowledgeDeps`, and `DialogueDeps`.
    """

    service: SessionService
    turns: TurnSupervisor
    approvals: WebApprovals | None = None
    activity: TurnActivity | None = None
    policy: AutonomyPolicy | None = None
    load: Callable[[UUID], Awaitable[Any]] | None = None
    progress: LearnerProgressService | None = None


@dataclass(frozen=True)
class SourceDeps:
    """What the source and ingestion routes need from `create_app`'s closure.

    A record rather than a long parameter list, matching `ExportDeps`,
    `SettingsDeps`, and `CatalogDeps`. Everything here is already built in
    `create_app`; nothing is constructed in this module.
    """

    require_project: Callable[[UUID], Awaitable[None]] | None = None
    corpus: CorpusRunner | None = None
    blob_store: BlobStorePort | None = None
    editor: CorpusEditor | None = None
    extractor: DocumentExtractor | None = None
    extract_queue: ExtractionQueue | None = None
    ontology: OntologyRunner | None = None
    perception: PerceptionPort | None = None
    perceiver: MediaPerceiver | None = None
    extraction: ExtractionActivity | None = None
    reader_of: Callable[[UUID], ProjectCorpusReader] | None = None


@dataclass(frozen=True)
class ExportDeps:
    """What the export routes need from `create_app`'s closure.

    A record rather than a long parameter list, so adding a fourth thing does
    not re-order anybody's call. Everything here is already built in
    `create_app`; nothing is constructed in this module.
    """

    #: `service.load` and `service.project_state`, narrowed to the two calls
    #: this module makes. Typed as `Any` because `SessionService` lives behind
    #: an application-layer import `app.py` already has and re-declaring its
    #: shape here would be a second protocol for one collaborator.
    service: Any
    require_project: Callable[[UUID], Awaitable[Any]]
    graph_reader: Callable[[UUID], Awaitable[GraphReadPort]]
    curriculum_of: Callable[[UUID], Awaitable[Curriculum]]
    authoring: AuthoringActivity | None

    #: The three further reads `format=html` needs, and only it. All three
    #: default to `None` so every existing construction of this record --
    #: including the fixtures in `tests/interfaces/` -- keeps working and
    #: exports a course whose resolved widgets render named absences. That is
    #: the honest degradation: a build with no corpus genuinely cannot quote a
    #: passage, and a zip export never could either.
    corpus_reader: Callable[[UUID], Any] | None = None
    definitions: Callable[[UUID], Awaitable[Any]] | None = None
    timeline_reader: Callable[[UUID], Awaitable[Any]] | None = None


@dataclass(frozen=True)
class SettingsDeps:
    """What the settings routes need. Everything is built in composition.

    `store` and `secrets` are optional because both are: a deployment with no
    settings database still serves the schema and the provider catalogue (which
    are static), and one with no `AGENT_SETTINGS_KEY` still reads and writes
    every non-secret setting. Answering 503 for the whole surface because one
    half is unwired would hide the half that works.
    """

    store: SettingsStorePort | None = None
    secrets: SecretBoxPort | None = None
    probe: ProviderProbePort | None = None
    profiles: ModelProfileStorePort | None = None

    async def close(self) -> None:
        """Release both stores' connections.

        Here rather than as two steps in `Application.close`, because
        `test_every_close_step_has_a_partial_build_resource` resolves a step
        through the `Application(...)` keyword that filled the attribute, and
        `self.settings.store.close` has one component too many to resolve. One
        method on the thing composition already passes as a unit keeps the two
        lists derivable from each other, which is the whole point of that test.

        `getattr` rather than a `close()` on the ports: both are deliberately
        dumb about scopes, keys and strings (see `SettingsStorePort`), and a
        lifecycle method on the Protocol would oblige every test double to grow
        one for a resource it does not hold. The production adapters are the
        only implementations that own a connection, and they are the only ones
        this needs to find.

        This is not decoration. `aiosqlite` starts a **non-daemon** worker
        thread per connection, so one unclosed store keeps `threading._shutdown`
        waiting and the interpreter never exits -- B5 and B100's symptom, and
        measured on this branch: CI's `pytest` job finished the suite in 6m26s
        and then sat for a further 78 minutes before being cancelled, with the
        runner reporting orphan `uv` and `pytest` processes.
        """
        for store in (self.store, self.profiles):
            closer = getattr(store, "close", None)
            if closer is not None:
                await closer()
