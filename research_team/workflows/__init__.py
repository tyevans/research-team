"""The shipped presets.

Data, not a layer: these modules import from `domain.workflow` and nothing
else, and define no behaviour. They live outside `domain/` because a preset is
content that will be edited often by people who are not changing the engine,
and burying it among the aggregates would invite the two to drift into each
other.

Adding a preset is adding a module here and a line to `PRESETS`. Every one of
them is validated at import time, so a malformed preset fails the test suite on
collection rather than an hour into somebody's run.
"""

from research_team.domain.workflow import Preset
from research_team.workflows.addie import addie_pure
from research_team.workflows.hybrid import hybrid_default
from research_team.workflows.ubd import ubd_pure

PRESETS: dict[str, Preset] = {
    preset.id: preset for preset in (hybrid_default, ubd_pure, addie_pure)
}

DEFAULT_PRESET_ID = hybrid_default.id
"""The hybrid, because whichever pure methodology a user picks they inherit
that tradition's known structural defect -- and choosing which defect to
tolerate requires exactly the expertise they are using the tool to avoid
needing."""

__all__ = ["DEFAULT_PRESET_ID", "PRESETS", "addie_pure", "hybrid_default", "ubd_pure"]
