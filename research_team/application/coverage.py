"""Tyler's objective grid, UbD's Code columns and ADDIE's blueprint, once.

Three traditions with no contact between them each invented a two-dimensional
grid and each made it their primary diagnostic. That is the strongest
convergence the comparison found, and it is why this module exists: with typed
axes, every coverage, orphan and density check over a matrix is one
implementation rather than three that drift.

**The axes differ in kind, not just in label, and that is the whole
difficulty.** Tyler's grid is *intrinsic* -- behaviour x content are two
attributes of the same objective, so a cell holds the objectives that have
that pair. UbD's Code columns and ADDIE's blueprint are *relational* --
intent x evidence, objective x module are two different artifact types joined
by an edge, so a cell holds the links. `AttributeAxis` and `ArtifactAxis` are
those two shapes, a matrix must be built from a matching pair, and
`matrix_density` genuinely branches on which it got. Flattening them into one
axis type with optional fields would make the module look tidier and would
make every diagnostic below ambiguous about what it had just found.

**Axes are declared, never derived.** A grid whose rows are the behaviours
somebody happened to write has no empty rows by construction, which makes the
empty-row diagnostic vacuous exactly where it would have been useful. So
`matrix_from_attributes` takes the axis values and rejects a record that falls
outside them, and `matrix_from_links` takes the full row and column id sets
rather than reading them off the links.

**Findings, not scores.** Every diagnostic returns entries a person can act
on, and an empty list is a pass. Nothing here calls a model; all of it is a
scan over data the stage already produced.
"""

from collections.abc import Iterable, Sequence
from typing import Annotated, Literal

from pydantic import BaseModel, Field, model_validator

from research_team.application.findings import Finding, FindingSeverity
from research_team.domain.workflow import ArtifactType

__all__ = [
    "ArtifactAxis",
    "AttributeAxis",
    "Axis",
    "CoverageMatrix",
    "MatrixCell",
    "matrix_density",
    "matrix_density_check",
    "matrix_from_attributes",
    "matrix_from_links",
    "render_matrix",
]


class AttributeAxis(BaseModel, frozen=True):
    """Two of these make an intrinsic matrix: one artifact type, two of its
    attributes. Tyler's behaviour x content and nothing else so far."""

    kind: Literal["attribute"] = "attribute"
    artifact_type: ArtifactType
    attribute_path: str


class ArtifactAxis(BaseModel, frozen=True):
    """Two of these make a relational matrix: two artifact types joined by an
    edge. `subtype` is what lets UbD demand a *performance task* rather than
    any evidence at all, which is the difference between the check biting and
    the check passing on a quiz."""

    kind: Literal["artifact"] = "artifact"
    artifact_type: ArtifactType
    subtype: str | None = None


Axis = Annotated[AttributeAxis | ArtifactAxis, Field(discriminator="kind")]

MatrixKind = Literal["intrinsic", "relational"]


class MatrixCell(BaseModel, frozen=True):
    """What occupies one position. Only non-empty cells are stored, so an
    absent cell and an empty one are the same thing and cannot disagree."""

    row: str
    column: str
    artifact_ids: tuple[str, ...] = ()


class CoverageMatrix(BaseModel, frozen=True):
    """A grid over two typed axes, with its rows and columns declared.

    Rows and columns are keys, not display text: an artifact id on a
    relational axis, an attribute value on an intrinsic one. The distinction
    matters at exactly one point -- a relational row key is something a
    finding can name as an affected artifact, and an intrinsic one is not.
    """

    matrix_id: str
    row_axis: Axis
    column_axis: Axis
    rows: tuple[str, ...] = ()
    columns: tuple[str, ...] = ()
    cells: tuple[MatrixCell, ...] = ()

    @model_validator(mode="after")
    def _coherent(self) -> "CoverageMatrix":
        if self.row_axis.kind != self.column_axis.kind:
            raise ValueError(
                f"matrix {self.matrix_id}: both axes must be of the same kind; "
                f"got {self.row_axis.kind} x {self.column_axis.kind}"
            )
        if (
            isinstance(self.row_axis, AttributeAxis)
            and isinstance(self.column_axis, AttributeAxis)
            and self.row_axis.artifact_type != self.column_axis.artifact_type
        ):
            raise ValueError(
                f"matrix {self.matrix_id}: an intrinsic matrix is two attributes "
                f"of one artifact type; got {self.row_axis.artifact_type} and "
                f"{self.column_axis.artifact_type}"
            )
        _reject_duplicates(self.matrix_id, "row", self.rows)
        _reject_duplicates(self.matrix_id, "column", self.columns)
        seen: set[tuple[str, str]] = set()
        for cell in self.cells:
            if cell.row not in self.rows:
                raise ValueError(f"matrix {self.matrix_id} has no row {cell.row!r}")
            if cell.column not in self.columns:
                raise ValueError(f"matrix {self.matrix_id} has no column {cell.column!r}")
            if (cell.row, cell.column) in seen:
                raise ValueError(
                    f"matrix {self.matrix_id}: cell "
                    f"({cell.row!r}, {cell.column!r}) is given twice"
                )
            seen.add((cell.row, cell.column))
        return self

    @property
    def kind(self) -> MatrixKind:
        return "intrinsic" if self.row_axis.kind == "attribute" else "relational"

    def occupancy(self) -> dict[tuple[str, str], tuple[str, ...]]:
        """Positions to their contents, non-empty cells only."""
        return {(c.row, c.column): c.artifact_ids for c in self.cells if c.artifact_ids}


def _reject_duplicates(matrix_id: str, axis: str, keys: Sequence[str]) -> None:
    for index, key in enumerate(keys):
        if key in keys[:index]:
            raise ValueError(f"matrix {matrix_id}: {axis} {key!r} is declared twice")


def matrix_from_links(
    matrix_id: str,
    *,
    row_axis: ArtifactAxis,
    column_axis: ArtifactAxis,
    rows: Sequence[str],
    columns: Sequence[str],
    links: Iterable[tuple[str, str]],
) -> CoverageMatrix:
    """The relational build: two id sets and the edges between them.

    `rows` and `columns` are the *full* sets, which is the only reason an
    empty row or column is detectable at all -- read off the links, both would
    be empty by definition. Repeated links collapse into one cell entry, so a
    duplicated edge inflates nothing.

    A cell holds the id of the artifact on the other axis, because a link here
    is not itself an artifact with an id of its own: the fact worth recording
    is which evidence serves which intent.
    """
    cells: dict[tuple[str, str], list[str]] = {}
    for row, column in links:
        if row not in rows:
            raise ValueError(f"matrix {matrix_id} has no row {row!r}")
        if column not in columns:
            raise ValueError(f"matrix {matrix_id} has no column {column!r}")
        occupants = cells.setdefault((row, column), [])
        if column not in occupants:
            occupants.append(column)
    return CoverageMatrix(
        matrix_id=matrix_id,
        row_axis=row_axis,
        column_axis=column_axis,
        rows=tuple(rows),
        columns=tuple(columns),
        cells=tuple(
            MatrixCell(row=row, column=column, artifact_ids=tuple(occupants))
            for (row, column), occupants in cells.items()
        ),
    )


def matrix_from_attributes(
    matrix_id: str,
    *,
    row_axis: AttributeAxis,
    column_axis: AttributeAxis,
    rows: Sequence[str],
    columns: Sequence[str],
    records: Iterable[tuple[str, str, str]],
) -> CoverageMatrix:
    """The intrinsic build: `(artifact_id, row_value, column_value)` per artifact.

    A value outside the declared axes raises rather than growing the axis.
    Tyler's grid is an authored instrument -- the behaviour and content axes
    are the course's own vocabulary -- and an objective whose behaviour is not
    on the axis is a defect in the objective or in the axis, either of which a
    person needs to decide. Silently widening the grid decides it for them and
    hides both.
    """
    cells: dict[tuple[str, str], list[str]] = {}
    for artifact_id, row, column in records:
        if row not in rows:
            raise ValueError(f"matrix {matrix_id} has no row {row!r}")
        if column not in columns:
            raise ValueError(f"matrix {matrix_id} has no column {column!r}")
        occupants = cells.setdefault((row, column), [])
        if artifact_id not in occupants:
            occupants.append(artifact_id)
    return CoverageMatrix(
        matrix_id=matrix_id,
        row_axis=row_axis,
        column_axis=column_axis,
        rows=tuple(rows),
        columns=tuple(columns),
        cells=tuple(
            MatrixCell(row=row, column=column, artifact_ids=tuple(occupants))
            for (row, column), occupants in cells.items()
        ),
    )


def matrix_density(
    matrix: CoverageMatrix,
    *,
    no_empty_rows: bool = False,
    no_empty_columns: bool = False,
    max_cell_density: float | None = None,
    severity: FindingSeverity = "blocking",
) -> list[Finding]:
    """Every grid diagnostic the three traditions share, over one matrix.

    **What applies to which kind.** Empty rows mean the same thing in both:
    something on the row axis that nothing reaches. Empty columns do not.

    - *Relational*, `no_empty_rows`: an uncovered intent. This is exactly
      `coverage(from=row_axis, to=column_axis, min=1)` -- not an approximation
      of it, and `test_empty_rows_agree_with_coverage` is what holds that
      true.
    - *Relational*, `no_empty_columns`: an orphan. Exactly
      `orphan(type=column_axis, must_link_to=row_axis)`.
    - *Intrinsic*, `no_empty_rows`: a declared behaviour that no objective was
      written against. It names no artifact id, because the finding is that
      there is no artifact.
    - *Intrinsic*, `no_empty_columns`: Tyler's content area with no behaviour
      attached. **This has no relational analogue** and it is deliberately not
      called an orphan: an orphan is an artifact that exists and connects to
      nothing, and an empty content column is a region of the grid where
      nothing was written at all. They read the same on a diagram and mean
      opposite things to a reviewer.
    - Either kind, `max_cell_density`: Tyler's objective inflation. A grid
      approaching full is not thorough, it is a course claiming to teach every
      behaviour about every topic, and the density number is the cheapest
      signal of it available.

    Every flag defaults off, so a preset gets the diagnostics it asked for and
    no others -- a check that reports things nobody bound it for teaches
    reviewers to skim findings.
    """
    if max_cell_density is not None and not 0.0 <= max_cell_density <= 1.0:
        raise ValueError(f"max_cell_density must be between 0 and 1; got {max_cell_density}")

    occupancy = matrix.occupancy()
    findings: list[Finding] = []

    if no_empty_rows:
        occupied = {row for row, _ in occupancy}
        findings += [
            _absence_finding(matrix, "row", key, severity)
            for key in matrix.rows
            if key not in occupied
        ]
    if no_empty_columns:
        occupied = {column for _, column in occupancy}
        findings += [
            _absence_finding(matrix, "column", key, severity)
            for key in matrix.columns
            if key not in occupied
        ]

    positions = len(matrix.rows) * len(matrix.columns)
    if max_cell_density is not None and positions:
        density = len(occupancy) / positions
        if density > max_cell_density:
            findings.append(
                Finding(
                    check="matrix_density",
                    severity=severity,
                    message=(
                        f"{matrix.matrix_id} is {density:.2f} dense against a "
                        f"ceiling of {max_cell_density:.2f} ({len(occupancy)} of "
                        f"{positions} cells occupied). A grid this full usually "
                        f"means the intents are inflated rather than the coverage "
                        f"thorough."
                    ),
                    suggested_edit=(
                        "Cut or merge intents until the grid is sparse enough to "
                        "show where the course actually concentrates."
                    ),
                )
            )
    return findings


def _absence_finding(
    matrix: CoverageMatrix, axis: Literal["row", "column"], key: str, severity: FindingSeverity
) -> Finding:
    """One empty row or column, said in the vocabulary of the matrix's kind."""
    if matrix.kind == "relational":
        if axis == "row":
            message = (
                f"{matrix.matrix_id}: {key} is uncovered -- no "
                f"{_axis_name(matrix.column_axis)} is linked to it."
            )
            edit = f"Add a {_axis_name(matrix.column_axis)} serving {key}, or remove {key}."
        else:
            message = (
                f"{matrix.matrix_id}: {key} is an orphan -- it serves no "
                f"{_axis_name(matrix.row_axis)}."
            )
            edit = f"Link {key} to a {_axis_name(matrix.row_axis)}, or drop it."
        return Finding(
            check="matrix_density",
            severity=severity,
            message=message,
            cites=(key,),
            suggested_edit=edit,
        )

    other = matrix.column_axis if axis == "row" else matrix.row_axis
    mine = matrix.row_axis if axis == "row" else matrix.column_axis
    return Finding(
        check="matrix_density",
        severity=severity,
        message=(
            f"{matrix.matrix_id}: the {mine.attribute_path} {key!r} has no cells -- "
            f"no {mine.artifact_type.value} pairs it with any "
            f"{other.attribute_path}."
        ),
        suggested_edit=(
            f"Write a {mine.artifact_type.value} for {key!r}, or take it off the "
            f"{mine.attribute_path} axis if the course does not intend to cover it."
        ),
    )


def _axis_name(axis: Axis) -> str:
    if isinstance(axis, AttributeAxis):
        return axis.attribute_path
    if axis.subtype:
        return f"{axis.artifact_type.value} ({axis.subtype})"
    return axis.artifact_type.value


_PARAMS = frozenset({"matrix", "no_empty_rows", "no_empty_columns", "max_cell_density"})


def matrix_density_check(
    matrix: CoverageMatrix,
    params: dict[str, object],
    severity: FindingSeverity = "blocking",
) -> list[Finding]:
    """The registry adapter: a `Check.params` mapping applied to one matrix.

    `matrix` in the params names which matrix the binding is about, so a stage
    producing two of them runs the right diagnostics on each; being handed the
    wrong one raises rather than silently checking it, because a check that
    reports a clean matrix under another matrix's name is worse than no check.

    An unrecognised parameter also raises. The alternative -- ignoring it --
    produces a binding that looks bound, runs, and enforces nothing, and the
    presets already contain one such param (`min_contact_points` on the
    hybrid's `thread_x_thread`) that this signature does not implement. Better
    that it fails loudly at wiring time than passes quietly forever.
    """
    unknown = set(params) - _PARAMS
    if unknown:
        raise ValueError(f"matrix_density does not take {', '.join(sorted(unknown))}")
    named = params.get("matrix")
    if named is not None and named != matrix.matrix_id:
        raise ValueError(
            f"check is bound to matrix {named!r} but was given {matrix.matrix_id!r}"
        )
    ceiling = params.get("max_cell_density")
    return matrix_density(
        matrix,
        no_empty_rows=bool(params.get("no_empty_rows", False)),
        no_empty_columns=bool(params.get("no_empty_columns", False)),
        max_cell_density=float(ceiling) if ceiling is not None else None,  # type: ignore[arg-type]
        severity=severity,
    )


def render_matrix(matrix: CoverageMatrix, *, max_columns: int = 12) -> str:
    """The matrix as a markdown table, plus a legend naming every column.

    No UI work is needed for this and that was a finding rather than a
    convenience: the file viewer already renders markdown tables, so a matrix
    written as one is reviewable the moment it is written.

    **Wide matrices.** A blueprint with forty assessment items produces forty
    columns, and forty columns of full labels is not a table anyone reads.
    Three things handle it, in order of how much they cost the reader:

    1. *Columns are coded* `C1..Cn` in the header, with a legend below mapping
       each code to its key. This is what a paper assessment blueprint does,
       and it caps a header cell at three characters. Row labels are left
       whole, because there is one row-label column and many column-label
       cells -- the width pressure is entirely horizontal, so the asymmetry in
       the treatment is the asymmetry in the problem.
    2. *Beyond `max_columns`, the remainder collapses* into one `… (k more)`
       column, marked in a row when any collapsed column of that row is
       occupied. That constraint is the point: truncation may cost detail, but
       it must never turn an occupied row into an apparently empty one,
       because an empty row is the diagnostic the reader came for.
    3. *The legend lists every column*, truncated ones included, so nothing
       disappears from the document -- only from the grid.

    Transposition was the obvious fourth option and is not used. It only helps
    when exactly one axis is wide, and it silently swaps two diagnostics that
    are not symmetric here: an empty row and an empty column mean different
    things, and one of them has no relational analogue at all. A reader who
    has to check the orientation before reading the table is worse off than
    one reading a wide one.
    """
    if max_columns < 1:
        raise ValueError(f"max_columns must be at least 1; got {max_columns}")

    heading = (
        f"**{matrix.matrix_id}** — {_axis_name(matrix.row_axis)}"
        f" x {_axis_name(matrix.column_axis)}"
    )
    codes = {column: f"C{n}" for n, column in enumerate(matrix.columns, start=1)}
    shown = matrix.columns[:max_columns]
    hidden = matrix.columns[max_columns:]
    occupancy = matrix.occupancy()
    lines = [heading, ""]

    # A degenerate axis is itself a finding, and the legend below still names
    # what does exist -- which is the whole content of "every column is an
    # orphan" or "no evidence has been written yet". Replacing the document
    # with a sentence would drop exactly the list the reader needs.
    if not matrix.rows:
        lines.append("This matrix has no rows.")
    else:
        if not matrix.columns:
            lines += ["This matrix has no columns: every row below is empty.", ""]
        header = [_escape(_axis_name(matrix.row_axis)), *(codes[c] for c in shown)]
        if hidden:
            header.append(f"… ({len(hidden)} more)")
        lines += [_row(header), _row(["---"] * len(header))]
        for row in matrix.rows:
            cells = [_mark(occupancy.get((row, column), ())) for column in shown]
            if hidden:
                cells.append("x" if any((row, c) in occupancy for c in hidden) else "")
            lines.append(_row([_escape(row), *cells]))

    if not matrix.columns:
        return "\n".join(lines)

    lines += ["", "| Key | " + _escape(_axis_name(matrix.column_axis)) + " |", "| --- | --- |"]
    lines += [_row([codes[column], _escape(column)]) for column in matrix.columns]
    return "\n".join(lines)


def _row(cells: Sequence[str]) -> str:
    return "| " + " | ".join(cells) + " |"


def _mark(occupants: Sequence[str]) -> str:
    """`x` for one, `x(n)` for several. The count is worth showing because a
    cell with six items in a blueprint is over-assessed, and a bare `x` in
    every cell hides that as effectively as an empty grid hides a gap."""
    if not occupants:
        return ""
    return "x" if len(occupants) == 1 else f"x({len(occupants)})"


def _escape(text: str) -> str:
    """A pipe in a label would end the cell it is in and shift every cell after
    it, which turns one bad label into a table that misreports every row."""
    return text.replace("|", r"\|")
