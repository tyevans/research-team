"""The `readeverything` adapter, over a real temporary blob tree.

**Nothing here touches the network.** The vision and ASR seams are filled with
`readeverything`'s own fakes, and the one test that exercises
`RemoteWhisperTranscriber` hands it an `httpx.MockTransport`. A test that
reached a real transcriber would pass only on the machine that has one, and
would pin this suite to somebody's LAN address.
"""

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
    differs from `vision.model_id`, so the two are derived from one value here
    exactly as `build_perception_adapter` derives them from one setting.
    """
    return ReadEverythingPerception(
        blob_root=blob_root,
        vision=vision,
        transcriber=transcriber,
        vision_model=vision_model,
        transcriber_model=transcriber_model,
        ffmpeg=ffmpeg,
        artifact_root=blob_root.parent / "perception",
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

    assert ffmpeg_present() is (shutil.which("ffmpeg") is not None)
