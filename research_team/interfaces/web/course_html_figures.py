"""SVG figure rendering and chart generation for course HTML exports.

Extracted from `course_html.py` to keep the page layout and presentation logic
focused on document composition while isolating the visual figure calculations,
geometric bounds, coordinate layouts, and SVG markup generators.
"""

from collections.abc import Sequence
from datetime import datetime
from typing import Any

from research_team.application.knowledge.graph_export import (
    ExportGraph,
    ExportNode,
    build_export,
)
from research_team.application.knowledge.timeline_read import TimelineBand
from research_team.interfaces.web.graph_html import color_for_type

#: How many nodes a lesson figure draws. A `graph` component is one entity's
#: neighbourhood, not an explorer; a dense neighbourhood without a cap is an
#: unreadable figure in the HTML export and a multi-second export run. The
#: honest outcome is a truncated figure that says so, rather than a page of
#: overlapping dots. `build_export` carries the flag; `_svg_graph` prints it.
MAX_FIGURE_NODES = 60

#: How many bands a `timeline` figure draws, for `MAX_FIGURE_NODES`' reason.
#: Bounded from above so an unbounded query (`after: 1900`, say) does not
#: turn a single lesson into thousands of bars; 40 is about two screens of
#: fixed-height figure inside a lesson.
MAX_FIGURE_BANDS = 40

_ESCAPE = {"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;"}


def esc(value: object) -> str:
    """HTML-escape anything, including the `None` a missing YAML field is."""
    return "".join(_ESCAPE.get(ch, ch) for ch in str("" if value is None else value))


_esc = esc


def compute_graph_bounds(
    nodes: Sequence[ExportNode], pad: float = 90.0
) -> tuple[float, float, float, float]:
    """Calculate the (min_x, min_y, width, height) bounding box for nodes."""
    xs = [n.x for n in nodes]
    ys = [n.y for n in nodes]
    min_x, max_x = min(xs) - pad, max(xs) + pad
    min_y, max_y = min(ys) - pad, max(ys) + pad
    # `or 1`: a single node, or several at one point, spans zero -- and a
    # zero-width viewBox renders as nothing at all, which reads as a broken
    # export rather than as a small graph. The same guard `graph_html`'s
    # `fit` makes, for the same reason.
    width = (max_x - min_x) or 1.0
    height = (max_y - min_y) or 1.0
    return min_x, min_y, width, height


def render_graph_edge(
    x1: float, y1: float, x2: float, y2: float, inferred: bool = False
) -> str:
    """A line element connecting two node coordinates in SVG."""
    dash = ' stroke-dasharray="6 6"' if inferred else ""
    return (
        f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}"'
        f' stroke="var(--edge)" stroke-width="2"{dash}></line>'
    )


def render_graph_edges(edges: Sequence[Any], at: dict[str, tuple[float, float]]) -> list[str]:
    """Lines for each relationship whose endpoints are present in the layout."""
    rendered = []
    for rel in edges:
        a, b = at.get(rel.source_id), at.get(rel.target_id)
        if a is None or b is None:
            continue
        rendered.append(render_graph_edge(a[0], a[1], b[0], b[1], rel.inferred))
    return rendered


def render_graph_node(node: ExportNode) -> str:
    """A single node mark: circle, centered label, and tooltip title."""
    color = color_for_type(node.entity_type)
    # Hollow means synthesised rather than extracted, exactly as
    # `graph_html` draws it -- a class node that drew like an extracted
    # entity would assert a document said something no document said.
    fill = "none" if node.inferred else color
    label = node.name if len(node.name) <= 28 else node.name[:27] + "…"
    return (
        f'<g><circle cx="{node.x:.1f}" cy="{node.y:.1f}" r="9" fill="{fill}"'
        f' stroke="{color}" stroke-width="3"></circle>'
        f'<text x="{node.x:.1f}" y="{node.y + 30:.1f}" text-anchor="middle"'
        f' font-size="20" fill="var(--fg)">{_esc(label)}</text>'
        f"<title>{_esc(node.name)} ({_esc(node.entity_type)})</title></g>"
    )


def render_graph_nodes(nodes: Sequence[ExportNode]) -> list[str]:
    """Circle and label marks for each node in layout."""
    return [render_graph_node(node) for node in nodes]


def render_graph_svg(graph: ExportGraph) -> str:
    """A neighbourhood, drawn from `compute_layout`'s coordinates.

    No JavaScript: the positions are decided on the server, so the figure is
    markup. That is what makes it print, survive a mail client's HTML
    sanitiser, and keep its labels as text a reader can select and a browser
    can find with ctrl-F.
    """
    nodes = graph.nodes
    if not nodes:
        return '<p class="absent">Nothing to draw.</p>'
    min_x, min_y, width, height = compute_graph_bounds(nodes)
    at = {n.entity_id: (n.x, n.y) for n in nodes}

    edges = render_graph_edges(graph.edges, at)
    marks = render_graph_nodes(nodes)

    note = (
        '<p class="quiet">Truncated: part of a larger neighbourhood, not all of it.</p>'
        if graph.truncated
        else ""
    )
    return (
        '<div class="figure"><svg role="img" '
        f'aria-label="{_esc(graph.title)} neighbourhood" '
        f'viewBox="{min_x:.1f} {min_y:.1f} {width:.1f} {height:.1f}" '
        'preserveAspectRatio="xMidYMid meet">'
        f"{''.join(edges)}{''.join(marks)}</svg></div>{note}"
    )


def parse_instant(value: str | None) -> float | None:
    """An ISO instant as a sortable number, or `None` for an open end.

    Swallows a parse failure into `None` rather than raising: the band came
    from a projection over model-extracted dates, and an export that died on
    one malformed instant would lose a whole course to a single bad date.
    The band still renders -- with that end open, which is the honest reading
    of "we do not know where this edge is".
    """
    if not value:
        return None
    try:
        return datetime.fromisoformat(value).timestamp()
    except (ValueError, OSError, OverflowError):
        return None


def compute_timeline_bounds(
    bands: Sequence[TimelineBand],
) -> tuple[float, float, float] | None:
    """Return (low, high, span) across all bands, or None if no drawable dates."""
    points: list[float] = []
    for band in bands:
        for value in (band.start, band.end):
            moment = parse_instant(value)
            if moment is not None:
                points.append(moment)
    if not points:
        return None
    low, high = min(points), max(points)
    span = (high - low) or 1.0
    return low, high, span


def render_timeline_band(
    band: TimelineBand,
    index: int,
    low: float,
    span: float,
    left: float = 260.0,
    inner: float = 700.0,
    row: float = 34.0,
) -> str:
    """Render a single timeline band row with label, bar rect, title, and extent."""
    start = parse_instant(band.start)
    end = parse_instant(band.end)
    x1 = left if start is None else left + (start - low) / span * inner
    x2 = left + inner if end is None else left + (end - low) / span * inner
    # A point-in-time band (a day-precision date, or one whose start and
    # end coincide) would otherwise be a zero-width rectangle, which
    # draws nothing. Three pixels is a tick, and reads as an instant.
    x2 = max(x2, x1 + 3.0)
    y = 8 + index * row
    color = color_for_type(band.entity_type)
    faint = ' opacity="0.55"' if band.uncertainty not in ("EXACT", "") else ""
    label = band.name if len(band.name) <= 30 else band.name[:29] + "…"
    return (
        f'<text x="{left - 12:.0f}" y="{y + 15:.0f}" text-anchor="end" font-size="15"'
        f' fill="var(--fg)">{_esc(label)}</text>'
        f'<rect x="{x1:.1f}" y="{y:.0f}" width="{x2 - x1:.1f}" height="18" rx="4"'
        f' fill="{color}"{faint}><title>{_esc(band.name)} — {_esc(band.extent)}'
        f" ({_esc(band.uncertainty.lower())})</title></rect>"
        f'<text x="{x2 + 8:.1f}" y="{y + 14:.0f}" font-size="13"'
        f' fill="var(--fg-dim)">{_esc(band.extent)}</text>'
    )


def render_timeline_bands(
    bands: Sequence[TimelineBand],
    low: float,
    span: float,
    left: float = 260.0,
    inner: float = 700.0,
    row: float = 34.0,
) -> list[str]:
    """Render all timeline band rows."""
    return [
        render_timeline_band(band, index, low, span, left=left, inner=inner, row=row)
        for index, band in enumerate(bands)
    ]


def render_timeline_svg(bands: Sequence[TimelineBand], undated: int, truncated: bool) -> str:
    """Dated entities on a shared axis, as bars.

    Open ends run to the edge of the drawing rather than being clamped to the
    axis minimum, which is what `TimelineBand.start`'s docstring asks for: a
    `BEFORE` marker is a positive claim about an unbounded earlier time, and
    a bar that started at the leftmost dated thing would be a claim the
    extraction never made.
    """
    bounds = compute_timeline_bounds(bands)
    if bounds is None:
        return '<p class="absent">These bands carry no drawable dates.</p>'
    low, _high, span = bounds
    row = 34.0
    height = row * len(bands) + 30

    rows = render_timeline_bands(bands, low, span, row=row)

    notes = []
    if undated:
        notes.append(f"{undated} dated nothing, so they are not drawn.")
    if truncated:
        notes.append("Truncated: more bands fell in this window than are drawn.")
    tail = f'<p class="quiet">{_esc(" ".join(notes))}</p>' if notes else ""
    return (
        '<div class="figure"><svg role="img" aria-label="Timeline" '
        f'viewBox="0 0 1060 {height:.0f}" preserveAspectRatio="xMidYMid meet">'
        f"{''.join(rows)}</svg></div>{tail}"
    )


def figure_graph(
    root: Any, entities: Sequence[Any], relationships: Sequence[Any]
) -> ExportGraph:
    """A neighbourhood laid out for a lesson figure.

    `build_export` does the capping, the orphan-edge drop and the `truncated`
    flag; all this adds is the root, which `Neighborhood` deliberately does
    not include in `entities` -- a figure that dropped the entity it is named
    after would be a drawing of everything around a hole. The same correction
    `export_graph` makes for `scope=entity`.
    """
    return build_export(
        (root, *entities),
        relationships,
        title=root.name,
        scope="lesson",
        limit=MAX_FIGURE_NODES,
    )


# Backward-compatible aliases
_svg_graph = render_graph_svg
_svg_timeline = render_timeline_svg
_instant = parse_instant

__all__ = [
    "MAX_FIGURE_BANDS",
    "MAX_FIGURE_NODES",
    "_instant",
    "_svg_graph",
    "_svg_timeline",
    "compute_graph_bounds",
    "compute_timeline_bounds",
    "esc",
    "figure_graph",
    "parse_instant",
    "render_graph_edge",
    "render_graph_edges",
    "render_graph_node",
    "render_graph_nodes",
    "render_graph_svg",
    "render_timeline_band",
    "render_timeline_bands",
    "render_timeline_svg",
]
