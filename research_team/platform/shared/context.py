"""Compatibility facade for context strategy types.

Canonical definitions have moved to `research_team.session.application.context`
to keep `platform` strictly decoupled from session domain aggregates.
"""

from typing import Any

__all__ = [  # noqa: F822
    "DEFAULT_CLEAR_OVER_CHARS",
    "DEFAULT_KEEP_RESULTS",
    "Compaction",
    "ContextStrategy",
    "ElideToolResults",
    "FullHistory",
    "PreparedContext",
]


def __getattr__(name: str) -> Any:
    if name in __all__:
        import importlib

        mod = importlib.import_module("research_team.session.application.context")
        val = getattr(mod, name)
        globals()[name] = val
        return val
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
