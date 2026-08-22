"""What a project turned out to be about, and in what order to learn it.

Three value objects and no behaviour beyond arithmetic over them. The
projection that produces these lives in `application/area_projection.py` and
the ordering in `application/learning_paths.py`; this module is what they
agree on.

**Nothing here is an aggregate and nothing here is on the event log.** That is
a decision rather than an omission, and it is the one worth reading before
adding a `LearningAreasProjected` event. A projection is a pure function of a
graph that is *itself* folded from the log -- so the log already contains
everything needed to reproduce it, and storing the output would be storing a
derivation beside its own inputs. The failure mode that creates is specific
and this repository has met it: a stored projection and a re-derived one
disagree, both are defensible, and nothing says which is current. See
`docs/design/learning-areas-and-paths.md` §9 for what is given up by not
storing it -- a projection cannot be "stale" if it is always recomputed, but
it also cannot be annotated, and annotation is the thing to reach for an
event for when somebody asks.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class AreaMember:
    """One entity's membership in an area, with what earned it the place.

    `centrality` is the entity's weighted degree *within its own area*, not
    within the graph. The distinction decides what an anchor is: an entity
    wired to half the project but to nothing in the area it landed in is a
    bridge, not an anchor, and ranking by global degree would put it at the
    top of an area it barely belongs to.
    """

    entity_id: str
    name: str
    entity_type: str
    centrality: float
    temporal: str | None = None


@dataclass(frozen=True)
class LearningArea:
    """One cluster of the graph, as something a person could study.

    `slug` is derived from the anchors rather than minted, and that is
    load-bearing: it is a directory name under `/course/areas/` and a URL
    segment, and `derive-ids-rather-than-let-the-model-pick` is the rule this
    repository already learned. A model-chosen id would be unvalidated input
    in a storage key.

    `title` and `summary` are the *only* two fields a model may write, and
    both are cosmetic -- delete them and the area still identifies, orders and
    materialises correctly. Everything structural comes from the graph.
    """

    slug: str
    members: tuple[AreaMember, ...]
    title: str | None = None
    summary: str | None = None

    @property
    def anchors(self) -> tuple[AreaMember, ...]:
        """The members the graph says the area is about, most central first.

        Ties break on entity id, not on insertion order: two entities of equal
        centrality must rank the same way on every run, or the slug derived
        from the top anchor changes between runs over the same graph and the
        directory a course was written to moves underneath it.
        """
        return tuple(sorted(self.members, key=lambda m: (-m.centrality, m.entity_id)))

    @property
    def size(self) -> int:
        return len(self.members)

    def display_name(self) -> str:
        """What to call this area when nothing has named it.

        The top anchor's name rather than the slug: a slug is lossy on
        purpose (lowercased, punctuation dropped) and showing it to a reader
        as a title advertises the derivation instead of the subject.
        """
        if self.title:
            return self.title
        anchors = self.anchors
        return anchors[0].name if anchors else self.slug


@dataclass(frozen=True)
class PrerequisiteEdge:
    """One ordering claim: `before` should be studied ahead of `after`.

    `contested` marks an edge that survived a cycle its reverse also had a
    claim on. It is carried rather than resolved silently because a mutual
    dependency between two areas is real information about the subject -- it
    says the two genuinely interleave -- and a clean topological order that
    threw it away would be the more confident and less true answer.
    """

    before: str
    after: str
    weight: float
    reason: str
    contested: bool = False


@dataclass(frozen=True)
class LearningPath:
    """An ordered walk through some or all of a projection's areas.

    `area_slugs` is the order. `edges` is why, and it holds only the edges
    *between consecutive steps plus every contested edge* rather than the
    whole digraph: the question a reader has at step four is "why is this
    fourth", and handing them the complete prerequisite relation buries the
    answer in the other ninety edges.
    """

    slug: str
    title: str
    area_slugs: tuple[str, ...]
    edges: tuple[PrerequisiteEdge, ...]
    destination: str | None = None
    """The area this path was cut to reach, or `None` for the full path.

    A path with a destination is the answer to "what do I need in order to
    understand this", which is the question people actually arrive with. It
    is the prerequisite closure of one area rather than a different ordering
    of everything, so its steps are a subsequence of the full path's.
    """

    @property
    def contested(self) -> tuple[PrerequisiteEdge, ...]:
        return tuple(e for e in self.edges if e.contested)


@dataclass(frozen=True)
class AreaProjection:
    """Every area found in one pass, with what the pass had to work with.

    The three counts are not decoration. A projection over 40 entities and one
    over 4,000 are different claims about a project, and an area map that
    looks identical in both cases is the surface `CLAUDE.md` warns about under
    *Events* -- one that renders successfully whether the machinery ran or
    not. `entity_count` is what makes "this is thin" visible to a reader
    rather than only to whoever wrote the algorithm.

    `used_embeddings` records which of the two possible runs this is, and
    `semantic_count` says how much. Both matter because the embedding channel
    is the one that can be silently absent: embeddings off, a project ingested
    before they were durable, or a provider whose endpoint was down all produce
    a projection that renders perfectly and clustered on the graph alone. A
    reader who cannot tell those from a run that used every signal is being
    shown a weaker claim than they think.
    """

    areas: tuple[LearningArea, ...]
    entity_count: int
    relationship_count: int
    co_mention_count: int
    semantic_count: int = 0
    """Embedding-derived edges actually drawn, after the similarity floor.

    Not the number of pairs offered. See `project_areas`.
    """
    used_embeddings: bool = False
    truncated: bool = False
    """The graph read hit its cap, so these areas are over part of the graph.

    Carried from `Graph.truncated` for that field's own reason: a reader shown
    areas built from 5,000 of 9,000 entities and no flag is looking at a
    curriculum for a different project and cannot tell.
    """
