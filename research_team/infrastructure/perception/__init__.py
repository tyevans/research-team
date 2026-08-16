"""The perception adapter, and the only package that imports `readeverything`.

A package rather than a module because Task 5's use case and any second
perceiver want somewhere to live that is not the `readeverything` file itself.
"""

from research_team.infrastructure.perception.readeverything_adapter import (
    FFMPEG_REVISION,
    ReadEverythingPerception,
    build_perception_adapter,
    ffmpeg_present,
)

__all__ = [
    "FFMPEG_REVISION",
    "ReadEverythingPerception",
    "build_perception_adapter",
    "ffmpeg_present",
]
