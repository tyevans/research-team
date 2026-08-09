"""The web entrypoint is wired as completely as the app factory asks to be.

This exists because the same bug has now shipped three times: a dependency is
added to `create_app`, every test constructs the app itself and passes it, and
`web.py` -- the one call production actually makes -- does not. Every test is
green and the running server answers 503 on the routes that needed it. The
corpus routes went out that way, and so did `topic_repository`.

A test that lists today's dependencies by hand would rot on the next one
added, which is precisely the failure being guarded against. So the list comes
from `create_app`'s own signature, read at test time: adding a parameter to
the factory is what makes this test start demanding it at the call site.
"""

import ast
import inspect
from pathlib import Path

import pytest

from research_team.interfaces.web import create_app

ENTRYPOINT = Path(__file__).resolve().parent.parent.parent / "web.py"


def _create_app_call() -> ast.Call:
    """The single `create_app(...)` call in the web entrypoint.

    Found by name in the syntax tree rather than by running `main()`: calling
    it would build the whole application against real config and then start a
    uvicorn server, and monkeypatching enough of that away would leave the
    test asserting against its own scaffolding instead of the file.
    """
    tree = ast.parse(ENTRYPOINT.read_text())
    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "create_app"
    ]
    assert len(calls) == 1, (
        f"expected one create_app call in {ENTRYPOINT.name}, found {len(calls)}"
    )
    return calls[0]


def _supplied_parameters(call: ast.Call, order: list[str]) -> dict[str, ast.expr]:
    """Parameter name -> the expression the entrypoint passes for it.

    Positional arguments are matched against the declared order, so moving a
    parameter in the signature without moving the argument is caught too.
    """
    # Not strict: fewer positional arguments than parameters is the ordinary
    # case here -- everything after `lifespan` is passed by keyword.
    supplied = dict(zip(order, call.args, strict=False))
    supplied.update({keyword.arg: keyword.value for keyword in call.keywords if keyword.arg})
    return supplied


def test_the_entrypoint_passes_every_dependency_create_app_accepts():
    """Fails the moment a parameter is added to `create_app` and not to `web.py`.

    Reverting the `topic_repository` fix turns this red, naming that parameter;
    it was red before the fix for the same reason.
    """
    signature = inspect.signature(create_app)
    order = list(signature.parameters)
    call = _create_app_call()
    missing = sorted(set(order) - set(_supplied_parameters(call, order)))
    assert not missing, (
        f"web.py does not pass {missing} to create_app -- these routes will answer "
        f"503 in the real server while every test that builds its own app passes"
    )


def test_the_entrypoint_passes_no_dependency_as_a_bare_none():
    """A parameter named at the call site but hard-coded `None` is not wiring.

    Passing `topics=None` would satisfy the test above while leaving the
    routes exactly as broken, so the literal is rejected here. A conditional
    that may evaluate to `None` -- `research` is one, deliberately withheld
    unless configured -- is not a literal and is left alone; see the comment
    above it in `web.py` for why that absence is a decision.
    """
    signature = inspect.signature(create_app)
    order = list(signature.parameters)
    nulled = sorted(
        name
        for name, value in _supplied_parameters(_create_app_call(), order).items()
        if isinstance(value, ast.Constant) and value.value is None
    )
    assert not nulled, f"web.py passes {nulled} as a literal None, which wires nothing"


@pytest.mark.parametrize("parameter", ["topics", "topic_repository", "corpus"])
def test_the_guarded_parameters_are_still_optional_on_the_factory(parameter):
    """The guard only means anything while the factory tolerates the absence.

    If these ever become required, `create_app` raises `TypeError` at the call
    site and this file is redundant rather than wrong -- but it would go on
    passing silently, so the assumption is stated where it can fail.
    """
    assert inspect.signature(create_app).parameters[parameter].default is None
