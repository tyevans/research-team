"""Course artifacts, from the stage that declares them to files in the log.

The unit tests derive paths from presets. What they cannot show is that the
paths ever reach the model, that a file written to one lands in the aggregate's
filesystem, or that the two stages of a run leave a directory whose alphabetical
listing reads in stage order -- which is the entire point of the numeric prefix
and the only part of it a person will ever notice.

The model here is scripted rather than intelligent: it writes exactly what a
compliant model would write. That deliberately does not test whether the prompt
*persuades* a real model -- nothing offline can -- but it does test that a
compliant write lands where the rest of the system will look for it, which is
the half that can break silently.
"""

from uuid import uuid4

from langchain_core.messages import AIMessage

from research_team.application.artifacts import parse_frontmatter, stage_artifact_paths
from research_team.domain import AdvanceStage, CreateProject, SelectWorkflow
from research_team.workflows import hybrid_default
from tests.conftest import ToolAwareFakeChatModel

INTAKE = "tyler.step0.intake"
FRAMING = "hybrid.step1.framing"


def _stage(stage_id: str):
    return next(stage for stage in hybrid_default.stages if stage.id == stage_id)


def _artifact(stage_id: str, artifact_type: str, provenance: str) -> str:
    """What a compliant model writes: a frontmatter block, then prose."""
    return (
        "---\n"
        f"artifact_type: {artifact_type}\n"
        f"stage: {stage_id}\n"
        f"preset: {hybrid_default.id}\n"
        f"preset_version: '{hybrid_default.version}'\n"
        "provenance:\n"
        f"{provenance}"
        "---\n"
        "\n# Heading\n\nThe body of the artifact.\n"
    )


CITED = "  - source_id: doc-1\n    start: 0\n    end: 120\n"
INFERRED = "  - inferred_not_in_source: true\n"


def _writes(stage_id: str, call_id: str, cited: bool = True) -> list[AIMessage]:
    """One turn's worth of messages: write every file the stage declares, then reply."""
    stage = _stage(stage_id)
    calls = [
        {
            "name": "write_file",
            "args": {
                "file_path": path,
                "content": _artifact(
                    stage_id,
                    output.artifact_type.value,
                    CITED if cited else INFERRED,
                ),
            },
            "id": f"{call_id}-{index}",
        }
        for index, (path, output) in enumerate(
            zip(stage_artifact_paths(hybrid_default, stage), stage.outputs, strict=True)
        )
    ]
    return [
        AIMessage(content="", id=f"{call_id}-a", tool_calls=calls),
        AIMessage(content=f"wrote the {stage_id} artifacts", id=f"{call_id}-b"),
    ]


async def _project(application):
    project_id = uuid4()
    project = application.service.projects.create_new(project_id)
    project.execute(CreateProject(project_id=project_id, name="course"))
    project.execute(SelectWorkflow(preset=hybrid_default))
    await application.service.projects.save(project)
    return project_id


async def _advance(application, project_id, to_stage: str) -> None:
    project = await application.service.projects.load(project_id)
    project.execute(
        AdvanceStage(
            preset=hybrid_default,
            to_stage=to_stage,
            decided_by="human",
            gate_decision="approve",
        )
    )
    await application.service.projects.save(project)


async def _run_two_stages(build_application):
    """A run through intake and then framing, returning the session's files."""
    model = ToolAwareFakeChatModel(
        responses=[*_writes(INTAKE, "s0"), *_writes(FRAMING, "s1", cited=False)]
    )
    application = await build_application(model=model)
    project_id = await _project(application)
    await application.attach_project(project_id)
    session_id = await application.service.start_in_project(project_id)

    await application.service.run_turn(session_id, "do the intake")
    await _advance(application, project_id, FRAMING)
    await application.service.run_turn(session_id, "frame the context")

    session = await application.service.load(session_id)
    return session.state.files


async def test_both_stages_artifacts_land_at_their_declared_paths(build_application):
    files = await _run_two_stages(build_application)

    expected = [
        *stage_artifact_paths(hybrid_default, _stage(INTAKE)),
        *stage_artifact_paths(hybrid_default, _stage(FRAMING)),
    ]
    assert set(expected) <= set(files)


async def test_a_stages_declared_outputs_all_appear(build_application):
    """The declaration is the contract; a missing file is a detectable gap."""
    files = await _run_two_stages(build_application)

    for stage_id in (INTAKE, FRAMING):
        stage = _stage(stage_id)
        written = [
            path for path in stage_artifact_paths(hybrid_default, stage) if path in files
        ]
        assert len(written) == len(stage.outputs)


async def test_every_artifact_carries_parseable_typed_frontmatter(build_application):
    files = await _run_two_stages(build_application)

    course = {path: entry for path, entry in files.items() if path.startswith("/course/")}
    assert course, "expected the run to have written course artifacts"
    for path, entry in course.items():
        front, body = parse_frontmatter(entry["content"])
        assert front is not None, path
        assert set(front) >= {
            "artifact_type",
            "stage",
            "preset",
            "preset_version",
            "provenance",
        }, path
        assert front["preset"] == hybrid_default.id
        assert front["provenance"], f"{path} claims nothing, sourced or inferred"
        assert body.strip()


async def test_the_stage_recorded_in_a_file_is_the_stage_that_wrote_it(build_application):
    """Cheap, and the thing that goes wrong when a stage block is copy-pasted."""
    files = await _run_two_stages(build_application)

    for stage_id in (INTAKE, FRAMING):
        for path in stage_artifact_paths(hybrid_default, _stage(stage_id)):
            front, _ = parse_frontmatter(files[path]["content"])
            assert front["stage"] == stage_id


async def test_an_inferred_artifact_says_so_rather_than_citing_nothing(build_application):
    """The framing stage's files were written with no source behind them.

    The flag is what keeps that visible. Without it the file is
    indistinguishable from one that was checked against the corpus, which is
    the failure the whole provenance convention exists to prevent.
    """
    files = await _run_two_stages(build_application)

    for path in stage_artifact_paths(hybrid_default, _stage(FRAMING)):
        front, _ = parse_frontmatter(files[path]["content"])
        assert front["provenance"] == [{"inferred_not_in_source": True}]


async def test_alphabetical_order_is_stage_order(build_application):
    """What a person actually sees: the file list, sorted, reading in order."""
    files = await _run_two_stages(build_application)

    course = sorted(path for path in files if path.startswith("/course/"))
    stages = [parse_frontmatter(files[path]["content"])[0]["stage"] for path in course]
    assert stages == [INTAKE] * len(_stage(INTAKE).outputs) + [FRAMING] * len(
        _stage(FRAMING).outputs
    )


async def test_the_paths_the_model_is_told_to_write_are_the_paths_derived(
    build_application,
):
    """The prompt and the derivation are one source, so they cannot drift.

    Asserted against what the model was actually sent, because the failure
    worth catching is a stage block that names plausible paths nothing else
    computes -- which looks fine in the transcript and produces a course
    directory no check can find.
    """

    class PromptRecording(ToolAwareFakeChatModel):
        prompts: list[str] = []

        def _generate(self, messages, stop=None, run_manager=None, **kwargs):
            self.prompts.append("\n".join(str(message.content) for message in messages))
            return super()._generate(messages, stop=stop, run_manager=run_manager, **kwargs)

    model = PromptRecording(responses=[AIMessage(content="noted", id="a1")])
    application = await build_application(model=model)
    project_id = await _project(application)
    await application.attach_project(project_id)
    session_id = await application.service.start_in_project(project_id)

    await application.service.run_turn(session_id, "what do you write here?")

    [sent] = model.prompts
    for path in stage_artifact_paths(hybrid_default, _stage(INTAKE)):
        assert path in sent
    assert "inferred_not_in_source" in sent
