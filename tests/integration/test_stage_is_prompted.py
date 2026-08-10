"""The methodology reaches the model, through the composed application.

`tests/application/test_prompts.py` proves the resolver resolves and
`tests/infrastructure/test_stage_middleware.py` proves the middleware appends
whatever it is handed. Neither can prove the composition root ever hands it a
*prompt* -- and for the whole life of `prompts.py` it did not: the module had
one importer, its own test, and `composition.py` built its instructions out of
artifact paths, the gate explanation and widget syntax, all of them mechanical.
From the model's side `ubd.pure` and `addie.pure` ran identically.

So these drive a fake model through a real `create_deep_agent` against the real
`prompts/` directory on disk, and assert on the text the model was actually
sent. Reverting the composition wiring turns every test in this file red.
"""

from pathlib import Path
from typing import Any
from uuid import uuid4

from langchain_core.messages import AIMessage

from research_team.application.prompts import DEFAULT_PROMPT_ROOT, UNPROMPTED_STAGE_NOTICE
from research_team.domain import AdvanceStage, CreateProject, SelectWorkflow
from research_team.workflows import hybrid_default, ubd_pure
from tests.conftest import ToolAwareFakeChatModel

DESIRED_RESULTS = "ubd.stage1.desired_results"
FRAMING = "hybrid.step1.framing"


class PromptRecordingChatModel(ToolAwareFakeChatModel):
    """Remembers every message list it was invoked with, system message included.

    Recorded on the model rather than asserted inside a middleware stub because
    the claim under test is about what crossed the boundary to the provider,
    and a stub sitting above the executor would pass just as happily if
    composition never wired the library at all.
    """

    seen: list[str] = []

    def bind_tools(self, tools: Any, **kwargs: Any) -> "PromptRecordingChatModel":
        return self

    def _generate(self, messages: list[Any], *args: Any, **kwargs: Any) -> Any:
        self.seen.append("\n".join(str(getattr(m, "text", "")) for m in messages))
        return super()._generate(messages, *args, **kwargs)

    @property
    def last_system_text(self) -> str:
        return self.seen[-1] if self.seen else ""


def _model() -> PromptRecordingChatModel:
    model = PromptRecordingChatModel(
        responses=[AIMessage(content="done", id="a1"), AIMessage(content="done", id="a2")]
    )
    model.seen = []
    return model


async def _project_at(application, preset, stage_id: str):
    project_id = uuid4()
    project = application.service.projects.create_new(project_id)
    project.execute(CreateProject(project_id=project_id, name="course"))
    project.execute(SelectWorkflow(preset=preset))
    # Walked one stage at a time because `AdvanceStage` refuses a jump: a
    # project sitting at the first stage can only be moved to the second. The
    # target is reached by replaying the boundaries a real run would cross.
    ids = [stage.id for stage in preset.stages]
    for next_id in ids[1 : ids.index(stage_id) + 1]:
        project.execute(
            AdvanceStage(
                preset=preset,
                to_stage=next_id,
                decided_by="human",
                gate_decision="approve",
            )
        )
    await application.service.projects.save(project)
    return project_id


async def test_a_ubd_stage_is_prompted_with_the_text_of_its_prompt_ref(build_application):
    """The claim this whole change exists to make true.

    Reads the file off disk rather than restating it, so the assertion cannot
    drift from the prompt and cannot be satisfied by wiring that happens to
    inject some other UbD-sounding text. A distinctive interior line is used
    rather than the whole body because `stage_prompt` appends `role_line` and
    the artifact block follows it.
    """
    body = (DEFAULT_PROMPT_ROOT / "ubd" / "stage1_generate.md").read_text()
    marker = [line for line in body.splitlines() if len(line) > 60][-1].strip()

    model = _model()
    application = await build_application(model=model)
    project_id = await _project_at(application, ubd_pure, DESIRED_RESULTS)
    await application.attach_project(project_id)
    session_id = await application.service.start_in_project(project_id)

    await application.service.run_turn(session_id, "hi")

    assert marker in model.last_system_text


async def test_the_generator_role_line_travels_with_the_prompt(build_application):
    """`role`, `taxonomy_binding` and `over_generate_factor` were inert until now.

    Would pass on a wiring that resolved the prompt and dropped `role_line`,
    which is exactly the half-wiring worth ruling out: the taxonomy binding is
    the field that decides whether the model works in `blooms_revised` or
    `six_facets`, and those are named-never-unioned because they conflict.
    """
    model = _model()
    application = await build_application(model=model)
    project_id = await _project_at(application, ubd_pure, DESIRED_RESULTS)
    await application.attach_project(project_id)
    session_id = await application.service.start_in_project(project_id)

    await application.service.run_turn(session_id, "hi")

    assert "You are working as:" in model.last_system_text


async def test_the_prompt_precedes_the_mechanics_it_must_not_repeat(build_application):
    """Ordering, asserted rather than left to a comment.

    What the stage is *for* comes before where it writes. The prompt contract
    is stated as negative space -- a prompt must not name its paths, its
    frontmatter or the gate -- and a prompt placed after those has to be read
    as a correction to them instead of as the thing they serve.
    """
    model = _model()
    application = await build_application(model=model)
    project_id = await _project_at(application, ubd_pure, DESIRED_RESULTS)
    await application.attach_project(project_id)
    session_id = await application.service.start_in_project(project_id)

    await application.service.run_turn(session_id, "hi")

    text = model.last_system_text
    assert text.index("You are working as:") < text.index("This stage writes")


async def test_a_stage_whose_prompt_is_missing_says_so_to_the_model(build_application):
    """The common case: 32 of 38 refs have no file, and the run still starts.

    `hybrid.step1.framing` references `prompts/addie/gap_framing`, which does
    not exist. Refusing to build would take the default preset offline; falling
    back silently would leave a methodology-free run indistinguishable from the
    system before prompts existed, which is the one failure nobody can see. The
    notice is what makes it visible, and it is asserted here rather than only
    logged because a log line is not something the model reads.
    """
    model = _model()
    application = await build_application(model=model)
    project_id = await _project_at(application, hybrid_default, FRAMING)
    await application.attach_project(project_id)
    session_id = await application.service.start_in_project(project_id)

    await application.service.run_turn(session_id, "hi")

    text = model.last_system_text
    assert UNPROMPTED_STAGE_NOTICE.splitlines()[0] in text
    assert "prompts/addie/gap_framing" in text


async def test_the_unprompted_stage_still_gets_its_mechanics(build_application):
    """Degrading is not disabling.

    The artifact block, the gate explanation and the tool filter are unaffected
    by a missing prompt -- they derive from the stage declaration, not from the
    library. Would pass with the wiring reverted; it is here so that a later
    change to the missing-ref policy cannot quietly take them with it.
    """
    model = _model()
    application = await build_application(model=model)
    project_id = await _project_at(application, hybrid_default, FRAMING)
    await application.attach_project(project_id)
    session_id = await application.service.start_in_project(project_id)

    await application.service.run_turn(session_id, "hi")

    assert "This stage writes" in model.last_system_text


def test_the_prompt_root_is_the_one_the_presets_spell() -> None:
    """A cwd-relative root would resolve differently under pytest than under uvicorn.

    Cheap to assert and the failure it rules out is expensive: a library rooted
    at a directory that happens not to exist raises `PromptError` at build, so
    the whole application would refuse to start from any working directory but
    the repository root.
    """
    assert DEFAULT_PROMPT_ROOT.is_dir()
    assert DEFAULT_PROMPT_ROOT.name == "prompts"
    assert (DEFAULT_PROMPT_ROOT / "ubd" / "stage1_generate.md").is_file()
    assert isinstance(DEFAULT_PROMPT_ROOT, Path)
