"""Placeholder art for the course catalog.

Increment 3 replaces this with a searchable art library plus a generator; the
`ArtPort` this implements is what lets that swap change nothing above it. What
this module owes the port in the meantime is not realism -- it is a catalog
that is actually browsable: a reader who has seen forty grey rectangles cannot
tell one card from the next, and a scattering of the SAME grey rectangle is
worse, because it reads as broken rather than as unfinished.

The art is a small inline SVG, embedded as a `data:` URI so no image ever
touches the network or the filesystem. Every visual choice below is derived
from `sha256(slug)` rather than `random`, `hash()` or the clock: `hash()` is
salted per Python process (stable within one server, different after every
restart), and the clock or `random` would make a card's art depend on when or
how many times it was requested. `sha256` gives the same bytes everywhere,
forever, for the same slug -- which is the whole requirement.
"""

from hashlib import sha256
from urllib.parse import quote

from research_team.domain.course_catalog import ArtRef, CategoryKey

# One palette per key the default grouper (type_plurality_grouper.CATEGORY_LABELS)
# actually emits, so a category page reads as one family rather than a
# grab-bag. This table is checked against that one, in
# test_every_category_the_default_grouper_emits_has_its_own_palette --
# nothing else keeps the two in agreement, because they live in different
# modules and neither imports the other. An earlier draft had "place" here
# instead of "location" (a guess, not a read of the grouper), which meant a
# key nothing emits had a palette while a key the grouper does emit fell
# through to grey; the test exists so that class of drift fails loudly.
#
# "unclassified" is deliberately NOT in this table -- see the comment on
# `_UNCATEGORISED_BASE` for why grey is the right rendering for it, not an
# oversight the fallback happens to paper over.
_PALETTES: dict[str, tuple[str, str]] = {
    "work": ("#2b4c7e", "#f2a541"),
    "person": ("#5b3a63", "#e07a5f"),
    "location": ("#2f5d50", "#8fbf9f"),
    "organization": ("#4a5568", "#63b3ed"),
    "concept": ("#3b3b58", "#c9a0dc"),
    "event": ("#7a2e2e", "#e8c07d"),
    "category": ("#5c4a1e", "#d9b45e"),
}

_UNCATEGORISED_BASE = ("#3a3a3a", "#9a9a9a")
"""Palette for anything not in `_PALETTES` -- both a category this table has
never heard of (the ontology-derived vocabulary `CategoryGrouper`'s docstring
describes as still growing), and the grouper's own `unclassified` key.

For `unclassified` specifically, this is a choice and not a fallback catching
a gap: grey communicating "we could not classify this" is honest, where
inventing a confident-looking colour for it would not be. It reaches this
same code path as any other unrecognised key rather than a second grey
mechanism, so there is exactly one place that produces grey and one place to
change if that choice is ever revisited.

Desaturated relative to every hand-picked entry in `_PALETTES`, so an
unrecognised category never silently impersonates a real one, and still
tinted by the category string below it, so two unknown categories do not
collapse onto one look."""


def _palette_for(category: CategoryKey) -> tuple[str, str]:
    """A base/accent pair for any category string, known or not.

    Total over `str`, because `CategoryGrouper.group` is documented as total
    over areas and a category this table has not enumerated must still
    produce a card rather than raise. An unknown category is tinted by
    hashing the category string itself, so "unknown" is not one look -- two
    different unrecognised categories still read as different families.
    """
    if category in _PALETTES:
        return _PALETTES[category]
    digest = sha256(category.encode("utf-8")).digest()
    hue = digest[0] / 255
    return _UNCATEGORISED_BASE[0], _hsl(hue, 0.35, 0.55)


def _hsl(hue: float, saturation: float, lightness: float) -> str:
    """`hsl()` rather than computing RGB by hand -- SVG accepts it directly,
    and a hue in [0, 1) is exactly what a digest byte gives for free."""
    return f"hsl({round(hue * 360)}, {round(saturation * 100)}%, {round(lightness * 100)}%)"


def _svg_for(slug: str, category: CategoryKey) -> str:
    """The SVG markup itself.

    A 64x64 tile: a flat background in the category's base colour, and one
    rotated square in the accent colour whose position, size and rotation
    come from the slug's digest. A single shape rather than a scene -- this
    has to stay a few hundred bytes because it is embedded per card in a JSON
    payload and a catalog page can hold dozens of cards -- but one shape at a
    slug-derived angle and offset is already enough to tell two cards apart
    at a glance, which is the actual requirement, not visual richness.
    """
    digest = sha256(slug.encode("utf-8")).digest()
    base, accent = _palette_for(category)
    cx = 16 + (digest[1] % 33)  # 16..48, kept off the tile's edge
    cy = 16 + (digest[2] % 33)
    size = 14 + (digest[3] % 20)  # 14..33
    rotation = digest[4] % 360
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">'
        f'<rect width="64" height="64" fill="{base}"/>'
        f'<rect x="{cx - size / 2}" y="{cy - size / 2}" width="{size}" height="{size}" '
        f'fill="{accent}" transform="rotate({rotation} {cx} {cy})"/>'
        "</svg>"
    )


class SeededArtProvider:
    """The one production `ArtPort` adapter for the placeholder increment."""

    def for_candidate(self, slug: str, category: CategoryKey) -> ArtRef:
        svg = _svg_for(slug, category)
        # `quote` rather than base64: base64 inflates an already-tiny SVG by a
        # third, and plain percent-encoded text is what every browser expects
        # for an `image/svg+xml` data URI. `safe=""` percent-encodes `/` and
        # `#` too, which matters here because the SVG uses neither but a
        # future shape (an arc, an id-referenced gradient) might.
        encoded = quote(svg, safe="")
        url = f"data:image/svg+xml,{encoded}"
        return ArtRef(url=url, alt=f"Illustration for {slug}")
