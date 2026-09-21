"""Curriculum, course, catalog, and progress presenters for the web interface."""

from collections.abc import Sequence
from typing import Any

from research_team.curriculum.application import Curriculum
from research_team.curriculum.application.course_catalog import (
    CachedOutline,
    Catalog,
)
from research_team.curriculum.application.course_realization import (
    CourseDetail,
    RealizedCourse,
)
from research_team.curriculum.domain.catalog import Category, CourseCandidate
from research_team.curriculum.domain.course import CourseFit
from research_team.curriculum.domain.learner import LearnerProgressState
from research_team.curriculum.domain.learning_area import (
    AreaMember,
    LearningArea,
    LearningPath,
    PrerequisiteEdge,
)


def item_view(state: LearnerProgressState, path: str, component_id: str) -> dict[str, Any]:
    """One item's progress, or the zeroed shape for one nobody has touched.

    Never `None`. A client that has to branch on "no record yet" writes that
    branch once per renderer and gets it wrong in one of them; a zeroed record
    reads the same as an untouched one everywhere, which is what it is.
    """
    record = state.item(path, component_id)
    if record is None:
        return {
            "path": path,
            "component_id": component_id,
            "attempts": 0,
            "correct": False,
            "best_score": 0.0,
            "last_score": 0.0,
            "checked": [],
        }
    return {
        "path": record.path,
        "component_id": record.component_id,
        "attempts": record.attempts,
        "correct": record.correct,
        "best_score": record.best_score,
        "last_score": record.last_score,
        "checked": list(record.checked),
    }


def progress_view(state: LearnerProgressState, path: str | None = None) -> dict[str, Any]:
    """Everything this learner has done, optionally narrowed to one file.

    Keyed by component id when narrowed to a path, because that is what a
    renderer holds and it saves every call site re-deriving the composite key.
    Unnarrowed, the key has to carry the path too -- ids are only unique within
    a document -- so the two shapes differ deliberately rather than by neglect,
    and `scope` says which one this is.
    """
    records = [
        record for record in state.items.values() if path is None or record.path == path
    ]
    if path is not None:
        return {
            "scope": "file",
            "path": path,
            "items": {
                record.component_id: item_view(state, record.path, record.component_id)
                for record in records
            },
        }
    return {
        "scope": "session",
        "path": None,
        "items": {
            f"{record.path}#{record.component_id}": item_view(
                state, record.path, record.component_id
            )
            for record in records
        },
    }


def dialogue_progress_view(state: LearnerProgressState, dialogue_id: str) -> dict[str, Any]:
    """Everything this reader has answered in one dialogue, keyed by turn.

    **A third shape beside `progress_view`'s two, and the third is deliberate.**
    `progress_view` already carries `scope: "file"` (keyed by component id,
    because the caller holds the path) and `scope: "session"` (keyed
    `path#component_id`, because ids are only unique within a document). Neither
    fits a dialogue: its records are stored under `path="turn/{position}"` -- an
    utterance, not a file -- and a component id is only unique within one
    utterance, so the key has to carry both. Reusing the file-narrowed shape
    would mean inventing a `path` per turn and calling it once per turn, which
    is worse than either.

    The alternative was widening `progress_view` with a third `scope`. That is
    the smaller diff and the wider blast radius: a presenter shared by the
    lesson and session surfaces, widened so a third can reuse it, is how
    surfaces couple without anyone deciding to couple them -- the next change to
    the session shape would then have to be reasoned about for a dialogue too.

    **The cost of the third shape, stated rather than hidden: it is a third
    thing to keep true.** A change to how progress is reported now has three
    presenters to check instead of two. `item_view` is shared by all three,
    which is what holds that cost to the envelope rather than the record.

    Two levels rather than a flat `turn/0#council-1`, unlike the session shape,
    because the client consumes it one turn at a time: `useDialogueAttempts` is
    called once per exchange and wants exactly that exchange's map. A flat key
    would make every caller re-derive a composite and filter.
    """
    turns: dict[str, dict[str, Any]] = {}
    for record in state.items.values():
        turns.setdefault(record.path, {})[record.component_id] = item_view(
            state, record.path, record.component_id
        )
    return {"scope": "dialogue", "dialogueId": dialogue_id, "items": turns}


def area_view(area: LearningArea, *, members: bool = True) -> dict[str, Any]:
    """One learning area, with its members or only its anchors.

    `members=False` is what the map uses and it is not merely a size
    optimisation: a card showing sixty entity names is a card nobody reads,
    and the anchors are the ones the graph says the area is *about*. The full
    membership belongs on the area's own page, where a reader has asked for
    it.

    `centrality` crosses the wire rounded rather than raw. It is a weighted
    degree inside the area, and the fifteenth decimal place of one is not a
    fact about the project -- shipping it would invite a client to sort on
    noise and to render two identical entities as differently ranked.
    """
    anchors = area.anchors
    shown = anchors if members else anchors[:ANCHOR_PREVIEW]
    return {
        "slug": area.slug,
        "title": area.display_name(),
        "summary": area.summary,
        "size": area.size,
        "truncated_members": not members and len(anchors) > ANCHOR_PREVIEW,
        "members": [
            {
                "entity_id": m.entity_id,
                "name": m.name,
                "entity_type": m.entity_type,
                "centrality": round(m.centrality, 3),
                "temporal": m.temporal,
            }
            for m in shown
        ],
    }


#: How many of an area's anchors a map card carries. Small because the card is
#: a glance, and because §8 of the design gives the map one job -- being
#: falsifiable at a glance by somebody who knows the subject. Five names do
#: that; sixty prevent it.
ANCHOR_PREVIEW = 5


def edge_view(edge: PrerequisiteEdge) -> dict[str, Any]:
    return {
        "before": edge.before,
        "after": edge.after,
        "weight": edge.weight,
        "reason": edge.reason,
        "contested": edge.contested,
    }


def path_view(path: LearningPath) -> dict[str, Any]:
    return {
        "slug": path.slug,
        "title": path.title,
        "destination": path.destination,
        "areas": list(path.area_slugs),
        "edges": [edge_view(e) for e in path.edges],
    }


def curriculum_view(curriculum: Curriculum) -> dict[str, Any]:
    """The area map and the complete path, in one response.

    The three counts ride along on every read rather than living behind a
    second endpoint, because they are what makes a thin projection legible as
    thin. An area map over forty entities and one over four thousand render
    identically otherwise, which is the surface `CLAUDE.md` warns about under
    *Events*: one that looks the same whether the machinery ran or not.
    """
    projection = curriculum.projection
    return {
        "areas": [area_view(a, members=False) for a in projection.areas],
        "path": path_view(curriculum.path),
        "derived_from": {
            "entities": projection.entity_count,
            "relationships": projection.relationship_count,
            "passages": projection.co_mention_count,
            # Both, and not just the flag. `used_embeddings` answers "did this
            # signal contribute at all", which is what a reader needs to know
            # before trusting the map; the count is what tells them whether it
            # contributed *meaningfully* -- eleven edges over four thousand
            # entities is technically true and practically nothing.
            "semantic_edges": projection.semantic_count,
            "used_embeddings": projection.used_embeddings,
            "truncated": projection.truncated,
        },
    }


def candidate_view(candidate: CourseCandidate) -> dict[str, Any]:
    """One card, wherever it landed -- hero, highlights, a filed category, or
    a category page. Anchors are shaped exactly as `area_view`'s are, because
    they are the same object; a client rendering both should not need two
    readers for one shape.
    """
    return {
        "slug": candidate.slug,
        "title": candidate.title,
        "category": candidate.category,
        "prominence": round(candidate.prominence, 3),
        "size": candidate.size,
        # The cluster's *current* hash, not the blurb's -- kept separate from
        # `blurb.membershipHash` below on purpose. Staleness is the two read
        # together: a blurb's hash alone says only what it was written from,
        # and this field alone says only what the cluster is now. Neither one
        # by itself lets a client compute anything; the comparison is the
        # whole reason `CourseCandidate.membership_hash` exists at all (see
        # its own docstring).
        "membershipHash": candidate.membership_hash,
        "anchors": [
            {
                "entity_id": a.entity_id,
                "name": a.name,
                "entity_type": a.entity_type,
                "centrality": round(a.centrality, 3),
                "temporal": a.temporal,
            }
            for a in candidate.anchors
        ],
        "art": {"url": candidate.art.url, "alt": candidate.art.alt},
        "blurb": (
            None
            if candidate.blurb is None
            else {
                "text": candidate.blurb.text,
                "membershipHash": candidate.blurb.membership_hash,
                "generatedAt": candidate.blurb.generated_at.isoformat(),
            }
        ),
        "featuredRank": candidate.featured_rank,
    }


def category_view(category: Category) -> dict[str, Any]:
    return {
        "key": category.key,
        "label": category.label,
        "candidates": [candidate_view(c) for c in category.candidates],
    }


def _every_category(catalog: Catalog) -> dict[str, str]:
    """Every category with at least one candidate anywhere in the catalog.

    Not `catalog.categories`: that map is derived from `sections.filed` alone
    (see `Catalog`'s own docstring), so a category whose every candidate was
    promoted to hero or highlights has no entry in it, even though
    `all_candidates` still holds its members -- ruling R9b. Falling back to
    the key itself for one `catalog.categories` has no label for matches
    `CategoryGrouper.label_for`'s own fallback for the same case, for the
    reason its docstring gives: an unlisted label is ugly and correct, and a
    made-up one would be neither.
    """
    keys = {c.category for c in catalog.all_candidates}
    return {key: catalog.categories.get(key, key) for key in sorted(keys)}


def catalog_view(
    catalog: Catalog, orphaned_courses: Sequence[RealizedCourse] = ()
) -> dict[str, Any]:
    """The whole catalog: three bands, every category, and what it was
    derived from.

    `derived_from` rides along for `curriculum_view`'s stated reason -- a
    catalog over 40 entities and one over 4,000 render identically otherwise.
    `categories` is built from every candidate the catalog holds, not from
    `catalog.categories` alone, for `_every_category`'s reason (R9b).

    `orphaned_courses` -- `CourseService.orphans()`'s result -- is a separate
    argument rather than a `Catalog` field: it names courses the *catalog*
    has no candidate for at all (see `RealizedCourse`'s docstring), so nothing
    in `Catalog`'s own assembly has a way to produce it. Empty by default so
    every existing caller keeps working; a caller that has not wired
    `orphans()` up yet renders an honestly empty list rather than a missing
    key.
    """
    return {
        "hero": [candidate_view(c) for c in catalog.sections.hero],
        "highlights": [candidate_view(c) for c in catalog.sections.highlights],
        "filed": [category_view(cat) for cat in catalog.sections.filed],
        "categories": _every_category(catalog),
        "unplaceableFeatured": list(catalog.unplaceable_featured),
        "unnamedCount": catalog.unnamed_count,
        "orphanedCourses": [
            {
                "slug": c.slug,
                "title": c.title,
                "realizedAt": c.realized_at.isoformat(),
            }
            for c in orphaned_courses
        ],
        "derived_from": {
            "entities": catalog.derived_from[0],
            "relationships": catalog.derived_from[1],
        },
    }


def catalog_category_view(catalog: Catalog, key: str) -> dict[str, Any] | None:
    """One category's page, or `None` for a key nothing in this catalog uses.

    Built from `catalog.all_candidates`, never `catalog.sections.filed` --
    ruling R9: a candidate promoted to hero or highlights still belongs to its
    category, and a page built by filtering `filed` would silently omit
    exactly the courses prominent enough to have been promoted out of it.
    `all_candidates` is the total population for exactly this caller, per
    `Catalog.all_candidates`'s own docstring.

    Membership is checked against `all_candidates` directly rather than
    against `catalog.categories`, which is what makes an unknown key (404)
    distinguishable from a known key every one of whose candidates got
    promoted (200, non-empty) -- ruling R9b. `catalog.categories` alone
    cannot tell the two apart, because it omits the second case too.
    """
    members = [c for c in catalog.all_candidates if c.category == key]
    if not members:
        return None
    return {
        "key": key,
        "label": catalog.categories.get(key, key),
        "candidates": [candidate_view(c) for c in members],
    }


def outline_view(outline: CachedOutline) -> dict[str, Any]:
    """A generated or cached outline, `sections` in reading order.

    `(heading, summary)` pairs cross the wire as objects rather than tuples --
    JSON has no tuple type, and a two-element array would ask every client to
    remember which index is which.
    """
    return {
        "promise": outline.promise,
        "sections": [{"heading": h, "summary": s} for h, s in outline.sections],
        "membershipHash": outline.membership_hash,
        "model": outline.model,
        "generatedAt": outline.generated_at.isoformat(),
    }


def course_fit_view(fit: CourseFit, members: Sequence[AreaMember]) -> dict[str, Any]:
    """How a realized course's frozen membership compares to its cluster now.

    `kept` and `added` resolve against `members` -- the current cluster --
    because both are ids the cluster still holds. `dropped` is reported as
    bare ids: those entities are, by construction, no longer among `members`,
    so there is nothing to resolve against and no other place to look. See
    `fit_of`'s own docstring for why a dropped id cannot be given a name here.
    """
    names = {m.entity_id: m.name for m in members}
    return {
        "kept": [{"entity_id": i, "name": names[i]} for i in fit.kept],
        "added": [{"entity_id": i, "name": names[i]} for i in fit.added],
        "dropped": list(fit.dropped),
        "orphaned": fit.orphaned,
    }


def course_detail_view(detail: CourseDetail) -> dict[str, Any]:
    """One course detail page: the candidate, its outline, its full current
    membership, and -- if realized -- how it has drifted since.

    `members` uses the same per-member shape `area_view` does, for
    `candidate_view`'s reason: a client rendering both should not need two
    readers for one shape. See `CourseDetail.members`'s own docstring for why
    `[]` here is ambiguous with "no cluster" and has to be read alongside
    `course.fit.orphaned` rather than alone.
    """
    return {
        "candidate": candidate_view(detail.candidate),
        "outline": None if detail.outline is None else outline_view(detail.outline),
        "members": [
            {
                "entity_id": m.entity_id,
                "name": m.name,
                "entity_type": m.entity_type,
                "centrality": round(m.centrality, 3),
                "temporal": m.temporal,
            }
            for m in detail.members
        ],
        "course": (
            None
            if detail.course is None
            else {
                "realizedAt": detail.course.realized_at.isoformat(),
                "membershipHash": detail.course.membership_hash,
                "fit": course_fit_view(detail.course.fit, detail.members),
                "authoredSessionId": (
                    str(detail.course.authored_session_id)
                    if detail.course.authored_session_id is not None
                    else None
                ),
            }
        ),
    }
