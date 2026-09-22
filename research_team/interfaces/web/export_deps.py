"""Dependencies container for web export routes."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from research_team.curriculum.application import Curriculum
from research_team.interfaces.web.authoring import AuthoringActivity
from research_team.knowledge.application.graph_read import GraphReadPort


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


__all__ = ["ExportDeps"]
