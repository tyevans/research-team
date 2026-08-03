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

FRAMEWORKS = ("langchain", "langchain_core", "langchain_openai", "deepagents", "eventsource")

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
