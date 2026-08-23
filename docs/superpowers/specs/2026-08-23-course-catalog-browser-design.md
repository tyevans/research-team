# The course catalog browser

**Status:** design, approved in outline 2026-08-23. Increment 1 of 3.

## Why this exists

The Curriculum tab shows `AreaMap` and `PathSteps`. Both are correct and
neither invites anyone in. A projection is a result; a catalog is a place. The
goal is a browsable, discoverable front end over indexed content, and
eventually the interface a learner opens when the ingest is finished.

## The three increments, and why they are separate

1. **The catalog page.** Candidates, prominence, categories, generated blurbs,
   three sections, a category page, and a featured override. This is the whole
   visible win and it stands alone.
2. **Course detail and realization.** The generated outline, the `Course`
   aggregate, the UbD kickoff, and the fit signal against current clusters.
3. **The art pipeline.** A library, its search, a pluggable provider, and an
   LLM SVG generator.

This document specifies **increment 1 only**. The seam is deliberate: (1)
defines an art port that returns a reference, and (3) replaces the placeholder
behind it. (2) hangs off a card the reader clicks in (1).

## Vocabulary

| Term | Meaning |
|---|---|
| **Candidate** | A cluster, dressed for browsing. Derived, never stored. |
| **Course** | A candidate a person chose to realize. An aggregate, on the log. Increment 2. |
| **Category** | A group of candidates. Derived by a pluggable grouper. |
| **Prominence** | The score that decides which section a card lands in. |

The distinction between candidate and course is the design. A cluster is a
derivation and must stay recomputable; `domain/learning_area.py` gives the
reason and this document does not reopen it. A course is a *decision*, so it
earns the log. Clusters may then evolve underneath realized courses, and the
disagreement between the two is a signal rather than a corruption.

## What is in scope

* A catalog read, derived per request from the existing curriculum projection.
* Prominence, and three sections computed from it.
* Categories, behind a port, with one implementation.
* A generated blurb per candidate, cached, with visible staleness.
* A featured override, on the log.
* A category page.

## What is deliberately out of scope

* The course detail page and its generated outline. Increment 2.
* `Course` realization and the UbD kickoff. Increment 2.
* Real art. Increment 3. This increment ships a deterministic placeholder.
* Search and free-text filtering. Category is the only cut in increment 1.

## Domain

### `CourseCandidate`

A frozen dataclass in `domain/course_catalog.py`.

```
slug: str                  # the area's slug, unchanged
title: str                 # area.display_name(). Not generated in this increment.
blurb: Blurb | None        # None when nothing has been generated yet
category: CategoryKey
prominence: float
size: int
anchors: tuple[AreaMember, ...]
art: ArtRef
```

`CategoryKey` is a `str` newtype. `ArtRef` is a URL and an alt text, and
nothing more — the port owns where it points, so increment 3 changes the value
and not the shape.

`title` is the area's `display_name()`. Generating a better title is possible
and is **not** done here: `learning_area.py` records that a real authoring run
opened its unit with a title no model-free derivation will match, and reading
that line back is `BACKLOG.md` B139. The catalog does not depend on it.

`slug` is the area's own slug and is not minted here. The rule is already
recorded on `LearningArea`: a slug is a directory name and a URL segment, and a
model-chosen id would be unvalidated input in a storage key.

### `Blurb`

```
text: str
membership_hash: str       # what it was written from
generated_at: datetime
```

`membership_hash` is the whole reason this is a record rather than a string. A
blurb written from forty entities that now describes ninety is not wrong in any
way a reader can see. Storing the hash makes "this description is N entities
behind" a number the card can render.

### `CatalogSections`

```
hero: tuple[CourseCandidate, ...]
highlights: tuple[CourseCandidate, ...]
filed: tuple[Category, ...]      # Category = key, label, ordered candidates
```

Three sections because the reader's attention is not uniform. The cut points
are constants with stated defaults, not magic numbers buried in a loop.

## Prominence

```
prominence = size * mean(anchor centrality) , passages as tiebreak
```

`centrality` is already weighted degree *within* the area, which is the correct
reading: an entity wired to half the project but to nothing in its own area is
a bridge, not an anchor.

**State the limit plainly, because it does not go away.** This measures how
well-connected a cluster is. That is a proxy for "well covered by the corpus",
not for "worth a learner's time". A hero row driven by it alone leads with
whatever was ingested most. The override below is the answer, and it is why the
override is in increment 1 rather than deferred.

### The featured override

Two events on a small aggregate:

* `CourseFeatured(project_id, slug, rank, at)`
* `CourseUnfeatured(project_id, slug, at)`

Featured candidates are pinned to the hero in `rank` order. Everything else
falls through to the derived score.

This is on the log because it is a decision. It is keyed on `slug` rather than
on a minted course id, because a person can feature a candidate that nobody has
realized yet — which is the common case on a fresh project.

**The cost, and it is real.** A slug is derived from an area's top anchor, so
re-clustering can move it. A featured slug that no longer names any area is
dropped from the hero. It is *not* deleted: the event stays on the log, and the
catalog reports the count of featured slugs it could not place. A silent drop
would make a curator's work disappear with nothing to look at.

## Categories

### The port

```python
class CategoryGrouper(Protocol):
    def group(self, areas: Sequence[LearningArea]) -> Mapping[str, CategoryKey]: ...
```

### The one implementation: anchor type plurality

The plurality `entity_type` across an area's anchors.

Measured on the Star Trek project, 2026-08-23, over 5,462 entities:

```
work 1523   person 1282   concept 1023   organization 729
location 241   event 254   category 50   award 2   starship 1
```

Those map onto a reader's intuition well enough to ship: `person` reads as
biographies, `work` as media and series, `location` as places, `organization`
as factions.

**Why not the ontology, which is the obvious answer.** Measured the same day:
`ontology_classes` was 0, and `ontology_examined` was 0 — the pass had never
run on any document. A discovery sweep now exists (#268). Even once populated,
the graph's own grouping edges are weak here: 470 `is_a`/`member_of` edges over
234 targets, whose most common values are `Star Trek`, `The Original Series`,
`Rotten Tomatoes` and `Variety`. Those are franchises and review aggregators,
not classes. Grouping on them today would produce a "Rotten Tomatoes" category.

So the ontology is a *better* source that is not ready. The port exists so it
can replace the plurality grouper without the browser changing.

**What the plurality grouper cannot do**, stated so nobody rediscovers it: it
cannot separate races from enemies. Both are `organization` or `concept`. That
distinction needs the ontology or a model, and it is the reason the port is a
port.

### Display labels

The grouper returns a key. A label is generated once per key per project and
cached beside the blurbs. A key is countable and checkable; a label is
cosmetic. Keeping them apart means a category page can say "31 courses,
grouped because their anchors are `person`" — a claim the reader can check —
while still reading as "Biographies".

## Generated blurbs

Follows `application/entity_definitions.py`, which is the existing precedent
for generated-and-cached text, with **one deliberate difference**.

* Two ports: `BlurbTextPort` (writes) and `BlurbCachePort` (stores).
* Cached per `(project, slug, membership_hash)`.
* Not on the event log. A blurb is a derivation, not a decision.

**The difference from definitions: grounding.** A definition makes factual
claims and is refused when it cites nothing verifiable. A blurb is marketing
copy about what a course would cover. It cannot be citation-verified and
should not pretend to be. What it *must* be is built only from the anchors and
their types — never from what the model knows about the subject from outside
the corpus. A blurb about Vulcans assembled from the model's own Star Trek
knowledge is indistinguishable from one derived from the cluster, and it would
promise a course the corpus cannot teach.

The enforcement is the prompt plus one check: **every proper noun in the blurb
must match an anchor name.** A blurb that names an entity the cluster does not
contain is refused and not stored. This is weaker than citation checking and is
the strongest check available without spans.

## Art, in this increment

```python
class ArtPort(Protocol):
    async def for_candidate(self, slug: str, category: CategoryKey) -> ArtRef: ...
```

One implementation here: a deterministic placeholder derived from the slug —
a seeded geometric SVG, stable across runs, distinct per candidate. It is not a
stand-in that looks broken; a catalog with grey rectangles is not browsable and
the point of this increment is browsability.

Increment 3 replaces the implementation with a library search and a generator.
Nothing above this port changes.

## Interfaces

### Routes

```
GET  /api/projects/{id}/catalog                    -> sections + categories
GET  /api/projects/{id}/catalog/categories/{key}   -> one category, ordered
POST /api/projects/{id}/catalog/{slug}/feature     -> {rank}
POST /api/projects/{id}/catalog/{slug}/unfeature
```

`GET /catalog` answers **503 when the grouper or the blurb cache is unwired**,
never an empty catalog. An empty catalog is the right answer for a project with
no graph, so an unwired build answering the same thing is indistinguishable
from an empty one. This repository has shipped that exact failure more than
once and `read_ontology` records the ruling.

### Frontend

A new `catalog` facet beside `area` and `path`, and the default reading of the
Curriculum tab. `area` and `path` stay: they are the analytic readings, and the
catalog does not replace them.

* `CatalogPane` — fetches, renders three sections.
* `CourseCard` — one candidate. Three sizes, chosen by section.
* `CategoryPage` — one category, selected by `#/p/<id>/catalog/<key>`.

Card size is a computed style, so **`npm run test:browser` is required** for
this work, per `CLAUDE.md`. jsdom lays nothing out and would report every card
identical.

## Verification

Four gates as always, plus the browser suite for card geometry.

Two hazards this repository has met, designed against explicitly:

1. **A port with one adapter and no test between the ends is two things that
   were never checked against each other.** Every port here has exactly one
   production adapter. Each needs one test that drives **both ends over real
   data** — not a stub on one side and a unit test on the other. The
   co-mention channel shipped that way and produced nothing for a whole
   feature.
2. **A missing projection yields an empty read model, not an error.** Every
   test asserts on *data* — a card exists, a blurb has the text the cache
   held, a category holds the expected count. Never that the request
   succeeded.

Specific tests worth naming now:

* A catalog built over a real ingest has a non-zero card count, non-empty
  blurbs, and at least two categories. The count assertion is the one that
  fails when a grouper is dropped.
* A featured slug that no longer names an area is reported, not silently
  dropped.
* A blurb naming an entity absent from its cluster is refused.
* Prominence orders two hand-built areas the way the formula says, chosen so
  the sizes and centralities *disagree* — a case where a simpler formula would
  give a different answer. Areas whose size and centrality agree cannot
  distinguish the formula from `size` alone.

## Rejected alternatives

* **Storing the projection.** Rejected in `learning_area.py` and not reopened.
* **A course per path segment.** No stable id, so art and copy drift.
* **Categories from a second clustering pass.** Emergent labels still need a
  model to name them, and a small project produces one category holding
  everything.
* **Blurbs on the event log.** A derivation beside its own inputs, with no
  answer when the two disagree.
* **Regenerating a blurb on every membership change.** Cheap per call, but the
  copy churns under a reader on an actively-extracting project. The hash and a
  rendered staleness count are the cheaper honesty.

## Deliberately left undone

* No search, no free-text filter, no sort control. Category is the only cut.
* No pagination. A project with 500 areas will render 500 cards. The largest
  real project holds 18 documents, so this is not yet a problem; it becomes one
  before this is a learner interface.
* Blurbs are generated on demand and cached, not backfilled. A cold project
  shows titles without copy until something asks.
