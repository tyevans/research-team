"""Perception, wired at composition: the seam Task 6 exists to prove.

Two claims, and each is the failure `task-6-brief.md` names by name.

1. **No network at construction.** `build_application` with no
   `AGENT_VISION_MODEL` and no `AGENT_TRANSCRIBER_URL` set must build a port
   whose `capabilities()` reports nothing perceivable -- without awaiting
   anything, per `PerceptionPort.capabilities`'s own contract. This is the
   no-network guard at the seam where a `build_openai_vision_model` or a
   `RemoteWhisperTranscriber` would otherwise be born.

2. **The derived-text projection handler is actually reached.** CLAUDE.md's
   Events section records the exact failure this guards against: an event no
   projection handles still counts as APPLIED, so a build with the perceiver
   wired and `CorpusProjection._on_derived_text` not registered would answer
   every perceive request as a stored 200 and leave the corpus table with
   nothing to show for it. Asserting the call returned would pass in that
   broken build; only a stored row proves the handler ran. `perception=` is
   a fake here for the same reason `model=` is a fake in
   `test_definition_wiring.py` -- nothing in this file reaches a network or
   names a model host.
"""

from uuid import uuid4

import pytest

from research_team.application.corpus_editing import CorpusEditor
from research_team.application.perception import (
    LocatorSpan,
    Perceived,
    PerceptionCapabilities,
    derived_source_id,
)
from research_team.infrastructure.persistence.corpus_reader import ProjectCorpusReader


class FakePerception:
    """`PerceptionPort`, with the reading and the capabilities both dictated.

    `tests/application/test_perception.py` has the fuller-featured twin of
    this fixture; this one carries only what a composition-level test needs,
    so a change to the use case's own edge cases does not ripple into this
    file's wiring assertions.
    """

    def __init__(
        self,
        perceived: Perceived | None = None,
        capabilities: PerceptionCapabilities | None = None,
    ) -> None:
        self._perceived = perceived or Perceived(
            text="A talk about otters.",
            locators=(LocatorSpan(0, 10, {"kind": "time", "start_s": 0.0, "end_s": 4.0}),),
            fingerprint="vision=v1,asr=w1",
            degradations=(),
        )
        self._capabilities = capabilities or PerceptionCapabilities(
            vision=True, asr=True, ffmpeg=True
        )

    async def perceive(self, *, sha256: str, max_chars: int) -> Perceived:
        return self._perceived

    def capabilities(self) -> PerceptionCapabilities:
        return self._capabilities


async def _bytes():
    yield b"not a real video, just bytes to hash"


async def test_no_transcriber_is_constructed_without_configuration(
    monkeypatch, build_application
):
    """The no-network guard, at the seam where a network client would be born.

    Unset both variables `build_perception_adapter` reads: with neither, the
    adapter it builds must declare no capability, without awaiting -- which is
    the whole of what makes it safe to call from a synchronous
    `build_application` in the first place.
    """
    monkeypatch.delenv("AGENT_TRANSCRIBER_URL", raising=False)
    monkeypatch.delenv("AGENT_VISION_MODEL", raising=False)

    application = await build_application()

    assert application.perception.capabilities().any_model() is False


async def test_a_perceived_medium_lands_in_the_corpus_table(build_application):
    """The stored-row assertion CLAUDE.md's Events section insists on.

    A build with `MediaPerceiver` wired but `CorpusProjection._on_derived_text`
    unregistered would still answer `perceiver.perceive(...)` successfully --
    `StoreDerivedText` would be appended and the call would return a
    `PerceptionReport` -- and would leave `corpus_documents` with no row for
    it, because nothing subscribed. Asserting the call returned would not
    catch that; this test asserts the row a reader built the way production
    builds one can see.
    """
    project_id = uuid4()
    port = FakePerception()
    application = await build_application(project_id=project_id, perception=port)

    # Seeded through the composed application's own editor -- the same object
    # `POST /api/projects/{id}/documents` drives -- so the medium the
    # perceiver reads is a record composition actually wrote, not one this
    # test assembled by hand.
    assert isinstance(application.editor, CorpusEditor)
    await application.editor.store_media(
        project_id,
        "vid-1",
        _bytes(),
        "video/mp4",
        title="A talk",
    )
    await application.corpus_caught_up()

    report = await application.perceiver.perceive(project_id, "vid-1")

    await application.corpus_caught_up()
    reader = ProjectCorpusReader(application.corpus, project_id, application.blob_store)
    stored = await reader.read_document(derived_source_id("vid-1"))

    assert stored is not None
    assert stored.text == "A talk about otters."
    assert stored.record.source_id == report.source_id
    assert stored.record.derived_from == "vid-1"


async def test_perception_is_the_injected_fake_not_a_second_instance(build_application):
    """`perception=` genuinely overrides, rather than being merged with a
    real adapter built alongside it.

    Task 9's end-to-end test depends on this: it injects a fake so its build
    reaches no network at all. If `build_application` built a real
    `ReadEverythingPerception` regardless and merely preferred the injected
    port for `perceiver`, `application.perception` would still be the fake --
    this asserts identity, not behaviour, so a future refactor that keeps
    behaviour but loses the override is still caught.
    """
    port = FakePerception()

    application = await build_application(perception=port)

    assert application.perception is port
    # `perceiver` is built over the same instance, not a second one wired
    # from an unrelated default -- the identity a caller of `perceive` relies
    # on to know which port actually ran.
    assert application.perceiver._port is port


async def test_capabilities_reflect_configuration_when_nothing_is_injected(
    monkeypatch, build_application
):
    """The complement of the no-network guard: configured, it reports so.

    Without this, an install with a real `AGENT_VISION_MODEL` set could be
    silently declaring no capability and the no-network test above would not
    say so -- it only proves the unconfigured case, not that configuration is
    read at all.
    """
    monkeypatch.setenv("AGENT_VISION_MODEL", "qwen2.5-vl")
    monkeypatch.delenv("AGENT_TRANSCRIBER_URL", raising=False)

    application = await build_application()

    capabilities = application.perception.capabilities()
    assert capabilities.vision is True
    assert capabilities.any_model() is True


async def test_a_raise_late_in_build_application_never_constructs_the_media_client(
    monkeypatch,
):
    """B98: the media `httpx.AsyncClient` used to be built early in
    `build_application`, roughly a thousand lines and one raise-shaped
    function above `Application(...)`. Anything raising in that window left
    the client constructed with no owner to close it -- `Application.close()`
    is unconditional but only exists once an `Application` does.

    Asserting the client got closed (the more direct claim) is not cheaply
    testable: nothing in `build_application`'s raise path holds a reference
    to it once the function unwinds, so there is nothing to call `.aclose()`
    on and check. What *is* testable, and is what the fix actually changed,
    is the ordering: the client is now built last, immediately before
    `Application(...)`, so a raise anywhere earlier -- `WorkerRoster` here,
    the constructor built immediately before it -- must never construct one
    at all. Red against the pre-fix ordering: `WorkerRoster` is built after
    the client, so patching it to raise did not stop the client from having
    already been constructed and left open.
    """
    import httpx

    from research_team import composition

    built = []
    real_init = httpx.AsyncClient.__init__

    def _tracking_init(self, *args, **kwargs):
        # `type(self) is httpx.AsyncClient` rather than `isinstance`: the
        # default model build constructs `langchain_openai`/`openai` clients
        # that subclass `httpx.AsyncClient`, unrelated to this fix and built
        # earlier regardless of ordering. Only a bare `httpx.AsyncClient` is
        # the one this function builds for `media_http_client`.
        if type(self) is httpx.AsyncClient:
            built.append(self)
        real_init(self, *args, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "__init__", _tracking_init)

    class _Boom(Exception):
        pass

    def _raise(*args, **kwargs):
        raise _Boom("WorkerRoster refuses to build")

    monkeypatch.setattr(composition, "WorkerRoster", _raise)

    with pytest.raises(_Boom):
        composition.build_application()

    assert built == []
    for client in built:
        await client.aclose()
