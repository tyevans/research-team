"""The security boundary for model-generated SVG. Adversarial cases first,
per CLAUDE.md and the increment-3 spec's testing section -- a sanitiser
proven only against inputs it was designed to pass proves nothing about the
inputs it exists to catch."""

from research_team.infrastructure.knowledge.svg_sanitiser import (
    MAX_SVG_BYTES,
    SvgSanitiser,
)

_VALID = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">'
    '<rect width="64" height="64" fill="#123"/></svg>'
)


def _sanitiser() -> SvgSanitiser:
    return SvgSanitiser()


def test_a_plain_shape_with_a_view_box_passes():
    assert _sanitiser().sanitise(_VALID) == _VALID


def test_a_gradient_and_group_pass():
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">'
        '<defs><linearGradient id="g"><stop offset="0" stop-color="#fff"/>'
        '<stop offset="1" stop-color="#000"/></linearGradient></defs>'
        '<g><circle cx="10" cy="10" r="5" fill="url(#g)"/></g>'
        "</svg>"
    )
    assert _sanitiser().sanitise(svg) == svg


def test_a_script_element_is_refused():
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">'
        "<script>alert(1)</script></svg>"
    )
    assert _sanitiser().sanitise(svg) is None


def test_an_onload_attribute_is_refused():
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" onload="alert(1)">'
        '<rect width="1" height="1"/></svg>'
    )
    assert _sanitiser().sanitise(svg) is None


def test_an_external_href_is_refused():
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">'
        '<a href="https://evil.example/"><rect width="1" height="1"/></a></svg>'
    )
    assert _sanitiser().sanitise(svg) is None


def test_an_xlink_href_is_refused():
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" '
        'xmlns:xlink="http://www.w3.org/1999/xlink" viewBox="0 0 64 64">'
        '<use xlink:href="#somewhere"/></svg>'
    )
    assert _sanitiser().sanitise(svg) is None


def test_a_foreign_object_is_refused():
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">'
        '<foreignObject><div xmlns="http://www.w3.org/1999/xhtml">hi</div>'
        "</foreignObject></svg>"
    )
    assert _sanitiser().sanitise(svg) is None


def test_an_entity_expansion_payload_is_refused():
    """Billion-laughs shape: a DOCTYPE defining nested internal entities.
    expat either refuses to parse this outright or the size cap below catches
    it -- either way `sanitise` must return None, not hang or raise past this
    boundary."""
    svg = (
        '<?xml version="1.0"?>'
        "<!DOCTYPE svg [ "
        '<!ENTITY a "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa">'
        '<!ENTITY b "&a;&a;&a;&a;&a;&a;&a;&a;&a;&a;">'
        '<!ENTITY c "&b;&b;&b;&b;&b;&b;&b;&b;&b;&b;">'
        "]>"
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">'
        "<title>&c;</title></svg>"
    )
    assert _sanitiser().sanitise(svg) is None


def test_bytes_that_do_not_parse_are_refused():
    assert _sanitiser().sanitise("<svg><rect ") is None


def test_a_missing_view_box_is_refused():
    svg = '<svg xmlns="http://www.w3.org/2000/svg"><rect width="1" height="1"/></svg>'
    assert _sanitiser().sanitise(svg) is None


def test_oversized_input_is_refused():
    padding = "<!-- " + ("x" * MAX_SVG_BYTES) + " -->"
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">{padding}'
        '<rect width="1" height="1"/></svg>'
    )
    assert _sanitiser().sanitise(svg) is None


def test_an_absolute_root_width_is_refused():
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" width="400px">'
        '<rect width="1" height="1"/></svg>'
    )
    assert _sanitiser().sanitise(svg) is None


def test_a_non_svg_root_is_refused():
    svg = '<rect xmlns="http://www.w3.org/2000/svg" width="1"/>'
    assert _sanitiser().sanitise(svg) is None


def test_an_unlisted_element_is_refused():
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">'
        '<image href="x.png"/></svg>'
    )
    assert _sanitiser().sanitise(svg) is None
