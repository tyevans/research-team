"""The dependency rule, enforced.

Clean architecture is a claim about which way imports point. A claim that only
lives in a README stops being true the first time someone is in a hurry, so it
is asserted here instead: dependencies point inward, and the inner layers name
no framework.
"""

import ast
from pathlib import Path

import pytest

PACKAGE = Path(__file__).resolve().parent.parent / "research_team"

# Innermost first. A layer may import from itself and anything before it.
LAYERS = ("domain", "application", "infrastructure", "interfaces")

# There is no content-package exemption any more. `CONTENT` named
# `research_team/workflows/` -- the shipped presets, data rather than a layer
# -- and the workflow removal deleted that package. Removed rather than
# emptied to `frozenset()`: its guard,
# `test_content_packages_depend_only_on_the_domain`, was parametrised over the
# package's modules, so an empty set would leave a test that collects nothing
# and reads as passing. The exemption is cheap to reinstate if a data package
# ever returns; a test that silently checks nothing is not.

FRAMEWORKS = (
    "langchain",
    "langchain_core",
    "langchain_openai",
    "deepagents",
    "eventsource",
    "redstring",
)

# The domain is built on the event-sourcing primitives; that is the one
# framework it is allowed to name. Everything else stays outside.
ALLOWED_FRAMEWORKS = {
    "domain": {"eventsource"},
    "application": {"eventsource"},
}


def _modules(layer: str) -> list[Path]:
    return sorted((PACKAGE / layer).rglob("*.py"))


def _imported_roots(module: Path) -> set[str]:
    tree = ast.parse(module.read_text())
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            roots.add(node.module.split(".")[0])
    return roots


def _imported_paths(module: Path) -> set[str]:
    """Every absolute import, at full dotted length.

    `_imported_roots` truncates to the root package, which is right for the
    framework rule and blind to the one below: `redstring.domain.x` and
    `redstring` are the same string to it, and the whole point here is that
    they are not the same import.
    """
    tree = ast.parse(module.read_text())
    paths: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            paths.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            paths.add(node.module)
    return paths


def _imported_layers(module: Path) -> set[str]:
    tree = ast.parse(module.read_text())
    layers: set[str] = set()
    for node in ast.walk(tree):
        target = None
        if isinstance(node, ast.ImportFrom) and node.module:
            target = node.module
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith("research_team."):
                    layers.add(alias.name.split(".")[1])
            continue
        if target and target.startswith("research_team."):
            layers.add(target.split(".")[1])
    return layers


ALL_MODULES = [(layer, module) for layer in LAYERS for module in _modules(layer)]


@pytest.mark.parametrize(
    ("layer", "module"),
    ALL_MODULES,
    ids=[f"{layer}/{module.name}" for layer, module in ALL_MODULES],
)
def test_imports_point_inward(layer: str, module: Path) -> None:
    permitted = set(LAYERS[: LAYERS.index(layer) + 1])
    offenders = _imported_layers(module) - permitted
    assert not offenders, f"{module.relative_to(PACKAGE)} imports outward: {offenders}"


@pytest.mark.parametrize(
    ("layer", "module"),
    [(layer, module) for layer, module in ALL_MODULES if layer in ALLOWED_FRAMEWORKS],
    ids=[
        f"{layer}/{module.name}"
        for layer, module in ALL_MODULES
        if layer in ALLOWED_FRAMEWORKS
    ],
)
def test_inner_layers_name_no_framework(layer: str, module: Path) -> None:
    used = _imported_roots(module) & set(FRAMEWORKS)
    forbidden = used - ALLOWED_FRAMEWORKS[layer]
    assert not forbidden, (
        f"{module.relative_to(PACKAGE)} depends on {forbidden}; "
        "keep frameworks in infrastructure"
    )


@pytest.mark.parametrize(
    ("layer", "module"),
    ALL_MODULES,
    ids=[f"{layer}/{module.name}" for layer, module in ALL_MODULES],
)
def test_redstring_is_named_only_through_its_public_surface(layer: str, module: Path) -> None:
    """Anything under `redstring.domain.` is out; everything else is in.

    redstring's contract is that anything reached by a dotted path is internal
    and may change in a patch release -- so a dotted import into `domain` is a
    dependency on a private API that a *patch* bump can break, silently, in a
    package this repository pins below the next minor precisely because it
    moves.

    The concrete near-miss: `render_temporal` lives at
    `redstring.domain.temporal_parsing` and is not exported. It is the
    obvious-looking way to render a temporal extent and the wrong one
    (`temporal_rendering.py` says why), and without this rule reaching for it
    passes every other test in this file.

    Scoped to `redstring.domain.` rather than all of `redstring.` -- the
    broader rule was tried first and failed on three modules that were never
    the target: `infrastructure/agent/deep_agent.py`,
    `infrastructure/knowledge/stores.py` and
    `infrastructure/persistence/event_store.py` all reach into optional
    backend adapters (`redstring.llm.adapters.langchain`,
    `redstring.graph.adapters.neo4j`, `redstring.vector.adapters.pgvector`,
    `redstring.events.streams`) that redstring does not, and cannot, re-export
    from its top level -- doing so would pull neo4j, pgvector and langchain
    into every install regardless of which backend a project actually uses.
    The dotted path is the *only* way to reach them, by design, so forbidding
    it forbids something the package requires rather than something it
    exposes by mistake. `domain` carries no such excuse: everything public in
    it is already in `redstring.__all__`.

    This means a dotted import of some other internal outside `domain` --
    `redstring.temporal.query`, say -- passes unflagged. That is a known gap
    in this rule's reach, not an oversight: closing it would mean re-deriving,
    module by module, which parts of redstring are genuinely unreachable any
    other way, and nothing today needs that. `domain` is where the actual
    near-miss lives, and that is what this rule closes.

    Scoped to `research_team/` deliberately, on top of that. `tests/` builds
    redstring fixtures through dotted paths and stays free to: a test
    constructing an `Entity` is not shipping against a private API.
    """
    offenders = {
        path for path in _imported_paths(module) if path.startswith("redstring.domain.")
    }
    assert not offenders, (
        f"{module.relative_to(PACKAGE)} imports redstring internals: {offenders}; "
        "use the package's public surface"
    )


def test_only_the_entrypoint_imports_the_composition_root() -> None:
    """`composition` may know every layer, so no layer may know `composition`."""
    for _, module in ALL_MODULES:
        assert "composition" not in _imported_layers(module), (
            f"{module.relative_to(PACKAGE)} imports the composition root; "
            "let the entrypoint inject what it needs"
        )


def test_composition_root_is_the_only_place_that_wires_adapters() -> None:
    """Only the composition root and interfaces may name a concrete adapter."""
    wiring = {"EventStoreSessionRepository", "DeepAgentTurnExecutor"}
    for layer in ("domain", "application"):
        for module in _modules(layer):
            source = module.read_text()
            named = {name for name in wiring if name in source}
            assert not named, f"{module.relative_to(PACKAGE)} names adapters: {named}"
