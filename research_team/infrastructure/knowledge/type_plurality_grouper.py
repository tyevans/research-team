"""Grouping areas by the commonest entity type among their anchors.

**Why this and not the ontology**, which is the obvious source: see
`CategoryGrouper`'s docstring in `application/course_catalog.py` for the full
measurement. The short version, measured 2026-08-23 against the real
database: a discovery sweep has now run over all three projects (37 of 37
documents examined) and yielded 15 classes and 97 memberships in total -- but
one project alone (Star Trek, 5,462 entities) accounts for only 3 of them, two
of which are the same class name arriving from two different sources. The
ontology would need cross-source class merging before it could group
anything, so it is not ready to replace this yet. The graph's own `is_a` edges
fare no better -- they point mostly at franchises and review aggregators
(`Star Trek`, `Rotten Tomatoes`, `Variety`).

**What this cannot do**, written down so nobody rediscovers it: it cannot
separate races from enemies. Both are `organization` or `concept`. That
distinction needs the ontology or a model, and it is the reason `CategoryGrouper`
is a port rather than this function.
"""

from collections import Counter
from collections.abc import Mapping, Sequence

from research_team.domain.course_catalog import CategoryKey
from research_team.domain.learning_area import LearningArea

UNCLASSIFIED: CategoryKey = "unclassified"

CATEGORY_LABELS: Mapping[CategoryKey, str] = {
    "person": "People",
    "work": "Works & Media",
    "location": "Places",
    "organization": "Organisations",
    "event": "Events",
    "concept": "Ideas",
    "category": "Classifications",
    UNCLASSIFIED: "Unclassified",
}
"""Display labels for the keys this grouper emits.

Consumed by a later task, which builds `Category.label` from this and falls
back to the key itself for a key not listed here. A fixed table rather than a
generated label, in this increment: a table is honest and checkable and
cannot describe a category as something it is not, where a generated label
could claim a coherence the grouping does not have. An unlisted key falling
back to its raw form is ugly and correct; a made-up label in its place would
be neither.
"""


class TypePluralityGrouper:
    """The `CategoryGrouper` over anchor entity types."""

    def group(self, areas: Sequence[LearningArea]) -> Mapping[str, CategoryKey]:
        return {area.slug: self._key_for(area) for area in areas}

    def label_for(self, key: CategoryKey) -> str:
        return CATEGORY_LABELS.get(key, key)

    @staticmethod
    def _key_for(area: LearningArea) -> CategoryKey:
        anchors = area.anchors
        if not anchors:
            return UNCLASSIFIED
        counts = Counter(m.entity_type for m in anchors)
        best = max(counts.values())
        tied = {t for t, n in counts.items() if n == best}
        if len(tied) == 1:
            return next(iter(tied))
        # Ties are routine -- two people and two works is an ordinary area --
        # and an arbitrary tiebreak would move a card between categories on
        # reruns over an unchanged graph. `anchors` is already ranked by
        # centrality with a deterministic entity-id tiebreak, so the top
        # anchor whose type is among the tied ones decides.
        return next(m.entity_type for m in anchors if m.entity_type in tied)
