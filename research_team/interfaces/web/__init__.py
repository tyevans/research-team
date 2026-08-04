"""The HTTP + SSE adapter."""

from research_team.interfaces.web.app import create_app
from research_team.interfaces.web.approvals import WebApprovals

__all__ = ["WebApprovals", "create_app"]
