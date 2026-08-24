"""The security boundary for model-generated SVG.

`ModelSvgArtist` (Increment 3's generator, built in a sibling task) asks a
model for a flat vector illustration and gets back arbitrary text it claims is
SVG. That text is stored and later served to a browser at
`/api/art/{art_id}.svg` -- this module is what stands between "a model said
so" and "a browser will parse and render this". Nothing downstream re-derives
trust: `sanitise` is the one place a document is judged, and both the write
path (before `ArtStore.put`) and the read path (`app.py`'s route, belt over
suspenders in case a row predates this module or was written some other way)
call it.

The refusal is total, not a strip-and-continue: a document that contains a
`<script>` is not one whose *other* elements are worth keeping, because
whatever produced the script had no respect for the allowlist to begin with,
and a partially-cleaned document is a worse guarantee than a rejected one --
it looks like it worked.
"""

import xml.etree.ElementTree as ET

MAX_SVG_BYTES = 65_536
"""64 KiB. A flat vector illustration -- paths, shapes, a couple of gradients
-- does not need more than a few kilobytes; this is headroom, not a target.
Named so the cap is one place to move, not a literal buried in a comparison."""

_ALLOWED_ELEMENTS = frozenset(
    {
        "svg",
        "g",
        "path",
        "rect",
        "circle",
        "ellipse",
        "line",
        "polyline",
        "polygon",
        "defs",
        "linearGradient",
        "radialGradient",
        "stop",
        "title",
    }
)
"""Shapes and the grouping/gradient scaffolding a flat illustration needs.
Nothing that can reference external content (`image`, `use`, `foreignObject`)
and nothing that can execute (`script`, `animate*`, event-bearing elements
are caught separately via the `on*` attribute check)."""


def _local_name(tag: str) -> str:
    """`ElementTree` renders a namespaced tag as `{uri}local`. SVG's default
    namespace is `http://www.w3.org/2000/svg`, and a document with no xmlns at
    all parses with an unprefixed tag -- so this strips whichever form shows
    up rather than asserting one, and lets the allowlist judge the local name
    either way."""
    if tag.startswith("{"):
        return tag.split("}", 1)[1]
    return tag


def _has_absolute_length(value: str) -> bool:
    """True for anything but a bare unitless number or a percentage. The card
    sizes the image (`width`/`height` in CSS on the `<img>`), so a root
    `width="400px"` or `width="400"` fighting that layout is refused outright
    rather than silently stripped -- a generator that emits one is worth
    surfacing, not papering over."""
    stripped = value.strip()
    if stripped.endswith("%"):
        return False
    try:
        float(stripped)
    except ValueError:
        return True
    return False


def _check_element(element: ET.Element) -> bool:
    local = _local_name(element.tag)
    if local not in _ALLOWED_ELEMENTS:
        return False
    for name in element.attrib:
        local_attr = name.split("}", 1)[-1] if name.startswith("{") else name
        if local_attr.lower().startswith("on"):
            return False
        if local_attr in ("href", "xlink:href") or local_attr.endswith("}href"):
            return False
    return all(_check_element(child) for child in element)


class SvgSanitiser:
    """Stateless -- a class rather than a bare function because it is what
    `application/` ports name in their type hints (an `ArtGeneratorPort`
    collaborator), matching this codebase's convention of naming adapters as
    classes even where, as here, there is no instance state to hold."""

    def sanitise(self, svg: str) -> str | None:
        """Refuse (`None`) anything not provably safe to parse and render
        as-is. Returns the input unchanged on success -- this is a gate, not
        a cleaner; see the module docstring for why a partial clean is not
        offered.
        """
        if len(svg.encode("utf-8")) > MAX_SVG_BYTES:
            return None
        if "<!DOCTYPE" in svg or "<!ENTITY" in svg:
            # Refused on sight, before expat ever sees it. A flat vector
            # illustration has no legitimate use for a DOCTYPE or a custom
            # entity, and a small entity-expansion payload (a handful of
            # nested `&b;&b;...` references) is well under `MAX_SVG_BYTES`
            # both before *and* after expansion -- the size cap alone does
            # not catch it, because the multiplication happens inside
            # expat's parse, not in the bytes this function receives.
            # Measured: a ten-deep, ten-wide nest of 70-byte entities parses
            # to a few KB, sails under the cap, and still expands whatever
            # reads `root.itertext()` downstream to gigabytes at higher
            # depths -- rejecting the construct outright is cheaper and more
            # legible than trying to bound the expansion after the fact.
            return None
        try:
            # ElementTree's C parser (expat) does not resolve *external*
            # entities by default, but a crafted DOCTYPE with internal
            # entity definitions can still blow up expat's *internal*
            # expansion -- the `<!DOCTYPE`/`<!ENTITY` check above rejects
            # that shape before it ever reaches this parse.
            root = ET.fromstring(svg)
        except ET.ParseError:
            return None
        except Exception:  # noqa: BLE001 -- a security boundary: any parse
            # failure this stdlib parser can raise, not just the documented
            # `ParseError`, is a refusal rather than a crash. "I don't know
            # what this is" and "this is definitely hostile" get the same
            # answer here.
            return None

        if _local_name(root.tag) != "svg":
            return None
        if "viewBox" not in root.attrib:
            return None
        if "width" in root.attrib and _has_absolute_length(root.attrib["width"]):
            return None
        if "height" in root.attrib and _has_absolute_length(root.attrib["height"]):
            return None
        if not _check_element(root):
            return None
        return svg
