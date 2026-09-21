"""The artifact vocabulary the console renders from."""

from research_team.session.application.tool_artifacts import (
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
    import research_team.session.application.tool_artifacts as module

    declared = {
        value.SHAPE
        for value in vars(module).values()
        if isinstance(value, type) and hasattr(value, "SHAPE")
    }
    assert set(SHAPES) == declared
    assert len(SHAPES) == 7


def test_file_change_from_diff() -> None:
    from research_team.session.application.tool_artifacts import FileChange

    fc = FileChange.from_diff(
        path="/src/main.py",
        before="def old():\n    pass\n",
        after="def old():\n    # updated\n    return 42\n",
    )
    assert fc.path == "/src/main.py"
    assert fc.added == 2
    assert fc.removed == 1
    assert fc.total_lines == 3
    artifact = fc.as_artifact()
    assert artifact["shape"] == "file_change"
    assert artifact["added"] == 2
    assert artifact["removed"] == 1


def test_acknowledgement_success_and_failure() -> None:
    from research_team.session.application.tool_artifacts import Acknowledgement

    ack_ok = Acknowledgement.success("write", "file.py", detail="success")
    assert ack_ok.ok is True
    assert ack_ok.action == "write"
    assert ack_ok.subject == "file.py"

    ack_fail = Acknowledgement.failure("delete", "file.py", detail="not found")
    assert ack_fail.ok is False
    assert ack_fail.action == "delete"


def test_excerpt_from_text() -> None:
    from research_team.session.application.tool_artifacts import Excerpt

    excerpt = Excerpt.from_text(
        source_id="src_1",
        text="The quick brown fox jumps over the lazy dog",
        start=4,
        end=19,
        title="Fox Story",
    )
    assert excerpt.source_id == "src_1"
    assert excerpt.start == 4
    assert excerpt.end == 19
    assert excerpt.text == "quick brown fox"
    assert excerpt.char_count == len("The quick brown fox jumps over the lazy dog")


def test_parse_artifact_round_trips_all_shapes() -> None:
    from research_team.session.application.tool_artifacts import (
        Acknowledgement,
        Delegation,
        EntityList,
        EntityRef,
        Excerpt,
        FileChange,
        Hit,
        HitList,
        Inventory,
        InventoryItem,
        SourceHits,
        Worker,
        parse_artifact,
    )

    # 1. HitList
    hl = HitList(
        pattern="test",
        total=1,
        suppressed=0,
        sources=(
            SourceHits(
                source_id="s1",
                title="title1",
                label="l1",
                char_count=100,
                total=1,
                hits=(Hit(start=10, end=20, snippet="snippet"),),
            ),
        ),
    )
    parsed_hl = parse_artifact(hl.as_artifact())
    assert parsed_hl == hl

    # 2. EntityList
    el = EntityList(
        query="q",
        entities=(EntityRef("e1", "Name", "type", 3),),
        mode="fused",
    )
    assert parse_artifact(el.as_artifact()) == el

    # 3. Excerpt
    exc = Excerpt("s1", "T", "L", 0, 5, 20, "hello", uri="http://a")
    assert parse_artifact(exc.as_artifact()) == exc

    # 4. Inventory
    inv = Inventory("docs", "chars", 10, (InventoryItem("i1", "T", "L", 10, "detail"),))
    assert parse_artifact(inv.as_artifact()) == inv

    # 5. Acknowledgement
    ack = Acknowledgement("save", "doc", "ok", True)
    assert parse_artifact(ack.as_artifact()) == ack

    # 6. FileChange
    fc = FileChange("/a.py", 1, 0, 1, before="", after="a")
    assert parse_artifact(fc.as_artifact()) == fc

    # 7. Delegation
    delg = Delegation("task", (Worker("worker1", 10, 50, True),))
    assert parse_artifact(delg.as_artifact()) == delg

    # Invalid / unknown
    assert parse_artifact({}) is None
    assert parse_artifact("not a dict") is None  # type: ignore[arg-type]
    assert parse_artifact({"shape": "unknown_shape"}) is None
