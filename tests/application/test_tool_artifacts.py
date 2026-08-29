"""The artifact vocabulary the console renders from."""

from research_team.application.tool_artifacts import (
    ARTIFACT_VERSION,
    SHAPES,
    EntityList,
    EntityRef,
    Hit,
    HitList,
    SourceHits,
)


def test_a_hit_list_carries_offsets_and_totals_not_percentages() -> None:
    """The bar widths are the renderer's business; a percentage on the wire
    cannot be turned back into the range a citation needs."""
    artifact = HitList(
        pattern="magic",
        total=19,
        suppressed=0,
        sources=(
            SourceHits(
                source_id="manuscriptreport-com-blog-42e281d8",
                title="manuscriptreport.com",
                label="types of fictional genres",
                char_count=25784,
                total=9,
                hits=(Hit(start=1529, end=1694, snippet="…use of magic…"),),
            ),
        ),
    ).as_artifact()

    assert artifact["shape"] == "hit_list"
    assert artifact["version"] == ARTIFACT_VERSION
    assert artifact["total"] == 19
    assert artifact["sources"][0]["char_count"] == 25784
    assert artifact["sources"][0]["hits"][0] == {
        "start": 1529,
        "end": 1694,
        "snippet": "…use of magic…",
    }
    assert not any("percent" in key for key in artifact["sources"][0])


def test_an_unlinked_entity_is_zero_not_absent() -> None:
    """`0 relationship(s)` is the graph's most actionable gap. It has to
    survive to the renderer as a value, not as an omission."""
    artifact = EntityList(
        query="magic",
        entities=(
            EntityRef(
                entity_id="c0eaaeba",
                name="Magic Systems",
                entity_type="concept",
                relationship_count=2,
            ),
            EntityRef(
                entity_id="af6f2548", name="magic", entity_type="concept", relationship_count=0
            ),
        ),
        mode="fused",
    ).as_artifact()

    assert [entity["relationship_count"] for entity in artifact["entities"]] == [2, 0]


def test_the_registry_names_every_shape_class() -> None:
    """Derived by introspection rather than hand-listed, so an eighth shape
    fails here instead of rendering as a permanent fallback nobody notices."""
    import research_team.application.tool_artifacts as module

    declared = {
        value.SHAPE
        for value in vars(module).values()
        if isinstance(value, type) and hasattr(value, "SHAPE")
    }
    assert set(SHAPES) == declared
    assert len(SHAPES) == 7
