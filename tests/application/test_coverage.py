"""The matrix, its two kinds, and the equivalence the whole design rests on.

The claim under test is not "matrix_density finds empty rows". It is that
`matrix_density` over a matrix and `coverage`/`orphan` over the links that
built it are *the same computation*. If that is only approximately true then
a preset that binds `matrix_density` is quietly running a different check from
one that binds `coverage`, and the collapse the research reported is a story
rather than a fact. Hence the property tests: the reference implementations
below are the naive link scans, written the obvious way, and the matrix must
agree with them for every matrix hypothesis can build.
"""

import pytest
from hypothesis import given
from hypothesis import strategies as st

from research_team.application.coverage import (
    ArtifactAxis,
    AttributeAxis,
    CoverageMatrix,
    MatrixCell,
    matrix_density,
    matrix_density_check,
    matrix_from_attributes,
    matrix_from_links,
    render_matrix,
)
from research_team.domain.workflow import ArtifactType

INTENT = ArtifactAxis(artifact_type=ArtifactType.INTENT)
EVIDENCE = ArtifactAxis(artifact_type=ArtifactType.EVIDENCE_SPEC, subtype="performance_task")
BEHAVIOUR = AttributeAxis(artifact_type=ArtifactType.INTENT, attribute_path="behaviour")
CONTENT = AttributeAxis(artifact_type=ArtifactType.INTENT, attribute_path="content")


def relational(links, rows=("i1", "i2"), columns=("e1", "e2")):
    return matrix_from_links(
        "intent_x_evidence",
        row_axis=INTENT,
        column_axis=EVIDENCE,
        rows=rows,
        columns=columns,
        links=links,
    )


def intrinsic(records, behaviours=("interprets", "applies"), contents=("energy", "cells")):
    return matrix_from_attributes(
        "behaviour_x_content",
        row_axis=BEHAVIOUR,
        column_axis=CONTENT,
        rows=behaviours,
        columns=contents,
        records=records,
    )


# --- shape -------------------------------------------------------------------


def test_a_relational_matrix_reports_its_kind():
    assert relational([("i1", "e1")]).kind == "relational"


def test_an_intrinsic_matrix_reports_its_kind():
    assert intrinsic([("o1", "interprets", "energy")]).kind == "intrinsic"


def test_axes_of_different_kinds_cannot_be_paired():
    with pytest.raises(ValueError, match="same kind"):
        CoverageMatrix(
            matrix_id="mixed",
            row_axis=INTENT,
            column_axis=CONTENT,
            rows=("i1",),
            columns=("energy",),
        )


def test_an_intrinsic_matrix_needs_both_axes_on_one_artifact_type():
    with pytest.raises(ValueError, match="one artifact type"):
        CoverageMatrix(
            matrix_id="crossed",
            row_axis=BEHAVIOUR,
            column_axis=AttributeAxis(
                artifact_type=ArtifactType.EXPERIENCE, attribute_path="content"
            ),
            rows=("interprets",),
            columns=("energy",),
        )


def test_a_cell_outside_the_declared_axes_is_rejected():
    with pytest.raises(ValueError, match="no column"):
        CoverageMatrix(
            matrix_id="m",
            row_axis=INTENT,
            column_axis=EVIDENCE,
            rows=("i1",),
            columns=("e1",),
            cells=(MatrixCell(row="i1", column="e9", artifact_ids=("x",)),),
        )


def test_two_cells_for_one_position_are_rejected():
    with pytest.raises(ValueError, match="twice"):
        CoverageMatrix(
            matrix_id="m",
            row_axis=INTENT,
            column_axis=EVIDENCE,
            rows=("i1",),
            columns=("e1",),
            cells=(
                MatrixCell(row="i1", column="e1", artifact_ids=("a",)),
                MatrixCell(row="i1", column="e1", artifact_ids=("b",)),
            ),
        )


def test_a_duplicated_axis_key_is_rejected():
    with pytest.raises(ValueError, match="twice"):
        relational([], rows=("i1", "i1"))


def test_an_intrinsic_axis_value_never_observed_still_becomes_a_row():
    # The whole point: an axis is declared, not derived. A behaviour nothing
    # was written against has to survive into the grid to be reportable.
    matrix = intrinsic([("o1", "interprets", "energy")])
    assert matrix.rows == ("interprets", "applies")


def test_a_record_off_the_declared_axes_is_rejected():
    with pytest.raises(ValueError, match="no row"):
        intrinsic([("o1", "evaluates", "energy")])


# --- diagnostics --------------------------------------------------------------


def test_a_full_matrix_yields_no_findings():
    matrix = relational([("i1", "e1"), ("i2", "e2")])
    assert matrix_density(matrix, no_empty_rows=True, no_empty_columns=True) == []


def test_an_empty_row_is_reported_with_the_row_as_the_affected_artifact():
    matrix = relational([("i1", "e1"), ("i1", "e2")])
    (finding,) = matrix_density(matrix, no_empty_rows=True)
    assert finding.check == "matrix_density"
    assert finding.affected_artifact_ids == ("i2",)
    assert finding.suggested_edit is not None


def test_an_empty_column_in_a_relational_matrix_reads_as_an_orphan():
    matrix = relational([("i1", "e1"), ("i2", "e1")])
    (finding,) = matrix_density(matrix, no_empty_columns=True)
    assert finding.affected_artifact_ids == ("e2",)
    assert "orphan" in finding.message


def test_an_empty_column_in_an_intrinsic_matrix_is_not_called_an_orphan():
    # L5: Tyler's "content area with no behaviour" has no relational analogue,
    # and naming it an orphan would invent one.
    matrix = intrinsic([("o1", "interprets", "energy"), ("o2", "applies", "energy")])
    (finding,) = matrix_density(matrix, no_empty_columns=True)
    assert "orphan" not in finding.message
    assert "cells" in finding.message


def test_an_intrinsic_empty_row_names_no_artifact_because_none_exists():
    matrix = intrinsic([("o1", "interprets", "energy"), ("o2", "interprets", "cells")])
    (finding,) = matrix_density(matrix, no_empty_rows=True)
    assert finding.affected_artifact_ids == ()
    assert "applies" in finding.message


def test_flags_left_off_report_nothing():
    matrix = relational([])
    assert matrix_density(matrix) == []


def test_a_fully_dense_grid_is_reported_as_inflation():
    matrix = relational([("i1", "e1"), ("i1", "e2"), ("i2", "e1"), ("i2", "e2")])
    (finding,) = matrix_density(matrix, max_cell_density=0.8)
    assert "1.00" in finding.message
    assert finding.affected_artifact_ids == ()


def test_density_at_the_ceiling_passes():
    matrix = relational([("i1", "e1"), ("i1", "e2"), ("i2", "e1")])
    assert matrix_density(matrix, max_cell_density=0.75) == []


def test_density_of_an_empty_matrix_is_zero_not_an_error():
    empty = CoverageMatrix(
        matrix_id="m", row_axis=INTENT, column_axis=EVIDENCE, rows=(), columns=()
    )
    assert matrix_density(empty, max_cell_density=0.5, no_empty_rows=True) == []


def test_severity_is_carried_onto_every_finding():
    matrix = relational([])
    findings = matrix_density(
        matrix, no_empty_rows=True, no_empty_columns=True, severity="advisory"
    )
    assert {f.severity for f in findings} == {"advisory"}


def test_max_cell_density_out_of_range_is_rejected():
    with pytest.raises(ValueError, match="max_cell_density"):
        matrix_density(relational([]), max_cell_density=1.5)


# --- the registry adapter ------------------------------------------------------


def test_the_adapter_reads_the_params_the_presets_actually_ship():
    matrix = relational([("i1", "e1")])
    findings = matrix_density_check(
        matrix, params={"matrix": "intent_x_evidence", "no_empty_rows": True}
    )
    assert [f.affected_artifact_ids for f in findings] == [("i2",)]


def test_the_adapter_refuses_a_matrix_it_was_not_pointed_at():
    with pytest.raises(ValueError, match="intent_x_experience"):
        matrix_density_check(relational([]), params={"matrix": "intent_x_experience"})


def test_the_adapter_rejects_an_unknown_parameter():
    # A silently ignored param is a check that claims to run and does not.
    with pytest.raises(ValueError, match="min_contact_points"):
        matrix_density_check(relational([]), params={"min_contact_points": 1})


# --- rendering -----------------------------------------------------------------


def test_a_narrow_matrix_renders_every_column():
    matrix = relational([("i1", "e1"), ("i2", "e2")])
    table = render_matrix(matrix)
    assert "| C1 | C2 |" in table
    assert "more)" not in table


def test_an_occupied_cell_is_marked_and_a_multiply_occupied_one_is_counted():
    matrix = CoverageMatrix(
        matrix_id="m",
        row_axis=INTENT,
        column_axis=EVIDENCE,
        rows=("i1",),
        columns=("e1", "e2"),
        cells=(MatrixCell(row="i1", column="e1", artifact_ids=("a", "b")),),
    )
    row = next(line for line in render_matrix(matrix).splitlines() if line.startswith("| i1"))
    assert row == "| i1 | x(2) |  |"


def test_the_legend_names_every_column_including_truncated_ones():
    columns = tuple(f"e{n}" for n in range(20))
    matrix = relational([("i1", "e19")], columns=columns)
    table = render_matrix(matrix, max_columns=4)
    assert "| C20 | e19 |" in table
    assert "… (16 more)" in table


def test_truncation_never_makes_an_occupied_row_look_empty():
    columns = tuple(f"e{n}" for n in range(20))
    matrix = relational([("i1", "e19")], columns=columns)
    table = render_matrix(matrix, max_columns=4)
    row = next(line for line in table.splitlines() if line.startswith("| i1"))
    assert row.rstrip().endswith("x |")


def test_a_pipe_in_a_label_cannot_break_the_table():
    matrix = relational([("a|b", "e1")], rows=("a|b",))
    assert r"| a\|b |" in render_matrix(matrix)


def test_an_empty_matrix_renders_a_sentence_rather_than_an_empty_table():
    empty = CoverageMatrix(
        matrix_id="m", row_axis=INTENT, column_axis=EVIDENCE, rows=(), columns=()
    )
    assert "no rows" in render_matrix(empty)


def test_max_columns_below_one_is_rejected():
    with pytest.raises(ValueError, match="max_columns"):
        render_matrix(relational([]), max_columns=0)


# --- the equivalence ------------------------------------------------------------


def reference_coverage(rows, links):
    """`coverage(from=row_type, to=column_type, min=1)`, written the naive way."""
    return {row for row in rows if not any(link[0] == row for link in links)}


def reference_orphan(columns, links):
    """`orphan(type=column_type, must_link_to=row_type)`, written the naive way."""
    return {column for column in columns if not any(link[1] == column for link in links)}


def _affected(findings):
    return {ids[0] for finding in findings for ids in [finding.affected_artifact_ids] if ids}


ids = st.lists(
    st.text("abcdefg", min_size=1, max_size=3), min_size=0, max_size=6, unique=True
).map(tuple)


@st.composite
def matrices(draw):
    rows = draw(ids)
    columns = draw(ids.map(lambda cs: tuple(f"c{c}" for c in cs)))
    links = draw(
        st.lists(
            st.tuples(st.sampled_from(rows or ("",)), st.sampled_from(columns or ("",))),
            max_size=12,
        )
    )
    links = [link for link in links if link[0] in rows and link[1] in columns]
    return relational(links, rows=rows, columns=columns), rows, columns, links


@given(matrices())
def test_empty_rows_agree_with_coverage(case):
    matrix, rows, _columns, links = case
    findings = matrix_density(matrix, no_empty_rows=True)
    assert _affected(findings) == reference_coverage(rows, links)


@given(matrices())
def test_empty_columns_agree_with_orphan(case):
    matrix, _rows, columns, links = case
    findings = matrix_density(matrix, no_empty_columns=True)
    assert _affected(findings) == reference_orphan(columns, links)


@given(matrices())
def test_the_two_diagnostics_do_not_interfere(case):
    matrix, _rows, _columns, _links = case
    both = matrix_density(matrix, no_empty_rows=True, no_empty_columns=True)
    separate = matrix_density(matrix, no_empty_rows=True) + matrix_density(
        matrix, no_empty_columns=True
    )
    assert both == separate


@given(matrices())
def test_a_rendered_row_is_blank_exactly_when_the_row_is_empty(case):
    matrix, rows, _columns, links = case
    if not matrix.rows or not matrix.columns:
        return
    table = render_matrix(matrix, max_columns=3)
    empty = reference_coverage(rows, links)
    for row in matrix.rows:
        line = next(line for line in table.splitlines() if line.startswith(f"| {row} |"))
        assert ("x" in line.split("|", 2)[2]) is (row not in empty)


@given(matrices())
def test_every_row_and_column_survives_rendering(case):
    matrix, _rows, _columns, _links = case
    table = render_matrix(matrix, max_columns=2)
    for column in matrix.columns:
        assert column in table
    for row in matrix.rows:
        assert row in table
