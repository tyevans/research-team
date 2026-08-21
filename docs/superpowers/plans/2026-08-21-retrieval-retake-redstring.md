# Redundant Tail Chunk (redstring) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop `SlidingWindowChunker` emitting a final chunk that is wholly contained in the previous one.

**Architecture:** One change inside `_generate_chunks`' loop: once a chunk's `end` reaches the end of the text, there is nothing left to cover, so the loop stops. Today it continues because the loop's only exit test is on `next_start`, which is still short of the end by exactly `overlap`.

**Tech Stack:** Python, `uv`, pytest. Repository: `~/workspace/redstring` (a *different* repository from research-team).

**Spec:** `~/workspace/rt-retrieval-retake/docs/superpowers/specs/2026-08-21-retrieval-retake-design.md`, Part 0 ("`SlidingWindowChunker` emits a wholly-redundant tail chunk") and Part VIII ("PR 3").

## Global Constraints

- **This is redstring, not research-team.** Do not run research-team's gates here or vice versa. Find redstring's own gates in its `CLAUDE.md`, `.pre-commit-config.yaml` and CI workflow before starting, and run those.
- **Work in a worktree.** `cd ~/workspace/redstring && git worktree add -b sliding-window-tail ../redstring-sliding-tail`. Do not switch branches in `~/workspace/redstring` itself.
- **redstring is pre-1.0 with a stated no-shim policy**, and this changes chunk *counts* for every consumer. It does not change chunk ids, stored identity, or the text any surviving chunk carries -- say exactly that in the PR description so a downstream reader does not assume a re-index is needed.
- **Prove the test red before trusting it green.**

---

### Task 1: Fix the tail chunk

**Files:**
- Modify: `src/redstring/extraction/chunkers/sliding_window_chunker.py` (`_generate_chunks`, the loop at lines 212-252)
- Test: `tests/unit/extraction/test_chunkers.py`

**Interfaces:**
- Consumes: `SlidingWindowChunker(default_chunk_size, default_overlap).chunk(text) -> ChunkingResult`, whose `.chunks` is a list of `Chunk` with `start_char`, `end_char`, `text`, `chunk_index`, `overlap_with_previous`.
- Produces: no signature change. `chunk()` returns one fewer chunk for any text longer than the window.

- [ ] **Step 1: Write the failing test**

```python
@pytest.mark.parametrize("length", [1350, 1800, 2700, 4500])
def test_no_chunk_is_wholly_contained_in_another(length: int) -> None:
    """The last window is emitted even when the previous one reached the end.

    `end` is clamped to `text_len`, so a chunk can finish at the end of the
    document -- but the loop's only exit test is `text_len - next_start <= 0`,
    and `next_start` is `end - overlap`, which is still `overlap` short. So one
    more window is emitted at `(text_len - overlap, text_len)`, wholly inside
    the chunk just yielded.

    It buys nothing: every term in it is already in the containing chunk, so it
    adds no retrieval reach, while costing a row, an embedding call, and a
    second draw for the tail's terms under any max-aggregating ranker.

    Parametrised over length rather than asserted on one document because the
    two formulas -- "stop when nothing remains" and "stop when a chunk reached
    the end" -- agree on every text at or under the window size, which is
    where a hand-picked example would most likely land.
    """
    text = "The quick brown fox jumps over the lazy dog. " * (length // 44)
    chunks = SlidingWindowChunker(
        default_chunk_size=1000, default_overlap=500
    ).chunk(text).chunks

    spans = [(chunk.start_char, chunk.end_char) for chunk in chunks]
    contained = [
        (inner, outer)
        for inner in spans
        for outer in spans
        if inner != outer and outer[0] <= inner[0] and inner[1] <= outer[1]
    ]
    assert contained == [], f"chunks wholly inside another: {contained}"


def test_a_document_shorter_than_the_window_is_one_chunk() -> None:
    """The guard against fixing the tail by dropping it.

    A text at or under the window size must still be exactly one chunk
    covering all of it. This passes before and after the fix; it is here so
    that a fix which stops the loop too early fails something.
    """
    text = "a" * 900
    chunks = SlidingWindowChunker(
        default_chunk_size=1000, default_overlap=500
    ).chunk(text).chunks
    assert len(chunks) == 1
    assert (chunks[0].start_char, chunks[0].end_char) == (0, 900)


def test_the_tail_of_a_long_document_is_still_covered() -> None:
    """The other guard: the fix must not reintroduce a dropped tail.

    That regression has happened here before -- the loop carries a comment
    about a version that stopped early when the remainder was shorter than
    `min_chunk_size` and silently lost a document's closing sentence. This
    asserts the last character is inside some chunk.
    """
    text = "The quick brown fox jumps over the lazy dog. " * 60
    chunks = SlidingWindowChunker(
        default_chunk_size=1000, default_overlap=500
    ).chunk(text).chunks
    assert max(chunk.end_char for chunk in chunks) == len(text)
    assert "".join(text[c.start_char:c.end_char] for c in chunks[:1]) == chunks[0].text
```

Import `SlidingWindowChunker` and `pytest` the way the rest of `test_chunkers.py` does -- read the file's existing imports rather than adding your own style.

- [ ] **Step 2: Run to verify the first test fails and the other two pass**

```
cd ~/workspace/redstring-sliding-tail
uv run pytest tests/unit/extraction/test_chunkers.py -k "wholly_contained or shorter_than_the_window or tail_of_a_long" -v
```

Expected: `test_no_chunk_is_wholly_contained_in_another` FAILS on all four lengths; the two guards PASS.

- [ ] **Step 3: Fix the loop**

In `src/redstring/extraction/chunkers/sliding_window_chunker.py`, inside `_generate_chunks`, immediately after the `yield Chunk(...)` and before `next_start = end - overlap`, add:

```python
            # Nothing is left once a chunk reaches the end of the text, and
            # the exit test below cannot see that: it is on `next_start`,
            # which is `end - overlap` and so still `overlap` short of the
            # end. Without this, a document longer than the window always got
            # one final window at `(text_len - overlap, text_len)` -- wholly
            # inside the chunk just yielded, adding no reach while costing a
            # row, an embedding call, and a second draw for the tail's terms
            # under any max-aggregating ranker.
            #
            # This does not drop a tail; the chunk just yielded ends at
            # `text_len`. The tail-dropping regression the comment below
            # guards against was a different thing -- stopping before
            # emitting a short *remainder*.
            if end >= text_len:
                break
```

- [ ] **Step 4: Run the three tests again**

```
uv run pytest tests/unit/extraction/test_chunkers.py -k "wholly_contained or shorter_than_the_window or tail_of_a_long" -v
```

Expected: all PASS.

- [ ] **Step 5: Run the chunker suites, then the whole suite**

```
uv run pytest tests/unit/extraction/ -v
uv run pytest
```

Expected: existing tests that assert an exact chunk *count* for a document longer than the window will fail, by exactly one. That is the fix working. Update each such assertion and say in its docstring that the count dropped by one because the redundant tail chunk is gone -- do not weaken an assertion to a range to make it pass.

Any test asserting on chunk *text* or *coverage* that fails is a real regression: stop and re-read Step 3.

- [ ] **Step 6: Run redstring's own gates**

Whatever `CLAUDE.md` / `.pre-commit-config.yaml` / CI define. At minimum:

```
uv run ruff check . && uv run ruff format --check . && uv run pytest
```

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "SlidingWindowChunker: stop once a chunk reaches the end of the text

A document longer than the window always got one final chunk at
(text_len - overlap, text_len), wholly contained in the chunk just yielded.
The loop's only exit test is on next_start, which is end - overlap and so
still overlap short of the end, so a chunk finishing exactly at text_len did
not stop it.

The redundant chunk buys nothing -- every term in it is already in the
containing chunk -- while costing a row, an embedding call, and a second draw
for the tail's terms under any max-aggregating ranker. Downstream, a consumer
deduplicating passages by offset cannot collapse it, because the two spans
differ.

Found by stark-bench (B-SLIDING-REDUNDANT-1) and measured at 1000/500 across
450-4500 characters: exactly one redundant chunk, always the last, for every
document longer than the window; documents at or under it were unaffected.

Two guard tests come with the fix, because the obvious wrong version of it
drops a real tail -- this loop already carries a comment about a version that
stopped early when the remainder was shorter than min_chunk_size and lost a
document's closing sentence.

Chunk counts drop by one for texts longer than the window. Chunk ids, stored
identity and the text of every surviving chunk are unchanged, so no consumer
needs a re-index."
```

- [ ] **Step 8: Open the PR**

Body must state: what changed, that counts drop by one for long documents, and that ids and text are unchanged so no re-index is needed. Link stark-bench's `B-SLIDING-REDUNDANT-1`.

---

## Self-Review

**Spec coverage.** The spec's Part VIII names exactly one redstring PR after the correction that dropped the chunk-id change (redstring's B161 had already rejected that fix, and its reasoning holds). This plan is that PR.

**Placeholder scan.** No TBDs. Step 5 says "update each such assertion" without naming files because the failing set is not knowable until the fix runs -- it is paired with a concrete rule (adjust the count, say why, never weaken to a range) rather than left open.

**Type consistency.** No new types. `Chunk`, `ChunkingResult` and `SlidingWindowChunker` are used with the field and method names verified against the installed 0.9.2 while writing the spec.
