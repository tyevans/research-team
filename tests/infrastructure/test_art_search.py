"""The IDF-weighted lexical search `LibraryArtProvider` scores the art
library with. No embeddings -- see `library_art.py`'s module docstring for
why."""

from datetime import UTC, datetime
from uuid import uuid4

from research_team.infrastructure.knowledge.library_art import (
    _ART_MATCH_THRESHOLD,
    _best_match,
)
from research_team.infrastructure.persistence.read_models import ArtRow


def _row(description: str, tags: list[str]) -> ArtRow:
    return ArtRow(
        id=uuid4(),
        svg="<svg viewBox='0 0 1 1'></svg>",
        description=description,
        tags=tags,
        palette="work",
        created_at=datetime.now(UTC),
        source="seeded",
        uses=0,
    )


def test_a_row_sharing_every_query_token_scores_higher_than_one_sharing_none():
    warp = _row("a glowing warp nacelle bending starlight", ["warp", "engineering"])
    unrelated = _row("a bowl of fruit on a wooden table", ["still-life"])

    match, score = _best_match(
        "warp nacelle propulsion", ["warp", "engineering"], [warp, unrelated]
    )

    assert match is warp
    assert score > 0


def test_no_shared_tokens_scores_zero_and_is_not_a_match():
    unrelated = _row("a bowl of fruit on a wooden table", ["still-life"])

    result = _best_match("warp nacelle propulsion", ["engineering"], [unrelated])

    assert result is None


def test_the_threshold_is_between_zero_and_one():
    assert 0.0 < _ART_MATCH_THRESHOLD <= 1.0


def test_a_rarer_shared_token_outweighs_a_common_one():
    # "diagram" appears in both rows' descriptions (common, low IDF); "nacelle"
    # appears only in the row that should win (rare, high IDF).
    warp = _row("a warp nacelle diagram", ["warp"])
    generic = _row("a generic technical diagram", ["diagram"])

    match, score = _best_match("nacelle diagram", [], [warp, generic])

    assert match is warp
    assert score > 0
