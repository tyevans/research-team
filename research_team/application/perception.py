"""Making a stored medium legible.

The port takes a digest and no mimetype. Detection is the perceiving library's
job and it does it from content -- measured on 2026-08-15 and re-taken against
`readeverything` 0.2.0 on 2026-08-16, an extensionless file named for its own
sha256 was identified as `video/mp4` -- so handing it this repository's stored
`media_type` would be giving a sniffed guess to something with a better
sniffer.

Nothing in this module names a library. `LocatorSpan.locator` is a plain dict
for exactly that reason: the adapter under `infrastructure/perception/` is the
only place that should know which library perceives, and the five `kind`
spellings below are this repository's own vocabulary rather than a re-export of
someone's union type.
"""

from dataclasses import dataclass
from typing import Protocol

LOCATOR_KINDS = ("time", "page", "bbox", "char", "byte")
"""Every `kind` a `LocatorSpan.locator` may carry.

Written down here rather than left implicit in the adapter because three later
readers dispatch on it -- a resolver, a citation renderer and the timeline --
and a fourth spelling invented at one of them would silently match nothing.
The tag is always explicit: inferring the kind from which keys are present
makes an unrecognised locator look like whichever known one it shares a key
with, where an explicit tag makes it visibly unknown.

The shapes, per kind:

- `{"kind": "time", "start_s": float, "end_s": float}`
- `{"kind": "page", "page": int}`
- `{"kind": "bbox", "page": int | None, "x": float, "y": float, "w": float, "h": float}`
- `{"kind": "char", "start": int, "end": int}`
- `{"kind": "byte", "start": int, "end": int}`
"""


@dataclass(frozen=True)
class LocatorSpan:
    """A stretch of the rendered text, and where in the medium it came from."""

    char_start: int
    char_end: int
    locator: dict[str, object]
    """The locator as JSON-ready data, tagged with one of `LOCATOR_KINDS`. A
    dict rather than a library's union type so nothing above this line imports
    the perceiving library: the adapter is the only place that should know
    which one it is."""


@dataclass(frozen=True)
class Perceived:
    """What one reading of one medium produced."""

    text: str
    locators: tuple[LocatorSpan, ...]
    fingerprint: str
    """What invalidates a derived transcript. A function of the *configured*
    model revisions, so swapping the vision model changes it and a stored
    reading taken with the old one stops being reused."""
    degradations: tuple[str, ...]
    """What could not be done, in words, rather than what failed. A missing
    capability degrades rather than raising -- measured 2026-08-16: with no
    vision model a video still renders, carrying `vision unavailable: frames
    were not described`."""


@dataclass(frozen=True)
class PerceptionCapabilities:
    """What this install can actually do.

    A structure rather than a boolean because the 503 has to name what is
    absent: "no vision model configured" and "ffmpeg not found" send an
    operator to two different places, and a route that can only say "not
    configured" sends them to neither.
    """

    vision: bool
    asr: bool
    ffmpeg: bool

    def any_model(self) -> bool:
        """Whether anything here can perceive rather than merely describe.

        With neither model, `represent` still returns a metadata stub -- "Image
        x.png, 64x48 PNG, 469 bytes" -- and storing that would put a sentence
        no human wrote into the corpus to be extracted as evidence. So this is
        the question the route asks before doing any work.
        """
        return self.vision or self.asr

    def missing(self) -> tuple[str, ...]:
        absent = []
        if not self.vision:
            absent.append("no vision model (AGENT_VISION_MODEL)")
        if not self.asr:
            absent.append("no transcriber (AGENT_TRANSCRIBER_URL)")
        if not self.ffmpeg:
            absent.append("ffmpeg not found on PATH")
        return tuple(absent)


class PerceptionPort(Protocol):
    async def perceive(self, *, sha256: str, max_chars: int) -> Perceived:
        """Read the blob stored under `sha256` into text and locators.

        Raises rather than returning a stub when the medium cannot be read at
        all; a capability that is merely absent arrives as a `degradation`.
        """
        ...

    def capabilities(self) -> PerceptionCapabilities:
        """What this install can do, without awaiting anything.

        Synchronous on purpose, and the reason is a caller: the web route
        consults this *before* enqueuing perception work, and the library's own
        builder is `async def`. See `ReadEverythingPerception` for the ruling
        this follows from -- capabilities are declared from configuration
        rather than probed, so this needs no event loop.
        """
        ...
