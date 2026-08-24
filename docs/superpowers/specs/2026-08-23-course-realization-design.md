# Course detail and realization

**Status:** design, approved in outline 2026-08-23. Increment 2 of 3.

**Predecessor:** `2026-08-23-course-catalog-browser-design.md`, which built the
catalog page and named this increment in its own scope list. That document's
vocabulary is assumed here and not repeated, except where this increment
changes it.

## Why this exists

Increment 1 made a place. Every card in it is a derivation, and clicking one
does nothing. This increment gives a reader somewhere to land, and gives them
one thing to do when they get there: decide the course is real.

The decision is the point. A cluster is recomputed on every request and must
stay that way; a person choosing one is a fact that has to survive the next
clustering pass. Once the two are separate, the disagreement between them
becomes readable -- a realized course whose cluster has moved underneath it is
a course whose content is out of date, and nothing else in this system can say
so.

## Vocabulary added

| Term | Meaning |
|---|---|
| **Course** | A candidate a person chose to realize. An aggregate, on the log. |
| **Outline** | Generated coverage copy for a candidate. Cached, like a blurb. |
| **Fit** | The comparison between a course's frozen membership and its cluster now. |
| **Orphaned** | A realized course whose slug no longer names any cluster. |

## What is in scope

* The `Course` aggregate, its two events, and its read model.
* A realize route that records the decision and then starts authoring.
* A generated outline per candidate, cached against membership hash.
* A sweep that writes the blurbs increment 1 never triggered.
* A course detail read joining candidate, outline, members, course and run.
* Fit, computed on read.
* The detail page, and cards that link to it.

## What is deliberately out of scope

* Re-authoring a drifted course. Fit reports; nothing acts on it. A button
  that re-runs UbD would silently replace content a person may have edited,
  and there is no realized course old enough yet to have taught us what the
  right behaviour is.
* Real art. Still increment 3, still behind `ArtPort`.
* Search. Still no free-text cut.

---

## 1. `Course` is an aggregate, and `CourseFeatured` is not

`domain/catalog_curation.py` deliberately has no aggregate class: featuring
enforces no invariant, so featuring twice is a rank change and unfeaturing
something never featured is a no-op. Realizing is not like that.

**The invariant: a course is realized once.** A second `CourseRealized` would
overwrite `member_entity_ids` with the membership as it stands today, which is
precisely the value fit is computed against. The drift would be erased by the
act of observing it, and nothing downstream could tell that had happened -- the
course would simply report itself perfectly in step with a cluster it was made
from months earlier. So this gets a `DeciderAggregate`, and `RealizeCourse`
against an already-realized course is rejected.

New module `domain/course.py`. The name is free: `application/course.py` is the
join between a preset's declared stages and the artifacts on disk, and shares
nothing with this but a word.

### Events

```python
COURSE_AGGREGATE_TYPE = "Course"

@register_event
class CourseRealized(DomainEvent):
    aggregate_type: str = COURSE_AGGREGATE_TYPE
    project_id: UUID
    slug: str
    title: str
    member_entity_ids: list[str]
    membership_hash: str
    realized_at: datetime

@register_event
class CourseAbandoned(DomainEvent):
    aggregate_type: str = COURSE_AGGREGATE_TYPE
    project_id: UUID
    slug: str
```

`member_entity_ids` rides on the event rather than being recoverable from the
hash. The hash answers whether the cluster moved; only the ids answer how, and
"how" is the entire product of this feature. A hash-only event would make fit
a boolean, and a boolean nobody can act on is not a signal.

`title` is carried too, and it is genuinely redundant while the slug resolves.
It is there for the orphaned case: a course whose cluster is gone has no
`display_name()` to fall back on, and a list of realized courses that renders
one of them as a bare slug is a list that hides the very case it exists to
surface.

**Stream id** is `(project_id, slug)`, so a project's courses do not serialise
against each other. `CourseAbandoned` returns the aggregate to unrealized, so
abandoning and realizing again *does* re-freeze the membership -- that is a
deliberate second decision, made explicitly, rather than the accidental
re-freeze the invariant guards against.

### The read model

`CourseRow` in `read_models.py`, `__table_name__ = "courses"`, keyed
`uuid5(CATALOG_NAMESPACE, f"course:{project_id}:{slug}")` -- the third prefix
under that namespace, after the unprefixed `CatalogFeatureRow` and `blurb:`.

```
project_id: UUID
slug: str
title: str
member_entity_ids: list[str]
membership_hash: str
realized_at: datetime
abandoned: bool = False
```

`abandoned` as a column rather than a delete, so `CourseProjection` replays to
the same state either way and a rebuild does not resurrect an abandoned course
by processing its `CourseRealized` and then finding nothing to undo it.

**`CourseProjection` handles both events and must be registered in
`composition.py`.** CLAUDE.md's own entry applies exactly: an event no
projection handles counts as applied, so omitting the registration produces an
empty table, a 200, and a detail page that reports every course unrealized
forever. **The test for this asserts a row exists with the frozen ids on it.**
An assertion that the realize route answered 202 passes with the projection
deleted.

---

## 2. Realizing records first and authors second

```
POST /api/projects/{id}/catalog/{slug}/realize
```

1. 404 if the slug names no candidate in the current catalog.
2. Append `CourseRealized` with the membership as it stands now.
3. Attempt `authoring.start(project_id, [slug], _one, kind="area")`.
4. Answer **202** with `{"realized": true, "authoring": frame | null,
   "reason": str | null}`.

**Step 3 never fails the request.** The existing authoring endpoint answers 409
when a run is already in flight -- one at a time per project, for
`AuthoringActivity`'s stated reason. Letting that propagate would mean whether
you can *choose* a course depends on whether somebody else is mid-run, which
makes a decision contingent on scheduling. `RunAlreadyActive` is caught, the
frame is `null`, and `reason` says so. The detail page then offers "Author this
now", which is the existing `POST /curriculum/author` with `area` set.

`_one` is lifted out of `author_courses` so both routes call one function
rather than two copies of the same three-argument call into `CourseAuthor`.

**No new event links the course to its run.** `CourseAuthored` already carries
`(project_id, target, session_id)` and `AuthoringRunRow.authored` already
stores the pairs. `AuthoringRunStore` gains one read --
`authored_session_for(project_id, target) -> UUID | None`, newest run first --
and that is the whole join. Minting a `CourseAuthoringLinked` event would be a
second record of a fact already on the log, and CLAUDE.md has the entry about
two accounts of one thing that can disagree with nothing to catch them.

```
POST /api/projects/{id}/catalog/{slug}/abandon
```

Appends `CourseAbandoned`. 404 for an unrealized slug. Does not cancel a
running authoring run and does not delete written files: the decision is
withdrawn, the work it caused is not, and pretending otherwise would delete a
person's course because they clicked the wrong thing.

---

## 3. The outline

### Shape

```python
@dataclass(frozen=True)
class OutlineSection:
    heading: str
    summary: str

@dataclass(frozen=True)
class Outline:
    promise: str                  # one sentence: what a learner comes away with
    sections: tuple[OutlineSection, ...]
    membership_hash: str
    generated_at: datetime
```

Three to six sections. The floor is because two sections is a blurb with
bullets; the ceiling is because the prompt names at most `PROMPT_ANCHORS` (12)
anchors and an outline with more sections than the graph gave it anchors is a
model padding.

### Its own store, not a `kind` column on blurbs

`CourseOutlineRow` / `CourseOutlineStore`, keyed
`uuid5(CATALOG_NAMESPACE, f"outline:{project_id}:{slug}")`, carrying
`sections_json: str` beside `promise`, `membership_hash`, `model` and
`generated_at`.

A discriminated single table was considered. It loses: a blurb's payload is one
`text` column and an outline's is a structured list, so the shared table needs a
JSON blob column that only one of the two kinds ever fills, and then the two
row types share nothing but a primary key and a namespace. Two stores of the
same shape are honest duplication; one store with a column that is meaningful
for half its rows is a schema that has to be explained.

Same as the blurb: **no `stale` flag.** `membership_hash` answers it by
comparison, and a flag would be a second answer to one question.

### Generation

`OutlineTextPort` in `application/course_catalog.py`, `ModelOutlineWriter` in
`infrastructure/knowledge/outline_writer.py`. The grounding refusal is
`ModelBlurbWriter`'s, unchanged and shared: every capitalised run in the reply
must substring-match an anchor name, and a reply that fails returns `None`
rather than a corrected string. The shared predicate moves to a module both
import; the opener list moves with it. **It is not re-derived in the new
module** -- two copies of that check would drift, and the blurb's copy is the
one with three rounds of review behind it.

Triggered on detail-page read: the route generates when the cache is missing or
its hash disagrees, and awaits it. One model call, and the reader is waiting for
this specific page, so a background job plus a poll would be latency plus
machinery for no gain.

**Per CLAUDE.md, `OutlineTextPort` has exactly one production adapter, so it
needs one test driving both ends over real data** --
`test_an_outline_over_a_real_ingest_names_only_entities_the_cluster_holds`.
The co-mention channel shipped stub-on-one-side and produced nothing for a
release; this is the population that rule was written for.

---

## 4. The blurb sweep

Increment 1 built `ModelBlurbWriter`, built the cache, wired both into
`composition.py`, and never called the writer. Every card ships blank.

```
POST /api/projects/{id}/catalog/blurbs   -> 202, a run frame
GET  /api/projects/{id}/catalog/blurbs   -> {"running": bool, "done": int, "total": int, "failed": int}
```

A background sweep over every candidate whose blurb is missing or whose hash
disagrees, one model call at a time, one at a time per project.

**Deliberately the same shape as the ontology discovery sweep**, which is the
one long-running button in this console that has been used and worked. Not a
side effect of the catalog GET: a project has dozens of candidates and putting
that many serial model calls in front of a page load makes the catalog
unopenable on a cold cache -- which is every cache, the first time.

Not per-card-on-scroll either. That was the alternative considered: it spreads
the cost and needs no button, but it fires model calls from scroll position,
which makes cost depend on how a reader moves their mouse, and it gives no
answer to "is the copy written yet".

Refusals are counted, not retried. A blurb the model would not ground is a card
that keeps its title and its art, which is what increment 1 already renders.

---

## 5. Fit

Pure, in `domain/course.py`:

```python
@dataclass(frozen=True)
class CourseFit:
    kept: tuple[str, ...]
    added: tuple[str, ...]      # in the cluster now, not when realized
    dropped: tuple[str, ...]    # frozen into the course, gone from the cluster
    orphaned: bool

def fit_of(frozen_ids: Sequence[str], area: LearningArea | None) -> CourseFit: ...
```

`area is None` means the slug names no cluster: `orphaned=True`, everything
`dropped`. Slugs derive from an area's top anchor, so re-clustering strands a
realized course exactly as increment 1's `unplaceable_featured` strands a
featured one, and this is the same finding with a different consequence.

Entity **ids** in the tuples, resolved to names by the presenter against the
current area's members -- a dropped id has no name in the current cluster, so
the view reports it as an id, and that is honest rather than a lookup that
invents a label for something that is gone.

Nothing acts on fit. It is rendered.

---

## 6. The detail read

```
GET /api/projects/{id}/catalog/{slug}
```

Registered **above** `/catalog/{slug}/feature` and `/catalog/categories/{key}`
is not required -- the segment counts differ -- but the block keeps increment
1's defensive declaration ordering and its comment.

Answers:

```
{
  "candidate": { ... as the catalog card, including art and blurb ... },
  "outline":   { "promise", "sections", "stale": bool } | null,
  "members":   [ { "entityId", "name", "centrality" }, ... ],
  "course":    null | {
      "realizedAt", "membershipHash",
      "fit": { "kept": [...], "added": [...], "dropped": [...], "orphaned": bool },
      "authoredSessionId": UUID | null
  }
}
```

`outline` is `null` only when generation refused; a cache miss is filled before
answering. `stale` is a convenience over the hash comparison, computed server
side because the client already has to trust the server's `membershipHash` and
two places doing the arithmetic is two places to get it wrong.

`members` is the full member list, not just anchors: the outline is a model's
claim about coverage, and a reader who wants to check it needs the population
the claim was made over on the same page.

**A realized course whose slug is orphaned is not reachable through this
route**, because the candidate does not exist. So the catalog read gains
`orphanedCourses: [{slug, title, realizedAt}]` beside `unplaceableFeatured`,
for the same reason that field exists: work that vanishes without a trace is
worse than work that is visibly stranded.

---

## 7. The front end

* `CoursePage.tsx` at `/projects/:id/catalog/:slug`. Card click navigates.
* Art, title, blurb, then the outline, then the member list.
* "Make this course" when unrealized. Realized shows the date, the fit banner
  when anything moved, and a link to the authored session when there is one.
* "Author this now" when realized with no run.
* The catalog page gets the blurb sweep button and its progress line, and an
  orphaned-courses strip when any exist.

---

## Testing

Beyond each unit's own tests, these four are the ones this repository's history
says will otherwise be missed:

1. **`CourseProjection` registered.** Asserts a `courses` row exists carrying
   the frozen ids. An assertion on the 202 passes with the projection deleted.
2. **Realize twice is refused**, and the stored `member_entity_ids` are
   unchanged by the second attempt. The second half is the real test: a refusal
   that still rewrote the row would pass the first half.
3. **The outline port, both ends over real data.** Not a stub on one side.
4. **Fit distinguishes drift from orphaning.** Parametrised over the property
   that separates them -- a slug that resolves versus one that does not -- and
   not over a representative example, per CLAUDE.md on formulas that agree on
   every case a test naturally reaches.

## Migration

Two new tables. `apply_schema` reconciles added columns, but these are new
tables on a database that predates them, so **the read-model change is verified
against a copy of the real database**, opened through
`research_team.infrastructure.persistence.local_copy`, not against a fresh one.
