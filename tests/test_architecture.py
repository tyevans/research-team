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


def _layer_of_module(module: Path) -> str | None:
    parts = module.relative_to(PACKAGE).parts
    for layer in ("domain", "application", "infrastructure", "interfaces"):
        if layer in parts:
            return layer
    if "platform" in parts:
        return "application"
    return None


def _modules(layer: str) -> list[Path]:
    return sorted(p for p in PACKAGE.rglob("*.py") if _layer_of_module(p) == layer)


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


def _layer_of_target(target: str) -> str | None:
    parts = target.split(".")
    for layer in ("domain", "application", "infrastructure", "interfaces"):
        if layer in parts:
            return layer
    if "platform" in parts:
        return "application"
    if "composition" in parts or "wiring" in parts:
        return "composition"
    return None


def _imported_layers(module: Path) -> set[str]:
    tree = ast.parse(module.read_text())
    layers: set[str] = set()
    for node in ast.walk(tree):
        targets: list[str] = []
        if isinstance(node, ast.ImportFrom) and node.module:
            targets.append(node.module)
        elif isinstance(node, ast.Import):
            targets.extend(alias.name for alias in node.names)
        for target in targets:
            if target.startswith("research_team."):
                layer = _layer_of_target(target)
                if layer:
                    layers.add(layer)
    return layers


ALL_MODULES = [(layer, module) for layer in LAYERS for module in _modules(layer)]


@pytest.mark.parametrize(
    ("layer", "module"),
    ALL_MODULES,
    ids=[f"{layer}/{module.relative_to(PACKAGE)}" for layer, module in ALL_MODULES],
)
def test_imports_point_inward(layer: str, module: Path) -> None:
    permitted = set(LAYERS[: LAYERS.index(layer) + 1])
    offenders = _imported_layers(module) - permitted
    assert not offenders, f"{module.relative_to(PACKAGE)} imports outward: {offenders}"


@pytest.mark.parametrize(
    ("layer", "module"),
    [(layer, module) for layer, module in ALL_MODULES if layer in ALLOWED_FRAMEWORKS],
    ids=[
        f"{layer}/{module.relative_to(PACKAGE)}"
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
    ids=[f"{layer}/{module.relative_to(PACKAGE)}" for layer, module in ALL_MODULES],
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


def test_the_removed_workflows_package_does_not_come_back_as_a_directory() -> None:
    """An empty `research_team/workflows/` is importable, and was.

    B147 deleted the workflow system's sources on 2026-08-27 and left the
    compiled bytecode behind in `research_team/workflows/__pycache__/`. That
    is gitignored, so it survives every checkout, every branch switch and
    every `git clean` that spares ignored files, and CI -- which starts from
    a clean tree -- cannot see it at all. This test can, which is the only
    reason it is worth its two lines: it fails on a developer's machine and
    nowhere else.

    Measured on 2026-08-29 rather than reasoned, because the obvious fear is
    the wrong one: `research_team.workflows.ubd` is **not** importable from
    bytecode under `__pycache__` (sourceless import wants the `.pyc` at the
    source's own path). What *is* importable is `research_team.workflows`
    itself, as an empty namespace package, because the directory exists. So
    the guard is over the directory, not over the modules.
    """
    assert not (PACKAGE / "workflows").exists(), (
        "research_team/workflows/ is back, or its orphaned __pycache__ was "
        "never cleaned; the package was deleted with B147 and an empty "
        "directory still imports as a namespace package"
    )


BOUNDED_CONTEXTS = (
    "curriculum",
    "dialogue",
    "knowledge",
    "research",
    "session",
    "settings",
    "tenancy",
)


def _bc_of_module(module: Path) -> str | None:
    parts = module.relative_to(PACKAGE).parts
    if parts and parts[0] in BOUNDED_CONTEXTS:
        return parts[0]
    return None


DOMAIN_MODULES = [m for m in _modules("domain") if _bc_of_module(m) is not None]


@pytest.mark.parametrize(
    "module",
    DOMAIN_MODULES,
    ids=[str(m.relative_to(PACKAGE)) for m in DOMAIN_MODULES],
)
def test_domain_layers_are_isolated_from_other_bounded_contexts(module: Path) -> None:
    """DDD domain purity: a bounded context's domain never imports another bounded context."""
    bc = _bc_of_module(module)
    assert bc is not None
    other_bcs = set(BOUNDED_CONTEXTS) - {bc}
    for imported in _imported_paths(module):
        if imported.startswith("research_team."):
            parts = imported.split(".")
            if len(parts) >= 2 and parts[1] in other_bcs:
                pytest.fail(
                    f"{module.relative_to(PACKAGE)} imports from other bounded context "
                    f"'{parts[1]}': {imported}. Domain layers must be strictly isolated."
                )


ALL_BC_MODULES = [
    (layer, module) for layer, module in ALL_MODULES if _bc_of_module(module) is not None
]


@pytest.mark.parametrize(
    ("layer", "module"),
    ALL_BC_MODULES,
    ids=[f"{layer}/{module.relative_to(PACKAGE)}" for layer, module in ALL_BC_MODULES],
)
def test_bounded_contexts_do_not_import_other_bounded_context_outer_layers(
    layer: str, module: Path
) -> None:
    """A bounded context may not depend on another's infrastructure or interfaces."""
    bc = _bc_of_module(module)
    assert bc is not None
    other_bcs = set(BOUNDED_CONTEXTS) - {bc}
    for imported in _imported_paths(module):
        if imported.startswith("research_team."):
            parts = imported.split(".")
            if len(parts) >= 3 and parts[1] in other_bcs:
                target_layer = parts[2]
                if target_layer in ("infrastructure", "interfaces"):
                    pytest.fail(
                        f"{module.relative_to(PACKAGE)} reaches into "
                        f"'{parts[1]}.{target_layer}': {imported}. "
                        "Cross-context interactions must go through "
                        "application or domain contracts."
                    )


def test_knowledge_bc_does_not_depend_on_research_bc() -> None:
    """Knowledge bounded context must not depend on Research bounded context."""
    knowledge_dir = PACKAGE / "knowledge"
    knowledge_modules = sorted(p for p in knowledge_dir.rglob("*.py") if p.is_file())
    assert knowledge_modules, "Expected knowledge modules to exist"
    for module in knowledge_modules:
        for imported in _imported_paths(module):
            if imported.startswith("research_team.research"):
                pytest.fail(
                    f"{module.relative_to(PACKAGE)} imports from research bounded context: "
                    f"{imported}. Knowledge must not depend on Research."
                )


def test_platform_shared_does_not_depend_on_domain_bounded_contexts() -> None:
    """Platform shared foundation must not depend on any domain bounded context."""
    platform_dir = PACKAGE / "platform"
    platform_modules = sorted(p for p in platform_dir.rglob("*.py") if p.is_file())
    assert platform_modules, "Expected platform modules to exist"
    for module in platform_modules:
        for imported in _imported_paths(module):
            if imported.startswith("research_team."):
                parts = imported.split(".")
                if len(parts) >= 2 and parts[1] in BOUNDED_CONTEXTS:
                    pytest.fail(
                        f"{module.relative_to(PACKAGE)} imports from domain bounded "
                        f"context '{parts[1]}': {imported}. "
                        "Platform must remain domain-agnostic."
                    )
