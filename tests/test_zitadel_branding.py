"""The hosted login pages carry the console's palette.

`docker/bootstrap-zitadel.sh` sets a Zitadel label policy from eight hex
literals, and every one of them is a copy of a value in
`frontend/src/styles/theme.css`. That is the shape `CLAUDE.md` warns about
under "two structures that must agree": the stylesheet is edited often, the
shell script almost never, and a branch that restyles the console has no
reason to touch it. Nothing conflicts, nothing is red, and the login page
quietly stops matching the product it signs you in to.

There is nothing to derive here -- one side is CSS and the other is `sh` -- so
this is the third remedy: a test that holds the pair, and that fails on the
branch that changes the palette rather than on `main` after a merge.
"""

import re
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_THEME = _ROOT / "frontend/src/styles/theme.css"
_BOOTSTRAP = _ROOT / "docker/bootstrap-zitadel.sh"

# The script's variable name, the token it copies, and which half of that
# token's `light-dark()` pair it holds.
_BRANDING = [
    ("brand_light_bg", "--color-bg", "light"),
    ("brand_light_fg", "--color-fg", "light"),
    ("brand_light_accent", "--color-accent", "light"),
    ("brand_light_warn", "--color-k-failure", "light"),
    ("brand_dark_bg", "--color-bg", "dark"),
    ("brand_dark_fg", "--color-fg", "dark"),
    ("brand_dark_accent", "--color-accent", "dark"),
    ("brand_dark_warn", "--color-k-failure", "dark"),
]


def _token(name: str, half: str) -> str:
    hex_ = r"(#[0-9a-fA-F]+)"
    pattern = rf"^\s*{re.escape(name)}:\s*light-dark\(\s*{hex_}\s*,\s*{hex_}\s*\)"
    match = re.search(pattern, _THEME.read_text(), re.MULTILINE)
    assert match is not None, f"{name} is not a light-dark() pair in {_THEME.name}"
    return (match.group(1) if half == "light" else match.group(2)).lower()


def _brand(variable: str) -> str:
    match = re.search(rf"^{variable}='(#[0-9a-fA-F]+)'$", _BOOTSTRAP.read_text(), re.MULTILINE)
    assert match is not None, f"{variable} is not set in {_BOOTSTRAP.name}"
    return match.group(1).lower()


@pytest.mark.parametrize(("variable", "token", "half"), _BRANDING)
def test_the_login_theme_carries_the_console_palette(
    variable: str, token: str, half: str
) -> None:
    """Fails when the palette moves and the login pages are left behind.

    Reverting either side of one pair fails this and nothing else -- proved by
    editing `brand_light_accent` to the Zitadel default `#5469d4`, which is red
    here and green under every other gate in the repository.
    """
    assert _brand(variable) == _token(token, half)
