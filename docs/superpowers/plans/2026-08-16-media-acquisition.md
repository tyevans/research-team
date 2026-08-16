# Media Acquisition Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Media gets into the corpus by being found, judged and approved — not only by a person uploading a file.

**Architecture:** A deterministic three-stage chain of small model calls (needs → terms → judge) turns a topic into media *proposals*. A new `MediaProposals` aggregate holds them. Accepting one is a 202; a worker then downloads the asset, stores it through the existing `CorpusEditor.store_media`, and runs perception eagerly. A review pane groups proposals by the need they answer. A gated `fetch_media` tool shares the download primitive.

**Tech Stack:** Python 3.13, `eventsource-py` (decider aggregates, `DeclarativeProjection`, `SQLiteReadModelRepository`), `redstring`, `readeverything`, FastAPI, httpx, LangChain (behind a port only), React + TanStack Query, vitest.

**Spec:** `docs/superpowers/specs/2026-08-16-media-acquisition-design.md` — read it before Task 1. The plan argues from the spec; where they disagree, the spec wins and the plan is wrong.

## Global Constraints

- **Four gates, and passing three is not passing:** `uv run ruff check .`, `uv run ruff format --check .`, `uv run pytest`, and `cd frontend && npm run verify`. The two ruff commands run over the whole repository, not the files you touched.
- **Never run two `vitest` processes at once.** Concurrent runs fail spuriously with a coverage temp-file error naming nothing about the real cause.
- **A failure under load is not evidence until it reproduces alone.** Re-run a failing test in isolation, then re-run the whole suite. Two consecutive identical results is the bar.
- **Comments explain why, not what.** State costs and trade-offs, name what a test would fail on, and say when something was *measured* rather than reasoned. A comment restating the code is worse than none.
- **Commit messages carry the reasoning that does not fit in a comment** — what was considered and rejected, what the change costs, what is deliberately left undone.
- **If a test would pass with the change reverted, say so in its docstring.** Prove a test red before trusting it green.
- **Pre-release: no backwards compatibility is owed.** Break data, events and contracts rather than migrating — but say so in the field's docstring and update `tests/infrastructure/test_schema_evolution.py` to assert the refusal rather than deleting the case.
- **Application layer imports no framework.** `tests/test_architecture.py` enforces it. LangChain vocabulary stays in `infrastructure/`.
- **Do not use `with_structured_output`.** It appears nowhere in this repository. Ports return text; the application layer parses and tolerates junk. See `OntologyTextPort` (`application/ontology_discovery.py:267`).
- **Measured values in this plan came from one instance on 2026-08-15**: 262 image results, 91 video, 29 general. What generalises is the shape, not the ratios.
- **Never use bare `git stash` / `git stash pop`.** The stash stack is shared with the main checkout and every other worktree, and other sessions may push or pop concurrently — a bare pop can take someone else's entry. To prove a test red against pre-change code, prefer a temporary WIP commit (`git commit -m wip`, run, `git reset --soft HEAD~1`) or simply write the test first and run it before implementing. If you must stash, use `git stash push -u -m "<unique-tag>"`, capture the SHA from `git stash list --format='%H %gs'`, and restore with `git stash apply <sha>` — never `pop`.

---

## File Structure

**Created:**
- `research_team/domain/media_proposals.py` — events, commands, state, `decide`, `evolve`, `MediaProposals` aggregate.
- `research_team/application/media_curation.py` — ports, `MediaNeed`/`MediaCandidate`, the three stage parsers, `MediaCurationService`.
- `research_team/application/media_acquisition.py` — the download primitive and the accept worker.
- `research_team/infrastructure/agent/media_curation_adapter.py` — `MediaCurationTextPort` over a chat model; `MediaSearchPort` over SearXNG.
- `research_team/infrastructure/agent/fetch_media.py` — the gated tool.
- `frontend/src/presentation/research/MediaProposalPane.tsx`, `MediaProposalCard.tsx`, `IgnoredList.tsx`
- `frontend/src/application/research/use-media-proposals.ts`
- `frontend/src/infrastructure/http/media-proposal-repository.ts`

**Modified:**
- `research_team/infrastructure/agent/search.py` — extract `parse_results` from `format_results`.
- `research_team/infrastructure/persistence/read_models.py` — `MediaProposalRow`, `MediaProposalProjection`, `MediaProposalStore`, `MediaProposalRunner`.
- `research_team/composition.py` — construct the runner beside the other six; start it.
- `research_team/interfaces/web/app.py` — routes.
- `research_team/application/autonomy.py` — `FETCH_MEDIA_TOOL` in `GATED_TOOLS` and `TOOL_FLOORS`.
- `research_team/infrastructure/config.py` — `AGENT_CURATION_MODEL`.
- `docs/configuration.md` — the `image_proxy` prerequisite.
- `frontend/src/application/ports/repositories.ts`, `infrastructure/http/dto.ts`, `mappers.ts`.

---

# Wave 1 — Groundwork (PR 1)

## Task 1: Extract `parse_results` from `format_results`

**Files:**
- Modify: `research_team/infrastructure/agent/search.py:195-260`
- Test: `tests/infrastructure/test_search.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `SearchResult` (frozen dataclass) and `parse_results(payload: object, limit: int) -> tuple[SearchResult, ...] | None`. Returns `None` for a payload that is not a results object — the caller renders `_MALFORMED_PAYLOAD`. Fields: `title: str`, `url: str`, `snippet: str`, `kind: Literal["image", "video", "other"]`, `asset_url: str`, `detail: str`, `thumbnail_url: str`. All `str`, never `None`; absent becomes `""`.

**Why this task exists:** the chain needs `thumbnail_url` and `asset_url` as data. The model must never see `thumbnail_url` — it costs context and exists for the review pane. Consuming `format_results`' string to get it would mean re-parsing prose we just built.

- [ ] **Step 1: Write the failing test**

```python
def test_parse_results_carries_the_thumbnail_that_format_results_hides():
    """`thumbnail_url` is the whole reason this function is separate: the
    pane needs it and the model must not see it. Fails if `parse_results`
    is a thin wrapper that drops what `format_results` does not print.
    """
    parsed = parse_results({"results": [IMAGE_RESULT]}, limit=5)
    assert parsed[0].thumbnail_url == IMAGE_RESULT["thumbnail_src"]
    assert parsed[0].thumbnail_url not in format_results({"results": [IMAGE_RESULT]}, limit=5)


def test_parse_results_falls_back_through_thumbnail_then_asset():
    """`thumbnail_src` was absent on 46 of 262 captured image results and
    `thumbnail` is frequently an empty string, so the fallback is measured,
    not defensive.
    """
    no_src = {k: v for k, v in IMAGE_RESULT.items() if k != "thumbnail_src"}
    assert parse_results({"results": [{**no_src, "thumbnail": "https://t.example/x"}]}, limit=5)[
        0
    ].thumbnail_url == "https://t.example/x"
    assert (
        parse_results({"results": [{**no_src, "thumbnail": ""}]}, limit=5)[0].thumbnail_url
        == no_src["img_src"]
    )


def test_parse_results_returns_none_for_a_payload_that_is_not_a_results_object():
    for junk in ([], "oops", None):
        assert parse_results(junk, limit=5) is None
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/infrastructure/test_search.py -k parse_results -v`
Expected: FAIL, `cannot import name 'parse_results'`.

- [ ] **Step 3: Implement**

Add the dataclass and function above `format_results`; rewrite `format_results` to call `parse_results` and render. `_media_line` becomes a renderer over `SearchResult`. Keep `_text` and `_HIGHLIGHT` exactly as they are.

- [ ] **Step 4: Run the whole search suite**

Run: `uv run pytest tests/infrastructure/test_search.py -v`
Expected: all pass, including `test_a_text_result_renders_exactly_as_it_did_before_media_was_understood` — that test is the proof this refactor changed no output.

- [ ] **Step 5: Commit**

```bash
git add research_team/infrastructure/agent/search.py tests/infrastructure/test_search.py
git commit
```
Message must say: pure refactor, behaviour unchanged, and that the existing byte-identical test is the check.

---

## Task 2: The `MediaProposals` aggregate

**Files:**
- Create: `research_team/domain/media_proposals.py`
- Test: `tests/domain/test_media_proposals.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - Events: `MediaNeedsIdentified(project_id: str, topic_id: str, needs: str, model_version: str)` where `needs` is a JSON list of objects `{need_id, medium, description, why}`; `MediaProposed(project_id, proposal_id, need_id, topic_id, page_url, asset_url, thumbnail_url, kind, title, reason, query)`; `MediaProposalAccepted(proposal_id, ...)`; `MediaProposalRejected(proposal_id, note: str)`; `MediaProposalStored(proposal_id, source_id)`; `MediaProposalFailed(proposal_id, error)`; `MediaAssetIgnored(project_id, asset_key)`; `MediaAssetUnignored(project_id, asset_key)`; `MediaHostIgnored(project_id, host)`; `MediaHostUnignored(project_id, host)`.
  - Commands mirroring each.
  - `MediaProposalState` with `proposals: dict[str, ProposalRecord]`, `ignored_assets: frozenset[str]`, `ignored_hosts: frozenset[str]`.
  - `decide`, `evolve`, `initial_state`, and `class MediaProposals(DeciderAggregate[...])` with `aggregate_type = "MediaProposals"`.

**Mirror `research_team/domain/corpus.py` exactly** — `@register_event` on each event, frozen dataclass commands, module-level `decide`/`evolve`, and the aggregate binding them with `staticmethod` (`corpus.py:837-852`). Do not invent a different shape.

- [ ] **Step 1: Write the failing tests — the refusals**

```python
def test_accepting_a_proposal_twice_is_refused():
    state = _with(MediaProposed(...), MediaProposalAccepted(proposal_id="p1"))
    with pytest.raises(CommandRejectedError):
        decide(AcceptMediaProposal(proposal_id="p1"), state)


def test_accepting_a_rejected_proposal_is_refused():
    """A closed decision is closed. Distinct from the test below, which is
    about the *asset*, not this record."""
    state = _with(MediaProposed(...), MediaProposalRejected(proposal_id="p1", note=""))
    with pytest.raises(CommandRejectedError):
        decide(AcceptMediaProposal(proposal_id="p1"), state)


def test_a_command_naming_an_unknown_proposal_is_refused():
    with pytest.raises(CommandRejectedError):
        decide(AcceptMediaProposal(proposal_id="nope"), initial_state())
```

- [ ] **Step 2: Write the failing test that pins what is NOT refused**

This is the most important test in the task. It is what stops someone later "fixing" rejection back into a blacklist.

```python
def test_a_previously_rejected_asset_may_be_proposed_again():
    """Rejecting closes one proposal; it does not blacklist the asset.
    Ignoring is the explicit forever, and is a different command.

    This test fails if `decide` grows a guard against re-proposing a
    rejected asset -- which reads like a sensible addition and is the bug
    this spec exists to prevent.
    """
    state = _with(
        MediaProposed(proposal_id="p1", asset_url="https://a.example/x.jpg", ...),
        MediaProposalRejected(proposal_id="p1", note=""),
    )
    events = decide(
        ProposeMedia(proposal_id="p2", asset_url="https://a.example/x.jpg", ...), state
    )
    assert isinstance(events[0], MediaProposed)
```

- [ ] **Step 3: Write the failing tests — ignoring**

```python
def test_an_ignored_asset_is_refused_a_new_proposal():
    state = _with(MediaAssetIgnored(asset_key="https://a.example/x.jpg"))
    with pytest.raises(CommandRejectedError):
        decide(ProposeMedia(asset_url="https://a.example/x.jpg", ...), state)


def test_unignoring_lets_it_be_proposed_again():
    state = _with(
        MediaAssetIgnored(asset_key="https://a.example/x.jpg"),
        MediaAssetUnignored(asset_key="https://a.example/x.jpg"),
    )
    assert decide(ProposeMedia(asset_url="https://a.example/x.jpg", ...), state)


def test_an_ignored_host_does_not_cover_a_sibling_subdomain():
    """No suffix matching, for `FetchGrant`'s stated reason: public-suffix
    knowledge this project does not have. A blacklist that quietly covers
    more than it says is invisible from every direction, so this is pinned.
    """
    state = _with(MediaHostIgnored(host="example.com"))
    assert decide(ProposeMedia(asset_url="https://cdn.example.com/x.jpg", ...), state)
```

- [ ] **Step 4: Run to verify all fail**

Run: `uv run pytest tests/domain/test_media_proposals.py -v`
Expected: every test fails on import — the module does not exist.

- [ ] **Step 5: Implement the module**

`decide` uses `normalize_url` for the asset key and `urlsplit(...).hostname` (lowercased) for the host. Import `normalize_url` from `research_team.infrastructure.agent.recall`— **no**: that would make domain import infrastructure. Move `normalize_url` to `research_team/domain/urls.py` and re-export it from `recall.py` so existing callers are untouched. Note this move in the commit message.

- [ ] **Step 6: Run tests, then the architecture test**

Run: `uv run pytest tests/domain/test_media_proposals.py tests/test_architecture.py -v`
Expected: PASS. The architecture test is what catches the import-direction mistake above.

- [ ] **Step 7: Commit**

---

## Task 3: Schema evolution case

**Files:**
- Modify: `tests/infrastructure/test_schema_evolution.py`

- [ ] **Step 1:** Add a case writing an old-shaped `MediaProposed` payload (without `thumbnail_url`) directly into the events table and reading it back, asserting it loads with `thumbnail_url == ""`. Run it, watch it fail if the field is required, then give the field a default.
- [ ] **Step 2:** Commit.

**PR 1 opens here.** Title: "Groundwork for media acquisition: parseable results and a proposal aggregate". Body must state that nothing is wired yet — no route, no projection, no chain — and that this is deliberately inert.

---

# Wave 2 — The chain, projection and routes (PR 2)

## Task 4: The curation ports and stage parsers

**Files:**
- Create: `research_team/application/media_curation.py`
- Test: `tests/application/test_media_curation.py`

**Interfaces:**
- Consumes: `SearchResult` from Task 1.
- Produces: `MediaCurationTextPort` (Protocol: `model_name: str`, `async generate(prompt: str) -> str`); `MediaSearchPort` (Protocol: `async search(query: str, categories: str) -> tuple[SearchResult, ...]`); `MediaNeed(need_id, medium, description, why)`; `MediaCandidate(need_id, result: SearchResult, reason: str)`; `parse_needs(text) -> tuple[list[MediaNeed], int]`; `parse_terms(text) -> tuple[list[Query], int]`; `parse_judgements(text) -> tuple[list[Judgement], int]`. Each parser returns `(items, rejected_count)`.

**Bounds** (module constants, each with a docstring giving the reasoning the way `MAX_SEARCHES_PER_TURN` does): `MAX_NEEDS_PER_TOPIC = 4`, `MAX_QUERIES_PER_NEED = 2`, `MAX_CANDIDATES_PER_NEED = 3`. Worst case 8 searches and 24 candidates per invocation. State in the docstrings that these are guesses, and that they are constants so being wrong is visible and cheap.

- [ ] **Step 1: Write the failing parser tests**

```python
def test_parse_needs_drops_an_item_missing_its_description_and_counts_it():
    needs, rejected = parse_needs('[{"medium":"image","description":"","why":"x"},'
                                  '{"medium":"image","description":"A map","why":"y"}]')
    assert [n.description for n in needs] == ["A map"]
    assert rejected == 1


def test_parse_needs_returns_nothing_for_prose_instead_of_json():
    """A model that answers in prose is a legitimate outcome, not an error:
    a topic can genuinely want no imagery, and a parser that raised would
    make the chain fail where it should return nothing."""
    needs, rejected = parse_needs("I don't think this topic needs images.")
    assert needs == []


def test_parse_needs_honours_the_cap():
    needs, _ = parse_needs(json.dumps([_need(i) for i in range(10)]))
    assert len(needs) == MAX_NEEDS_PER_TOPIC
```

Write the equivalent three for `parse_terms` and `parse_judgements`.

- [ ] **Step 2: Run to verify they fail.** `uv run pytest tests/application/test_media_curation.py -v`
- [ ] **Step 3: Implement the parsers.** Mirror `_members_from` in `application/ontology_discovery.py:240-265` — tolerate junk, count rejects, never raise.
- [ ] **Step 4: Run tests.** Expected: PASS.
- [ ] **Step 5: Commit.**

---

## Task 5: `MediaCurationService`

**Files:**
- Modify: `research_team/application/media_curation.py`
- Test: `tests/application/test_media_curation.py`

**Interfaces:**
- Consumes: `TopicReadPort` (`application/topic_read.py:88`) — its view carries `question`, `scope`, `sub_questions`, `findings`, `source_ids`.
- Produces: `MediaCurationService.curate(project_id: UUID, topic_id: UUID) -> CurationOutcome` with `CurationOutcome(needs: int, candidates: int, ignored: int, rejected_parses: int)`.

**Corrected mid-execution.** The first draft of this task passed only a topic
*id* and left stage 1's prompt with nothing to reason about — the chain would
have asked a model what imagery serves a topic it cannot see, making every
later stage garbage-in. The spec always said the prompt carries the topic's
question, scope and findings; the plan simply failed to wire the port that
already existed. A test must assert the topic's question reaches the text
port's prompt, not merely that `curate` returns something — the weaker
assertion passes with the port unwired, which is the whole defect.

**The fake port is six lines**, per `OntologyTextPort`'s reasoning — a list of canned responses returned in order. Do not mock a chat model.

- [ ] **Step 1: Write the failing test that the filter runs between search and judging**

```python
async def test_an_ignored_asset_is_filtered_before_the_judging_call():
    """Filtering after search and before stage 3 is what stops us paying a
    model call for candidates already excluded -- and what makes the count
    reportable. Fails if the filter moves to proposal time: the judge port
    would then see three candidates rather than two.
    """
    port = FakeTextPort([_needs_json(1), _terms_json(1), _judgements_json(2)])
    search = FakeSearchPort([_result("https://bad.example/x.jpg"), _result("https://ok.example/y.jpg")])
    outcome = await service(port, search, ignored_hosts={"bad.example"}).curate(project, topic)
    assert outcome.ignored == 1
    assert len(port.prompts[2].split("https://")) == 2  # one candidate reached the judge
```

- [ ] **Step 2: Write the failing test that needs are recorded before searching**

```python
async def test_needs_are_recorded_even_when_every_search_returns_nothing():
    """The one structural cost in the chain, and the thing it buys: "we
    looked for a gradient diagram and found none" is a fact rather than a
    silence. Fails if needs are only written alongside proposals.
    """
    outcome = await service(port, FakeSearchPort([])).curate(project, topic)
    assert outcome.needs == 2
    assert outcome.candidates == 0
    assert any(isinstance(e, MediaNeedsIdentified) for e in appended)
```

- [ ] **Step 3: Run to verify they fail.**
- [ ] **Step 4: Implement.** Stage 1 one call; stage 2 one call per need; searches; filter; stage 3 one call per need. Record `MediaNeedsIdentified` before any search.
- [ ] **Step 5: Run tests.** **Step 6: Commit.**

---

## Task 6: The infrastructure adapters

**Files:**
- Create: `research_team/infrastructure/agent/media_curation_adapter.py`
- Modify: `research_team/infrastructure/config.py`
- Test: `tests/infrastructure/test_media_curation_adapter.py`

**Interfaces:**
- Produces: `build_curation_ports(...) -> tuple[MediaCurationTextPort, MediaSearchPort]`; `config.curation_model() -> str`.

`curation_model()` reads `AGENT_CURATION_MODEL`, defaulting to `model_name()`. Give it the docstring `embedding_model()` has (`config.py:433-451`) — a distinct role gets a distinct model, and defaulting to the chat model is a convenience, not a claim they are the same thing.

The `MediaSearchPort` implementation calls `parse_results`, **not** `format_results`, and passes `categories` through unvalidated the way `build_search_tool` does. It does not use `Recall` and does not touch `SearchAttempts`: those bound a model's own searching within a turn, and this is a fixed pipeline whose call count is already bounded by Task 4's constants.

- [ ] **Step 1:** Test that the search port returns `SearchResult`s from a stubbed `httpx` transport (mirror `_client(handler)` in `tests/infrastructure/test_search.py:33`). **Step 2:** Verify red. **Step 3:** Implement. **Step 4:** Green. **Step 5:** Commit.

---

## Task 7: `MediaProposalRow`, projection, store, runner

**Files:**
- Modify: `research_team/infrastructure/persistence/read_models.py`
- Test: `tests/infrastructure/test_media_proposal_read_model.py`

**Interfaces:**
- Produces: `MediaProposalRow(ReadModel)`, `MediaProposalProjection(DeclarativeProjection)`, `MediaProposalStore`, `MediaProposalRunner`.

Mirror `OntologyRunner` (`read_models.py:2122-2196`) exactly, including touching the event store first so `projection_checkpoints` exists before anything reads it. Add a `project_id` index in `MediaProposalStore.open` — `apply_schema` reconciles columns and not indexes, and every read here is by project.

- [ ] **Step 1: Write the failing test — the row, not the request**

```python
async def test_a_proposal_lands_as_a_row_carrying_the_reason_the_chain_wrote():
    """Asserts the *data*, never that the machinery didn't throw.

    An event no projection handles counts as APPLIED, not rejected --
    `eventsource.replay`'s docstring says so. So an assertion that "the
    request succeeded" passes with this projection deleted entirely and is
    worthless as a test of it. This is how `EntityDefinitionRunner` shipped
    missing from `composition.py` behind a green suite.
    """
    await store.projection.handle(MediaProposed(proposal_id="p1", reason="Shows the gradient", ...))
    rows = await store.for_project(project_id)
    assert [r.reason for r in rows] == ["Shows the gradient"]
```

- [ ] **Step 2:** Verify red. **Step 3:** Implement row, projection, store, runner. **Step 4:** Green.
- [ ] **Step 5: Open it against a database that predates the change**

```bash
uv run python -m research_team.infrastructure.persistence.local_copy /tmp/probe.db
```

Then start the app against `AGENT_DB=/tmp/probe.db` and hit the proposals route. "It works on my fresh database" is the sound of the read-model bug this repo has already shipped once. Record in the commit message that this was done and what was seen.

- [ ] **Step 6: Commit.**

---

## Task 8: Wire the runner into `composition.py`

**Files:**
- Modify: `research_team/composition.py:780-812` and its `start()`
- Test: `tests/integration/test_media_proposals_reach_the_read_model.py`

- [ ] **Step 1: Write the failing integration test.** Drive a curation through the composed application and assert a row exists with the chain's reason. This is the test that fails if the runner is constructed but never started, or started but never constructed.
- [ ] **Step 2:** Verify red. **Step 3:** Construct `MediaProposalRunner` beside the other six, with a comment saying why it lives there — "a projection wired somewhere else is a projection somebody forgets to start" is the existing reasoning at `composition.py:787-789`. Add it to `start()`. **Step 4:** Green. **Step 5:** Commit.

---

## Task 9: Routes

**Files:**
- Modify: `research_team/interfaces/web/app.py`
- Test: `tests/interfaces/test_media_proposal_routes.py`

**Routes:**
- `POST /api/projects/{project_id}/topics/{topic_id}/media-proposals` → runs the chain, 202, returns the outcome counts.
- `GET /api/projects/{project_id}/media-proposals` → rows grouped by need.
- `POST …/media-proposals/{proposal_id}/accept` → 202.
- `POST …/media-proposals/{proposal_id}/reject` → 200, optional `{"note": "..."}`.
- `POST …/media-proposals/{proposal_id}/ignore` → 200, body `{"grain": "asset" | "host"}`.
- `DELETE /api/projects/{project_id}/ignored/{grain}/{key}` → 200.
- `GET /api/projects/{project_id}/ignored` → the two lists.

**Every route maps `CommandRejectedError` to 409.** B95 records two existing routes that do not, and answer 500 for a refusal the domain states clearly. Do not add a third.

- [ ] **Step 1:** Write a failing test per route, including one asserting a refused accept answers **409 and not 500**. **Step 2:** Verify red. **Step 3:** Implement. **Step 4:** Green. **Step 5:** Commit.

**PR 2 opens here.** Title: "The media curation chain, its projection and routes".

---

# Wave 3 — Accept path, pane, tool (PR 3)

## Task 10: The download primitive

**Files:**
- Create: `research_team/application/media_acquisition.py`
- Test: `tests/application/test_media_acquisition.py`

**Interfaces:**
- Produces: `async download_media(url, *, client, max_bytes) -> tuple[AsyncIterator[bytes], str]` raising `UnsupportedMedia(media_type)` and `MediaTooLarge(total)`.

Refuses any content-type outside `image/*`, `video/*`, `audio/*`. Reuses `MAX_UPLOAD_BYTES` and the chunking shape in `app.py:1061-1072` — do not invent a second ceiling.

- [ ] **Step 1: Write the failing test**

```python
async def test_an_html_interstitial_is_a_failure_and_not_a_source():
    """A judged candidate whose URL serves a login page must not become a
    corpus row whose bytes are HTML and whose transcript is empty."""
    with pytest.raises(UnsupportedMedia):
        await download_media("https://a.example/x.jpg", client=_html_client())
```

- [ ] **Step 2:** Verify red. **Step 3:** Implement. **Step 4:** Green. **Step 5:** Commit.

---

## Task 11: The accept worker

**Files:**
- Modify: `research_team/application/media_acquisition.py`
- Test: `tests/application/test_media_acquisition.py`

- [ ] **Step 1: Write the failing tests**

```python
async def test_an_accepted_proposal_becomes_a_source_carrying_its_page_url():
    """`uri` is the page, not the asset: provenance is where it was found,
    not the CDN path it happened to be served from."""
    await worker.run(proposal_id="p1")
    assert (await corpus.get("...")).uri == "https://example.org/gallery/trajan"


async def test_a_failed_download_records_why_and_leaves_the_proposal_visible():
    """A proposal that vanishes on failure is one nobody can retry or
    understand. Fails if the worker swallows the error."""
    await worker.run(proposal_id="p1")
    assert isinstance(appended[-1], MediaProposalFailed)
```

- [ ] **Step 2:** Verify red. **Step 3:** Implement: download → `store_media` → perception → `MediaProposalStored`. **Step 4:** Green. **Step 5:** Commit.

---

## Task 11b: Wire the worker to the accept route

**Added mid-execution — the plan had no task for this**, and without it the
whole wave is inert: Task 9's accept route appends `MediaProposalAccepted` and
answers 202, Task 11 built a worker that nobody starts, and the two never meet.
Every test in both tasks passes with them unconnected, which is exactly the
class of gap `CLAUDE.md` warns about — the machinery works and the feature does
not exist.

**Files:**
- Modify: `research_team/composition.py`, `research_team/interfaces/web/app.py`
- Test: `tests/integration/test_accepting_a_proposal_acquires_it.py`

- [ ] **Step 1: Write the failing integration test.** Accept a proposal
  through the composed application, then assert a corpus source exists whose
  `uri` is the proposal's page URL. Not that the route answered 202 — that
  passes today, with no worker in the world.
- [ ] **Step 2:** Verify red.
- [ ] **Step 3:** Construct `MediaAcceptWorker` in `composition.py` beside the
  projections, and have the accept route hand off to it. Acceptance stays a
  202: the route records the decision and returns; the download must not block
  the response, because an hour of audio is minutes of perception.
- [ ] **Step 4:** Green. **Step 5:** Commit.

---

## Task 12: The review pane

**Files:**
- Create: `frontend/src/presentation/research/MediaProposalPane.tsx`, `MediaProposalCard.tsx`, `IgnoredList.tsx`, `frontend/src/application/research/use-media-proposals.ts`, `frontend/src/infrastructure/http/media-proposal-repository.ts`
- Modify: `frontend/src/application/ports/repositories.ts`, `infrastructure/http/dto.ts`, `mappers.ts`
- Test: `frontend/src/presentation/research/MediaProposalPane.test.tsx`

Mirror `DocumentManagePane.tsx` and `use-documents.ts` for the repository/query seam. Reject is the primary action on the card; ignore is secondary with an asset/host choice.

- [ ] **Step 1: Write the failing tests** — proposals render grouped under their need's sentence; an accepted card shows a working state until stored (B94 is the inverse failure already in this codebase); the ignored list renders with an undo.
- [ ] **Step 2:** Verify red. **Step 3:** Implement. **Step 4:** `cd frontend && npm run verify`. Nothing here is a computed style, so `test:browser` is not indicated. **Step 5:** Commit.

---

## Task 13: `fetch_media` and its floor

**Files:**
- Create: `research_team/infrastructure/agent/fetch_media.py`
- Modify: `research_team/application/autonomy.py:27-65`
- Test: `tests/application/test_autonomy.py`, `tests/infrastructure/test_fetch_media.py`

Last on purpose: it shares Task 10's primitive, and building it earlier would mean writing that twice or in the wrong place.

- [ ] **Step 1: Write the failing policy tests**

```python
def test_fetch_media_floors_at_ask():
    assert AutonomyPolicy(default="auto").level_for(FETCH_MEDIA_TOOL) == "ask"


def test_an_explicit_setting_still_wins_in_both_directions():
    """A floor raises a default and never lowers it; someone who turns this
    to `auto` for a research session meant it."""
    policy = AutonomyPolicy(default="auto")
    policy.set(FETCH_MEDIA_TOOL, "auto")
    assert policy.level_for(FETCH_MEDIA_TOOL) == "auto"


def test_relax_all_sweeps_it_in():
    """Intended, and stated rather than inherited: this is the first tool
    where "allow all" means megabytes and a perception pass."""
    assert FETCH_MEDIA_TOOL in AutonomyPolicy().relax_all()
```

- [ ] **Step 2:** Verify red. **Step 3:** Implement. **Step 4:** Green. **Step 5:** Commit.

---

## Task 14: Documentation

**Files:**
- Modify: `docs/configuration.md`, `README.md`

- [ ] **Step 1:** Document `AGENT_CURATION_MODEL` and the **`image_proxy: true` prerequisite** — measured 2026-08-15: the instance returns raw third-party thumbnail URLs, so without it the review pane hotlinks the viewer's browser to whoever indexed the image. State that this is a deployment setting the code cannot enforce, and that the rejected alternative was a proxy endpoint of our own (an SSRF surface for a feature that does not need one).
- [ ] **Step 2:** Commit.

**PR 3 opens here.** Title: "Accepting a media proposal, and the pane that does it".

---

## Self-Review

**Spec coverage.** Chain → Tasks 4-6. Aggregate and the reject/ignore split → Task 2. Accept path → Tasks 10-11. Read model and the APPLIED trap → Tasks 7-8. Pane → Task 12. Tool and permissions → Task 13. Thumbnails/`image_proxy` → Tasks 1 (fallback chain) and 14 (prerequisite). Slicing section → the three waves.

**Gaps found and closed while reviewing:** the spec's fixture rule — that at least one test must start from a fixture which has *not* opened the project itself — was unassigned; it belongs to Task 8's integration test and is now stated there. The spec's `normalize_url` reuse implied a domain→infrastructure import, which `tests/test_architecture.py` forbids; Task 2 Step 5 now moves it to `domain/urls.py`.

**Known thin spots**, stated rather than hidden: Task 12's steps are less granular than the backend tasks because the component shapes depend on what `DocumentManagePane` looks like when it is reached, and Task 6's step list is compressed for the same reason. An executor should expand them rather than treat brevity as permission to skip tests.
