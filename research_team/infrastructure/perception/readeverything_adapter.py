"""`PerceptionPort` over `readeverything`, reading the blob tree in place.

This module is the only place in the repository that imports `readeverything`.
Everything above it speaks in `Perceived`/`LocatorSpan`, whose `locator` is a
plain dict, so swapping the library is a change to one file rather than to the
application layer.

**Capabilities are declared from configuration, not probed.** The library's
`build_perception` is `async def` and probes at construction; the web route
needs a synchronous answer to "can this install perceive at all?" before it
enqueues anything. So `capabilities()` derives from `AGENT_VISION_MODEL`,
`AGENT_TRANSCRIBER_URL` and `shutil.which("ffmpeg")`, the `CapabilitySet` is
built explicitly from those same configured ids -- which makes `fingerprint()`
computable without awaiting -- and the `Perception` itself is built lazily on
the first `perceive`, memoised behind an `asyncio.Lock`.

The alternative considered and rejected was making `build_application` async,
which would have changed every caller in the repository -- REPL, web and every
test -- for the sake of one port. **The cost of the choice made instead:** a
binary that is present but broken reads as available, so its failure arrives
later as a degradation on a `represent` rather than up front as a 503. That is
a worse error message, not a wrong answer, and it is the whole price.
"""

import asyncio
import shutil
from pathlib import Path

from readeverything import (
    BBox,
    Budget,
    ByteRange,
    Capability,
    CapabilitySet,
    CharSpan,
    FilesystemArtifactStore,
    LocatorSegment,
    PageRef,
    Perception,
    RemoteWhisperTranscriber,
    TimeSpan,
    VisionModel,
    build_openai_vision_model,
    build_perception,
)
from readeverything import (
    Transcriber as _Transcriber,
)

from research_team.application.perception import (
    LocatorSpan,
    Perceived,
    PerceptionCapabilities,
)
from research_team.infrastructure import config

FFMPEG_REVISION = "present"
"""The FFMPEG revision string in the declared `CapabilitySet`.

A constant rather than a version number because `shutil.which` is the only
question asked -- see the module docstring on declaring rather than probing.
The consequence to know is that upgrading ffmpeg does *not* move the
fingerprint, so a reading taken with ffmpeg 6 is reused after an upgrade to 7.

**This deliberately overrides a choice the library made the other way.**
`readeverything`'s own `BinaryProbe`, left to discover rather than handed a
declaration, records the full banner -- `ffmpeg version 6.1.1-3ubuntu5
Copyright (c) 2000-2023 the FFmpeg developers` (measured 2026-08-16) -- and
`_capabilities_handlers_can_use` documents the principle: a capability a
handler consults belongs in the fingerprint, so the cache stays honest about
what it depends on. `VideoHandler` does consult FFMPEG, so the library's
position is that a video reading depends on which ffmpeg produced its frames,
and it is not wrong: seek behaviour, scaler defaults and decoder fixes change
the pixels handed to the VLM.

Overridden anyway, because stability of stored readings is worth more here
than cache precision. Ubuntu bumps ffmpeg under a long-lived install without
anyone deciding to, and re-perceiving an entire corpus of video on a point
release is a large, real cost against a small, mostly-theoretical difference.

**The choice is sticky, which is the part to weigh before changing it.** Once
readings are stored keyed on `"present"`, moving to a version string
invalidates every one of them at once -- the migration gets more expensive
every day the corpus grows, so this is not a decision that stays cheap to
revisit. And the information is currently lost rather than merely kept out of
the key: **nothing anywhere records which ffmpeg produced a reading**, so a
disputed frame description cannot be traced to a decoder. The remedy that was
preferred and not taken is provenance rather than fingerprint -- one `ffmpeg
-version` at construction, stored on the reading -- which needs a new event
field, and that is a domain change two tasks behind this one. Filed as a
backlog candidate instead.
"""


def ffmpeg_present() -> bool:
    """Whether *both* ffmpeg and ffprobe are on PATH. Measured per call, not cached.

    Both, not just `ffmpeg`: the spec names the pair ("`ffmpeg` and `ffprobe`
    are OS binaries") and `readeverything`'s video handling calls `ffprobe` to
    read a container's duration and streams before `ffmpeg` extracts anything
    from it. Checking only the first declared `Capability.FFMPEG` present on an
    install that has one and not the other, and the shortfall then arrived as a
    degradation from a `represent` already paid for rather than as the 503 the
    route is there to give. A split install is not hypothetical: several
    distributions package the two separately, and a `ffmpeg` built without the
    `ffprobe` binary is a supported upstream configuration.

    Still declared rather than probed, so ruling R2's accepted cost stands
    unchanged -- a binary that is present but broken reads as available. This
    widens *which* binaries must be present, not how hard we look at them.

    Not cached because the answer is cheap and a long-lived process that had
    ffmpeg installed underneath it should notice.
    """
    return shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None


def _locator_to_dict(locator: object) -> dict[str, object]:
    """One of `readeverything`'s locators as tagged, JSON-ready data.

    The `kind` is written explicitly rather than inferred from which keys are
    present. Inference would make an unrecognised locator look like whichever
    known one it shares a key with -- `ByteRange` and `CharSpan` are both
    `start`/`end` and mean entirely different things -- and this vocabulary is
    what three later readers dispatch on. See `LOCATOR_KINDS` in
    `application/perception.py`, which is the canonical list.

    Raises on an unknown locator type rather than emitting an untagged dict: a
    new locator kind added upstream should stop here, where the mapping lives,
    instead of reaching a resolver that would drop it. That is defensible only
    because of the pin -- `pyproject.toml` caps `readeverything` below 0.3, so
    a new member of the `Locator` union cannot arrive without a deliberate
    bump, and the raise therefore fires under the developer running the upgrade
    rather than under a user uploading a file.

    **The cost, which is not small.** This is a runtime stop inside the
    perception of a real medium, not a build-time one: the blast radius is a
    whole reading lost -- upload to 500 -- rather than one span. And it is
    data-dependent, so an upgrade whose test corpus happens to contain no
    medium yielding the new locator passes CI and fires later on the first PDF
    of an unusual shape.

    The alternative considered: emit `{"kind": "unknown", "type":
    type(locator).__name__}`, add `"unknown"` to `LOCATOR_KINDS`, and let the
    three readers skip it -- which keeps the text of the reading and arguably
    satisfies "an unknown kind is visibly unknown" better than raising does.
    Rejected while the pin holds, because a silently skipped span is a citation
    that quietly cannot be resolved, and under a pin the loud version is paid
    by someone who can fix it. Revisit this the moment the cap moves.
    """
    match locator:
        case TimeSpan(start_s=start_s, end_s=end_s):
            return {"kind": "time", "start_s": start_s, "end_s": end_s}
        case PageRef(page=page):
            return {"kind": "page", "page": page}
        case BBox(page=page, x=x, y=y, w=w, h=h):
            return {"kind": "bbox", "page": page, "x": x, "y": y, "w": w, "h": h}
        case CharSpan(start=start, end=end):
            return {"kind": "char", "start": start, "end": end}
        case ByteRange(start=start, end=end):
            return {"kind": "byte", "start": start, "end": end}
    raise NotImplementedError(
        f"no locator kind for {type(locator).__name__}; add it here and to "
        "LOCATOR_KINDS in application/perception.py, which the resolver reads"
    )


def _to_span(segment: LocatorSegment) -> LocatorSpan:
    return LocatorSpan(
        char_start=segment.span.start,
        char_end=segment.span.end,
        locator=_locator_to_dict(segment.locator),
    )


class ReadEverythingPerception:
    """`readeverything` over the blob store's own directory tree.

    The root is `blob_root()` itself and the uri for a medium is
    `f"{sha256[:2]}/{sha256}"` -- the fan-out path the store already writes.
    Nothing is copied. The alternative considered and rejected was
    materialising each blob to a temp file with a plausible extension, which
    would have cost a full second copy of a file up to the 2GB upload ceiling
    on every perception, to give a sniffer a filename it does not consult:
    measured 2026-08-15, an extensionless file named for its own sha256 was
    identified as `video/mp4` from content alone.

    The consequence to know: this `Perception` can read any project's blobs,
    because the blob store is not partitioned by project. That is safe only
    because the digest handed to `perceive` came from the calling project's own
    read model -- there is no path from a uri back to a project, so nothing
    here can be asked to enumerate.
    """

    def __init__(
        self,
        *,
        blob_root: Path,
        artifact_root: Path,
        vision: VisionModel | None = None,
        transcriber: _Transcriber | None = None,
        vision_model: str | None = None,
        transcriber_model: str | None = None,
        ffmpeg: bool | None = None,
    ) -> None:
        """Nothing here awaits, and nothing here touches the network.

        `vision_model` and `transcriber_model` are the *declared* revisions and
        the injected models are the things that do the work; they are separate
        parameters because a test needs to be able to set them apart, and
        `build_perception` raises `DomainError` if the declared VISION revision
        disagrees with `vision.model_id`. `build_perception_adapter` derives
        both from one setting, which is what keeps that raise unreachable in
        production.
        """
        self._blob_root = Path(blob_root)
        self._artifact_root = Path(artifact_root)
        self._vision = vision
        self._transcriber = transcriber
        self._vision_model = vision_model
        self._transcriber_model = transcriber_model
        # `None` rather than `ffmpeg_present()` as a default argument: a
        # default is evaluated once at import, which would pin the answer for
        # the life of the process and make the test that asserts against
        # `shutil.which` a test of import order.
        self._ffmpeg = ffmpeg_present() if ffmpeg is None else ffmpeg
        self._capability_set = self._declare()
        self._perception: Perception | None = None
        # One lock per adapter, not a module global: two adapters in one test
        # process are two independent builds, and sharing a lock would serialise
        # them for no reason.
        self._build_lock = asyncio.Lock()

    def _declare(self) -> CapabilitySet:
        """The `CapabilitySet` handed to `build_perception`, from configuration.

        Absent capabilities are *omitted* rather than declared with an empty
        revision: `CapabilitySet.satisfies` asks whether a key is present, so a
        declared-but-blank vision would route an image to a handler with no
        model behind it.
        """
        revisions: dict[Capability, str] = {}
        if self._vision_model:
            revisions[Capability.VISION] = self._vision_model
        if self._transcriber_model:
            revisions[Capability.ASR] = self._transcriber_model
        if self._ffmpeg:
            revisions[Capability.FFMPEG] = FFMPEG_REVISION
        return CapabilitySet.of(revisions)

    @property
    def fingerprint(self) -> str:
        """What invalidates a stored reading. Synchronous, because the set is declared.

        A property rather than a method so a caller cannot mistake it for
        something that recomputes against the world; it is a pure function of
        configuration and nothing else.
        """
        return self._capability_set.fingerprint()

    def capabilities(self) -> PerceptionCapabilities:
        return PerceptionCapabilities(
            vision=Capability.VISION in self._capability_set.revisions,
            asr=Capability.ASR in self._capability_set.revisions,
            ffmpeg=Capability.FFMPEG in self._capability_set.revisions,
        )

    async def _open(self) -> Perception:
        """Build once, on first use, under a lock.

        The lock rather than a bare `if`: two `perceive` calls awaited
        concurrently would both see `None` and both build, and the second build
        would discard the first's `ResolutionMemo` -- the memo is why two
        readings of one blob cost one detection and one hash.
        """
        if self._perception is not None:
            return self._perception
        async with self._build_lock:
            if self._perception is None:
                self._perception = await build_perception(
                    self._blob_root,
                    vision=self._vision,
                    transcriber=self._transcriber,
                    capabilities=self._capability_set,
                    artifacts=FilesystemArtifactStore(root=self._artifact_root),
                )
        return self._perception

    async def perceive(self, *, sha256: str, max_chars: int) -> Perceived:
        perception = await self._open()
        rendered = await perception.represent(
            f"{sha256[:2]}/{sha256}", Budget(max_chars=max_chars)
        )
        return Perceived(
            text=rendered.text,
            locators=tuple(_to_span(segment) for segment in rendered.locator_map.segments),
            fingerprint=self.fingerprint,
            # `what` and not `f"{what}: {detail}"`: `what` is the sentence a
            # human reads ("vision unavailable: frames were not described",
            # measured 2026-08-16) and `detail` is the library's diagnostic,
            # which changes shape between versions and would make an otherwise
            # identical degradation compare unequal across an upgrade.
            degradations=tuple(degradation.what for degradation in rendered.degradations),
        )


def build_perception_adapter() -> ReadEverythingPerception:
    """The adapter this install is configured for. Synchronous, deliberately.

    Called from `build_application`, which is not async and is not becoming
    async for one port -- see the module docstring. Constructs a transcriber
    only when a URL is set and a vision model only when a model name is set,
    because both are optional and an unset one is a reportable degradation
    rather than an error.

    **The declared revisions come off the constructed models, never off the
    configuration string.** This shipped wrong once and broke every install
    that had vision configured: `build_openai_vision_model` prefixes its
    argument unconditionally, so `AGENT_VISION_MODEL=qwen2.5-vl` yields
    `model_id == "openai/qwen2.5-vl"` (measured 2026-08-16 against 0.2.0),
    `build_perception` compared the declared `qwen2.5-vl` against it and raised
    `DomainError` on the first perceive of every vision-configured install.
    Reading the id back off the object is the only wiring where the two cannot
    diverge -- any transformation the library applies is applied before the
    declaration is taken. `test_the_factory_declares_the_built_vision_models_own_id`
    is what fails if this reverts to the config string.

    The same is done for ASR, and there it is prevention rather than repair:
    the library's agreement check covers VISION only (measured), so a mismatched
    ASR revision would raise nothing and simply key the artifact cache on a
    string no model reported. `RemoteWhisperTranscriber` happens not to rewrite
    `model_id` today -- in equals out -- so taking it off the object costs
    nothing and stops depending on that staying true.
    """
    vision_model = config.vision_model()
    vision = (
        build_openai_vision_model(
            base_url=config.base_url(),
            model=vision_model,
            api_key=config.api_key(),
        )
        if vision_model
        else None
    )

    transcriber_url = config.transcriber_url()
    # `transcriber_model()` raises when unset, so it is only asked once a URL
    # exists -- an install with no ASR must not fail to start over a variable
    # it has no use for.
    transcriber_model = config.transcriber_model() if transcriber_url else None
    transcriber = (
        RemoteWhisperTranscriber(base_url=transcriber_url, model_id=transcriber_model)
        if transcriber_url and transcriber_model
        else None
    )

    return ReadEverythingPerception(
        blob_root=config.blob_root(),
        artifact_root=config.perception_root(),
        vision=vision,
        transcriber=transcriber,
        vision_model=vision.model_id if vision else None,
        transcriber_model=transcriber.model_id if transcriber else None,
    )
