"""The `readeverything` adapter, over a real temporary blob tree.

**Nothing here touches the network.** The vision and ASR seams are filled with
`readeverything`'s own fakes, and the one test that exercises
`RemoteWhisperTranscriber` hands it an `httpx.MockTransport`. A test that
reached a real transcriber would pass only on the machine that has one, and
would pin this suite to somebody's LAN address.
"""

import asyncio
import hashlib
import shutil
from pathlib import Path

import httpx
import pytest
from readeverything import (
    BBox,
    ByteRange,
    Capability,
    CapabilitySet,
    CharSpan,
    DomainError,
    FakeTranscriber,
    FakeVision,
    PageRef,
    RemoteWhisperTranscriber,
    TimeSpan,
)

from research_team.application.perception import LOCATOR_KINDS
from research_team.infrastructure.perception import (
    ReadEverythingPerception,
    build_perception_adapter,
    readeverything_adapter,
)
from research_team.infrastructure.perception.readeverything_adapter import _locator_to_dict

PNG_BYTES = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
    "890000000a49444154789c6300010000050001"
    "0d0a2db40000000049454e44ae426082"
)
"""A one-pixel PNG. Real bytes rather than a stub because detection is by
content -- `puremagic` reads the signature, and a placeholder would be
identified as `application/octet-stream` and routed to the binary handler,
which is not the path under test."""


def _write_blob(root: Path, payload: bytes) -> str:
    """Store `payload` the way `FilesystemBlobStore` would, returning its digest.

    Deliberately not routed through `FilesystemBlobStore.put`: the layout --
    two hex characters of fan-out, the file named for its own digest and given
    no extension -- is the thing the adapter depends on, and a fixture that
    asked the store to produce it could not notice the adapter reading a
    different shape. See CLAUDE.md on fixtures that seed through the call under
    test.
    """
    digest = hashlib.sha256(payload).hexdigest()
    path = root / digest[:2] / digest
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return digest


def _adapter(
    blob_root: Path,
    *,
    vision_model: str | None = None,
    transcriber_model: str | None = None,
    ffmpeg: bool = True,
    vision: object = None,
    transcriber: object = None,
) -> ReadEverythingPerception:
    """An adapter whose declared capabilities and injected models agree.

    The agreement is not incidental: `build_perception` raises `DomainError`
    when an explicitly supplied `CapabilitySet` declares a VISION revision that
    differs from `vision.model_id`.

    **This helper does not stand in for the factory, and an earlier version of
    this docstring claimed it did.** That claim is how the factory shipped
    declaring the raw config string while injecting an `openai/`-prefixed
    model. Callers here pass both sides explicitly; what the factory does with
    one configured value is only tested by tests that call
    `build_perception_adapter`.

    `artifact_root` is named after the blob root rather than being a fixed
    `perception` beside it. `tmp_path.parent` is the per-run pytest directory
    shared by every test in the run, so a fixed name there would give every
    test one artifact cache -- inert today, since an image reading writes no
    artifacts at all (measured 2026-08-16), and a cross-test cache hit the
    moment a video fixture appears. Not placed *inside* the blob root either:
    `test_it_reads_a_blob_by_digest_with_no_copy` asserts that tree is
    byte-for-byte unchanged, and an artifact landing there would fail it for
    the wrong reason.
    """
    return ReadEverythingPerception(
        blob_root=blob_root,
        vision=vision,
        transcriber=transcriber,
        vision_model=vision_model,
        transcriber_model=transcriber_model,
        ffmpeg=ffmpeg,
        artifact_root=blob_root.parent / f"{blob_root.name}-perception",
    )


async def test_it_reads_a_blob_by_digest_with_no_copy(tmp_path):
    """The blob store's own tree is the perception root.

    Measured 2026-08-15 and re-taken against 0.2.0 on 2026-08-16: content
    sniffing identifies an extensionless digest-named file, so the uri is
    `ab/abc...` and nothing is materialised anywhere. The assertion that the
    tree is unchanged is what would fail if a future implementation copied the
    blob to a temp file with a plausible extension.
    """
    digest = _write_blob(tmp_path, PNG_BYTES)
    before = sorted(p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*"))

    adapter = _adapter(tmp_path, vision_model=FakeVision().model_id, vision=FakeVision())
    perceived = await adapter.perceive(sha256=digest, max_chars=1000)

    assert perceived.text
    assert perceived.locators
    assert perceived.locators[0].char_start == 0
    after = sorted(p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*"))
    assert after == before


async def test_every_locator_carries_one_of_the_five_kinds(tmp_path):
    """The tag is the vocabulary three later readers dispatch on.

    Would pass with the tagging reverted only if `locator` were left as the
    library's dataclass, which is not JSON-ready -- so this also pins the dict.
    """
    digest = _write_blob(tmp_path, PNG_BYTES)
    adapter = _adapter(tmp_path, vision_model=FakeVision().model_id, vision=FakeVision())

    perceived = await adapter.perceive(sha256=digest, max_chars=1000)

    assert perceived.locators
    for span in perceived.locators:
        assert isinstance(span.locator, dict)
        assert span.locator["kind"] in LOCATOR_KINDS


def test_each_locator_type_maps_to_its_agreed_kind():
    """The whole vocabulary in one place, because one medium cannot exercise it.

    An image yields only `bbox` end-to-end (measured 2026-08-16 against 0.2.0:
    a 1x1 PNG renders one segment at the unit square), so the test above would
    stay green with `time`, `char` and `byte` mistagged -- proved by mutation,
    2026-08-16. This is the test that catches that, and it is also where
    `ByteRange` and `CharSpan` are pinned apart: they carry the same two keys
    and mean entirely different things, which is why the kind is written rather
    than inferred.
    """
    assert _locator_to_dict(TimeSpan(0.0, 2.0)) == {
        "kind": "time",
        "start_s": 0.0,
        "end_s": 2.0,
    }
    assert _locator_to_dict(PageRef(3)) == {"kind": "page", "page": 3}
    assert _locator_to_dict(BBox(page=1, x=0.0, y=0.25, w=0.5, h=0.5)) == {
        "kind": "bbox",
        "page": 1,
        "x": 0.0,
        "y": 0.25,
        "w": 0.5,
        "h": 0.5,
    }
    assert _locator_to_dict(CharSpan(0, 9)) == {"kind": "char", "start": 0, "end": 9}
    assert _locator_to_dict(ByteRange(0, 9)) == {"kind": "byte", "start": 0, "end": 9}


def test_an_unmapped_locator_stops_here_rather_than_reaching_a_resolver():
    """A sixth locator kind upstream must break the mapping, not the reader."""
    with pytest.raises(NotImplementedError):
        _locator_to_dict(object())


async def test_a_missing_capability_becomes_a_named_degradation(tmp_path):
    """No models at all still reads, and says what it could not do.

    Measured 2026-08-16 against 0.2.0: a missing capability degrades rather
    than raising, and the degradation names vision in words.
    """
    digest = _write_blob(tmp_path, PNG_BYTES)
    adapter = _adapter(tmp_path)

    perceived = await adapter.perceive(sha256=digest, max_chars=1000)

    assert perceived.degradations
    assert any("vision" in d for d in perceived.degradations)


async def test_capabilities_report_what_is_missing(tmp_path):
    adapter = _adapter(tmp_path, ffmpeg=False)

    assert adapter.capabilities().any_model() is False
    missing = adapter.capabilities().missing()
    assert any("AGENT_VISION_MODEL" in m for m in missing)
    assert any("AGENT_TRANSCRIBER_URL" in m for m in missing)
    assert any("ffmpeg" in m for m in missing)


def test_capabilities_are_declared_without_an_event_loop(tmp_path):
    """A plain `def` test, and that is the assertion.

    The route consults capabilities before enqueuing anything, and the
    library's `build_perception` is `async def`. If this ever needed a probe it
    would need a loop, and this test would stop being writable in this shape.
    """
    adapter = _adapter(tmp_path, vision_model="some-vlm")

    assert adapter.capabilities().vision is True
    assert adapter.capabilities().any_model() is True


def test_the_fingerprint_changes_when_the_configured_model_does(tmp_path):
    """It is what invalidates a derived transcript. If it did not move with the
    model, two models' readings would be indistinguishable in the corpus.

    Varies the *configured* revision, not the fake: the `CapabilitySet` is
    constructed from configuration rather than probed, so the configured model
    id is the thing the fingerprint is a function of.
    """
    one = _adapter(tmp_path, vision_model="v1").fingerprint
    two = _adapter(tmp_path, vision_model="v2").fingerprint

    assert one != two


async def test_a_declared_revision_that_lies_about_the_model_is_refused(tmp_path):
    """`build_perception` raises `DomainError` when the two disagree.

    The adapter derives both from one configured value, so this can only be
    reached by constructing them apart -- which is what this does, to pin the
    contract the single-value wiring exists to satisfy. Getting it wrong in
    production fails at first perception rather than silently keying the
    artifact cache on a model that did not produce the description.
    """
    digest = _write_blob(tmp_path, PNG_BYTES)
    adapter = ReadEverythingPerception(
        blob_root=tmp_path,
        vision=FakeVision(),
        vision_model="a-different-model",
        artifact_root=tmp_path.parent / "perception",
    )

    with pytest.raises(DomainError):
        await adapter.perceive(sha256=digest, max_chars=1000)


async def test_the_declared_capability_set_matches_the_configured_models(tmp_path):
    """One value feeds both the declaration and the injected model.

    What a test would fail on: wiring `AGENT_VISION_MODEL` into
    `build_openai_vision_model` but declaring some other string as the VISION
    revision, which `build_perception` refuses at startup -- but only if
    something proves the two come from one place.
    """
    adapter = _adapter(
        tmp_path,
        vision_model=FakeVision().model_id,
        vision=FakeVision(),
        transcriber_model=FakeTranscriber().model_id,
        transcriber=FakeTranscriber(),
    )

    expected = CapabilitySet.of(
        {
            Capability.VISION: FakeVision().model_id,
            Capability.ASR: FakeTranscriber().model_id,
            Capability.FFMPEG: "present",
        }
    )
    assert adapter.fingerprint == expected.fingerprint()
    assert adapter.capabilities().vision is True
    assert adapter.capabilities().asr is True


async def test_the_perception_is_built_once_and_reused(tmp_path):
    """Lazy and memoised: the second `perceive` awaits no second build.

    The build is deferred because `build_perception` is async and this
    adapter's constructor is called from the synchronous `build_application`.
    Rebuilding per call would re-probe and, worse, hand each reading a fresh
    `ResolutionMemo` -- the memo is the reason two perceptions of one blob cost
    one detection.
    """
    digest = _write_blob(tmp_path, PNG_BYTES)
    adapter = _adapter(tmp_path, vision_model=FakeVision().model_id, vision=FakeVision())

    await adapter.perceive(sha256=digest, max_chars=1000)
    first = adapter._perception
    await adapter.perceive(sha256=digest, max_chars=1000)

    assert adapter._perception is first


async def test_a_transcriber_is_reachable_through_a_mock_transport(tmp_path):
    """`RemoteWhisperTranscriber`'s `transport=` seam, exercised without a network.

    Here to prove the seam exists and is wired the way
    `build_perception_adapter` wires it -- base_url and model_id from
    configuration -- rather than to test whisper.cpp. No request is made unless
    something asks for speech, so the assertion is on construction and
    declaration, not on a response.
    """
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, json={"text": "nothing was said"})
    )
    transcriber = RemoteWhisperTranscriber(
        base_url="http://transcriber.invalid",
        model_id="whisper-large-v3",
        transport=transport,
    )
    adapter = _adapter(
        tmp_path,
        transcriber=transcriber,
        transcriber_model="whisper-large-v3",
    )

    assert adapter.capabilities().asr is True
    assert adapter.capabilities().vision is False


def _configure(monkeypatch, tmp_path) -> None:
    """Point config at `tmp_path` and clear every perception variable.

    Cleared rather than assumed absent: a developer with `AGENT_VISION_MODEL`
    exported would otherwise get different tests than CI.
    """
    monkeypatch.setenv("AGENT_BLOB_ROOT", str(tmp_path / "blobs"))
    monkeypatch.setenv("AGENT_PERCEPTION_ROOT", str(tmp_path / "perception"))
    for name in ("AGENT_VISION_MODEL", "AGENT_TRANSCRIBER_URL", "AGENT_TRANSCRIBER_MODEL"):
        monkeypatch.delenv(name, raising=False)


def test_the_factory_declares_the_built_vision_models_own_id(monkeypatch, tmp_path):
    """The declared VISION revision must be the *constructed* model's `model_id`.

    This is the regression test for a shipped bug. `build_openai_vision_model`
    prefixes its argument unconditionally -- `AGENT_VISION_MODEL=qwen2.5-vl`
    becomes `model_id == "openai/qwen2.5-vl"` (measured 2026-08-16 against
    0.2.0) -- so a factory that declared the raw config string handed
    `build_perception` two disagreeing values and raised `DomainError` on the
    first perceive of every vision-configured install.

    Both halves are asserted: that the declaration equals the model's id, and
    that the prefix is really there, so this stays a test of the wiring rather
    than a tautology if the library ever stops prefixing.

    Construction makes no network call -- verified in review with
    `socket.socket.connect` patched to raise. Caution about that is what kept
    this branch untested and let the bug ship.
    """
    _configure(monkeypatch, tmp_path)
    monkeypatch.setenv("AGENT_VISION_MODEL", "qwen2.5-vl")
    monkeypatch.setenv("AGENT_BASE_URL", "http://vision.invalid/v1/")

    adapter = build_perception_adapter()

    declared = adapter._capability_set.revisions[Capability.VISION]
    assert declared == adapter._vision.model_id
    assert declared == "openai/qwen2.5-vl"
    assert adapter.capabilities().vision is True


async def test_a_vision_configured_install_perceives_rather_than_refusing(
    monkeypatch, tmp_path
):
    """End to end through the factory: the `DomainError` must not be raised.

    The assertion above compares two strings; this one runs the comparison
    `build_perception` itself makes. It is the shape that reproduced the bug,
    so it is the shape kept. No request is made: the PNG is routed to the image
    handler, whose vision call is never reached for a `Budget` this small --
    and the base url points at `.invalid`, so a request would fail loudly
    rather than silently succeed against something real.
    """
    _configure(monkeypatch, tmp_path)
    monkeypatch.setenv("AGENT_VISION_MODEL", "qwen2.5-vl")
    monkeypatch.setenv("AGENT_BASE_URL", "http://vision.invalid/v1/")
    blob_root = tmp_path / "blobs"
    blob_root.mkdir(parents=True, exist_ok=True)
    digest = _write_blob(blob_root, PNG_BYTES)

    adapter = build_perception_adapter()
    perceived = await adapter.perceive(sha256=digest, max_chars=1000)

    assert perceived.text


def test_the_factory_declares_the_built_transcribers_own_id(monkeypatch, tmp_path):
    """ASR is taken off the object too, and there it is prevention not repair.

    The library's agreement check covers VISION only -- measured 2026-08-16 --
    so a mismatched ASR revision raises nothing and simply keys the artifact
    cache on a string no model reported. `RemoteWhisperTranscriber` does not
    rewrite `model_id` today, so this test would also pass against the config
    string; it is here so that stops being what the correctness depends on.
    """
    _configure(monkeypatch, tmp_path)
    monkeypatch.setenv("AGENT_TRANSCRIBER_URL", "http://transcriber.invalid/")
    monkeypatch.setenv("AGENT_TRANSCRIBER_MODEL", "whisper-large-v3")

    adapter = build_perception_adapter()

    declared = adapter._capability_set.revisions[Capability.ASR]
    assert declared == adapter._transcriber.model_id
    assert adapter.capabilities().asr is True
    assert adapter.capabilities().vision is False


def test_a_transcriber_url_without_a_model_refuses_to_start(monkeypatch, tmp_path):
    """Loud at startup, because the ASR revision is what invalidates a transcript.

    `config.transcriber_model()` has no default on purpose -- a default would
    let a swapped model reuse the previous one's cache entries silently. This
    pins that the factory lets that raise through rather than quietly building
    an install with a transcriber URL and no ASR.
    """
    _configure(monkeypatch, tmp_path)
    monkeypatch.setenv("AGENT_TRANSCRIBER_URL", "http://transcriber.invalid/")

    with pytest.raises(ValueError, match="AGENT_TRANSCRIBER_MODEL"):
        build_perception_adapter()


async def test_concurrent_first_perceives_build_one_perception(tmp_path, monkeypatch):
    """Five cold callers, one build. The in-lock re-check is what this pins.

    `test_the_perception_is_built_once_and_reused` is sequential and is
    satisfied entirely by the lock-free fast path: deleting the re-check
    *inside* the lock -- the exact regression the lock exists for -- leaves it
    green. Measured in review: 5 concurrent perceives give 1 build here and 5
    against the variant with the re-check removed.

    The `sleep(0)` inside the counted build is what makes the race reachable:
    without a suspension point every coroutine would run the build to
    completion before the next was scheduled, and the naive variant would pass.
    """
    digest = _write_blob(tmp_path, PNG_BYTES)
    adapter = _adapter(tmp_path, vision_model=FakeVision().model_id, vision=FakeVision())

    builds = 0
    real = readeverything_adapter.build_perception

    async def counting(*args, **kwargs):
        nonlocal builds
        builds += 1
        await asyncio.sleep(0)
        return await real(*args, **kwargs)

    monkeypatch.setattr(readeverything_adapter, "build_perception", counting)
    await asyncio.gather(*(adapter.perceive(sha256=digest, max_chars=1000) for _ in range(5)))

    assert builds == 1


def test_the_factory_starts_an_install_that_has_neither_model(monkeypatch, tmp_path):
    """An install with no ASR must not fail to start over `AGENT_TRANSCRIBER_MODEL`.

    `config.transcriber_model()` *raises* when unset, so the factory may only
    ask for it once a URL exists. What this fails on: hoisting that call out of
    the conditional, which turns every default install into a startup crash
    over a variable it has no use for.
    """
    monkeypatch.setenv("AGENT_BLOB_ROOT", str(tmp_path / "blobs"))
    monkeypatch.setenv("AGENT_PERCEPTION_ROOT", str(tmp_path / "perception"))
    monkeypatch.delenv("AGENT_VISION_MODEL", raising=False)
    monkeypatch.delenv("AGENT_TRANSCRIBER_URL", raising=False)
    monkeypatch.delenv("AGENT_TRANSCRIBER_MODEL", raising=False)

    adapter = build_perception_adapter()

    assert adapter.capabilities().any_model() is False
    assert adapter.fingerprint


def test_ffmpeg_presence_is_read_from_the_path_not_probed(tmp_path):
    """The declared FFMPEG capability tracks `shutil.which`, by construction.

    The accepted cost of declaring rather than probing: a binary present but
    broken reads as available here and fails later as a degradation. This
    asserts against the machine's real answer, so it is meaningful on CI's
    Ubuntu runners (ffmpeg 6.1.1 is installed there and here, measured
    2026-08-16) and does not become a false green on a machine without it.
    """
    from research_team.infrastructure.perception import ffmpeg_present

    assert ffmpeg_present() is (
        shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None
    )


def test_ffmpeg_presence_requires_ffprobe_too(tmp_path, monkeypatch):
    """One binary of the pair is not the capability.

    `readeverything`'s video path calls `ffprobe` before `ffmpeg`, so an
    install with only the second declares a capability it cannot deliver and
    the shortfall surfaces as a degradation from work already paid for. Proved
    red against the previous `shutil.which("ffmpeg") is not None`, which
    answered True here.
    """
    from research_team.infrastructure.perception import readeverything_adapter

    monkeypatch.setattr(
        readeverything_adapter.shutil,
        "which",
        lambda name: "/usr/bin/ffmpeg" if name == "ffmpeg" else None,
    )
    assert readeverything_adapter.ffmpeg_present() is False
