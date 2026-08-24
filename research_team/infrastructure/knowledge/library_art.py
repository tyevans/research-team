"""`ArtPort` over the shared art library, with a search-then-generate fallback.

**Why lexical search rather than embeddings.** The library starts empty and
grows one candidate at a time, so for a long stretch any ranking scheme is
indistinguishable from any other over a handful of rows -- there is nothing
yet to measure a fancier ranker against. An embedding index is a real
dependency, not a free upgrade: a model call per row on write, and a vector
store to keep that index in sync with, bought against a corpus too small to
tell whether it changed anything. Token overlap over the row's description
and tags, weighted by how rare each token is across the library being
searched, is cheap, needs no extra infrastructure, and is legible -- a wrong
match can be read off the tokens that caused it. Revisit once the library has
grown to a few hundred pieces; `semantic_neighbours.VectorNeighbours` is the
existing example in this codebase of the same embedding-similarity mechanism
applied to a different corpus (entities rather than art), and is the shape to
follow if this search is ever replaced.

**Assignment is a decision, not a cache.** Once `for_candidate` resolves a
slug to an `art_id` -- by prior assignment or by a fresh search match -- it
writes that pairing to `CandidateArtStore` so every later request for the
same `(project_id, slug)` returns the same picture without searching again.
A fallback (the seeded placeholder) is the one outcome that is *not*
recorded: recording it would make an unmatched candidate look "resolved" to
anything checking "no assignment and no library match" for work still to do
(the art sweep in `interfaces/web/art_sweep.py`), and it would never be
revisited once the library grows a piece that actually fits. Leaving it
unassigned is what lets the sweep find it again next run.
"""

import math
import re
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from research_team.domain.course_catalog import ArtRef, CourseCandidate
from research_team.infrastructure.persistence.read_models import ArtRow

#: Picked, not measured. What would measure it: the rate at which a person
#: shown the matched picture beside the candidate's title and anchors would
#: say the picture fits -- not available without a human-rated corpus, which
#: does not exist yet at any library size. Revisit once the sweep has run
#: enough real assignments to sample from.
_ART_MATCH_THRESHOLD = 0.35

_TOKEN = re.compile(r"[a-z0-9]+")


def _tokens(text: str) -> list[str]:
    return [t for t in _TOKEN.findall(text.lower()) if len(t) > 2]


def _idf(token: str, doc_tokens: list[list[str]]) -> float:
    # Smoothed so a token appearing in every row (df == n) still gets a
    # positive, if small, weight rather than log(1) == 0 -- a query that
    # matches only universally-common tokens should score low, not
    # identically to matching nothing, which a bare log(n/df) would produce
    # whenever df == n.
    n = len(doc_tokens)
    df = sum(1 for toks in doc_tokens if token in toks)
    return math.log((n + 1) / (df + 1)) + 1


def _score(query_tokens: list[str], row_tokens: list[str], idf: dict[str, float]) -> float:
    if not query_tokens:
        return 0.0
    shared = set(query_tokens) & set(row_tokens)
    raw = sum(idf[t] for t in shared)
    # Normalised by the score a row matching every query token would get, so
    # the result lands in 0..1 regardless of how many tokens the query has or
    # how rare they are -- a fixed threshold only means the same thing across
    # candidates if the scale itself is fixed.
    denom = sum(idf[t] for t in set(query_tokens))
    return raw / denom if denom else 0.0


def _best_match(
    query_text: str, query_tags: list[str], rows: list[ArtRow]
) -> tuple[ArtRow, float] | None:
    """The row scoring highest against the query, or `None` if nothing
    shares a token with it. IDF is computed over exactly the rows passed in
    for this one call -- the library being searched right now, not a corpus
    held across calls -- because the library changes shape (grows) between
    sweeps and a stale IDF table would misrank against rows added since."""
    if not rows:
        return None
    query_tokens = _tokens(query_text) + [t.lower() for t in query_tags]
    row_tokens = [_tokens(r.description) + [t.lower() for t in r.tags] for r in rows]
    vocabulary = {t for toks in ([query_tokens, *row_tokens]) for t in toks}
    idf = {t: _idf(t, row_tokens) for t in vocabulary}

    best_row: ArtRow | None = None
    best_score = 0.0
    for row, toks in zip(rows, row_tokens, strict=True):
        score = _score(query_tokens, toks, idf)
        if score > best_score:
            best_score = score
            best_row = row
    if best_row is None or best_score <= 0.0:
        return None
    return best_row, best_score


class _ArtStoreLike(Protocol):
    async def all(self) -> list[ArtRow]: ...
    async def get(self, art_id: UUID) -> ArtRow | None: ...
    async def increment_uses(self, art_id: UUID) -> None: ...


class _CandidateArtStoreLike(Protocol):
    async def get(self, project_id: UUID, slug: str): ...
    async def put(
        self, project_id: UUID, slug: str, art_id: UUID, membership_hash: str
    ) -> None: ...


class _FallbackArtPort(Protocol):
    async def for_candidate(self, project_id: UUID, candidate: CourseCandidate) -> ArtRef: ...


@dataclass(frozen=True)
class _CandidateQuery:
    text: str
    tags: list[str]


def _query_for(candidate: CourseCandidate) -> _CandidateQuery:
    text = candidate.title + " " + " ".join(a.name for a in candidate.anchors)
    return _CandidateQuery(text=text, tags=[candidate.category])


class LibraryArtProvider:
    """`ArtPort` backed by the shared library: prior assignment, then a
    search match, then a fallback -- see the module docstring for why a
    fallback is never recorded as an assignment."""

    def __init__(
        self,
        art_store: _ArtStoreLike,
        candidate_art_store: _CandidateArtStoreLike,
        fallback: _FallbackArtPort,
    ) -> None:
        self._art = art_store
        self._candidate_art = candidate_art_store
        self._fallback = fallback

    async def for_candidate(self, project_id: UUID, candidate: CourseCandidate) -> ArtRef:
        """Resolve this candidate's art, refreshing an assignment made
        against a cluster that has since drifted (a different
        `membership_hash`) -- the art equivalent of a stale blurb.

        A drifted assignment is *eligible* for a fresher library match here,
        but never discarded for staleness alone: if nothing in the library
        matches any better, this keeps returning the picture the candidate
        already has rather than falling back to the seeded placeholder,
        exactly as it would for a fresh assignment. Generating a *new*
        piece for a drifted candidate with no match is the sweep's job
        (`art_sweep.py`), not this per-request path -- a model call on every
        catalog read is the same cost `ArtGeneratorPort`'s callers already
        avoid everywhere else.
        """
        assigned = await self._candidate_art.get(project_id, candidate.slug)
        stale = assigned is not None and assigned.membership_hash != candidate.membership_hash
        if assigned is not None and not stale:
            row = await self._art.get(assigned.art_id)
            if row is not None:
                return _ref(row)
            # Assignment points at a row that no longer exists -- fall
            # through to search/fallback rather than raise, the same
            # tolerance `CourseBlurbStore` extends a stale cache entry.

        match = await self.match(candidate)
        if match is not None:
            row, _score = match
            if assigned is not None and row.id != assigned.art_id:
                # Moving the candidate off whatever it pointed at before --
                # a fresh assignment (this branch) or a drifted one being
                # upgraded to a better match. The old piece may still suit
                # another candidate (increment 3's "Art is write-once" is
                # exactly what this feature removes), so it stays in the
                # library; only its use count follows the candidate away.
                await self._art.decrement_uses(assigned.art_id)
            await self._candidate_art.put(
                project_id, candidate.slug, row.id, candidate.membership_hash
            )
            await self._art.increment_uses(row.id)
            return _ref(row)

        if stale:
            row = await self._art.get(assigned.art_id)
            if row is not None:
                return _ref(row)

        return await self._fallback.for_candidate(project_id, candidate)

    async def match(self, candidate: CourseCandidate) -> tuple[ArtRow, float] | None:
        """The library's best match for this candidate, above threshold, or
        `None`. Exposed separately from `for_candidate` so the art sweep
        (`interfaces/web/art_sweep.py`) can ask "does the library already
        cover this?" without also writing an assignment as a side effect --
        the sweep only wants to generate for candidates this returns `None`
        for."""
        query = _query_for(candidate)
        rows = await self._art.all()
        best = _best_match(query.text, query.tags, rows)
        if best is None:
            return None
        row, score = best
        if score < _ART_MATCH_THRESHOLD:
            return None
        return row, score


def _ref(row: ArtRow) -> ArtRef:
    return ArtRef(url=f"/api/art/{row.id}.svg", alt=row.description)
