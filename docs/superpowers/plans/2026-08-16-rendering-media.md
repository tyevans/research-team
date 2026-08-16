# Rendering Media Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prose can point at a source, and at a moment inside it, and the reader gets a player seeked there.

**Architecture:** The model emits `[[src:id@252]]` — an identifier and an integer, never a URL. A pure pre-pass over the markdown source converts valid references into anchors whose hrefs *this code* builds, before the existing single sanitisation point runs unchanged. Citations, which carry `{sourceId, start, end}` and no offset, get their moment from `locators.resolve` — its first production caller.

**Tech Stack:** React + TanStack Query + `marked` + DOMPurify, Python 3.13, `eventsource-py`.

**Spec:** `docs/superpowers/specs/2026-08-16-rendering-media-design.md` — read it before Task 1.

## Global Constraints

- **Four gates:** `uv run ruff check .`, `uv run ruff format --check .`, `uv run pytest`, and `cd frontend && npm run verify`. The ruff commands cover the whole repository. Run `verify` as a chain — the prettier check and the bundle budget exist only there and are the two that fail in CI.
- **Never run two `vitest` processes at once.** Concurrent runs fail spuriously with a coverage temp-file error naming nothing about the real cause.
- **`dangerouslySetInnerHTML` must still appear exactly once in the application** when this plan is finished. That is the property `presentation/common/content.tsx` was built to make grep-checkable, and it is worth more than this feature. Any task that would add a second is wrong and should stop and say so.
- **Rebuild and commit `research_team/interfaces/web/static/assets/app.js` and `index.css`** with any frontend change — they are tracked, and an uncommitted rebuild means the server serves a bundle without the change.
- **Never use bare `git stash` / `git stash pop`** — the stash stack is shared with the main checkout and every other worktree. Use a throwaway WIP commit, or write the test first and run it before implementing.
- **Commit in a single invocation** with explicit paths: `git add <paths> && git commit -F <file>`. Never `git add -A`.
- Comments explain why, not what. Say when something was measured rather than reasoned.
- Prove each test red before trusting it green. If a test would pass with the change reverted, say so in its docstring.
- This project is pre-release: no backwards compatibility is owed, but a deliberate break is documented in the field's docstring.

---

## Task 1: The reference pre-pass

**Files:**
- Create: `frontend/src/infrastructure/rendering/references.ts`
- Test: `frontend/src/infrastructure/rendering/references.test.ts`

**Interfaces:**
- Produces: `expandReferences(source: string, projectId: ProjectId): string` — markdown in, markdown out, with valid references replaced by anchors.

A pure string function with no React and no network. It is the whole security surface of this feature, so it is built and tested alone before anything renders it.

Grammar: `[[src:<id>]]`, `[[src:<id>@<seconds>]]`, `[[src:<id>@<start>-<end>]]`. `<id>` is restricted to the charset `source_id` already permits; `<seconds>` is a non-negative integer.

**Every invalid case renders as its literal text.** Not an error, not a blank, not a partial link — the literal characters the model wrote, so a reader can report it and a developer can grep for it.

- [ ] **Step 1: Write the failing tests**

```ts
it('links a bare source reference', () => {
  expect(expandReferences('see [[src:wiki-trajan]] for more', projectId))
    .toContain('href="/projects/' + projectId + '/doc/wiki-trajan"')
})

it('carries a point offset as a media fragment', () => {
  expect(expandReferences('[[src:keynote@252]]', projectId)).toContain('#t=252')
})

it('carries a range offset', () => {
  expect(expandReferences('[[src:keynote@252-310]]', projectId)).toContain('#t=252,310')
})

it.each([
  ['[[src:]]', 'empty id'],
  ['[[src:a b]]', 'space in id'],
  ['[[src:../../etc/passwd]]', 'traversal'],
  ['[[src:x"onmouseover=y]]', 'quote breaking out of the attribute'],
  ['[[src:x@notanumber]]', 'non-integer offset'],
  ['[[src:x@-5]]', 'negative offset'],
])('renders %s as literal text (%s)', (input) => {
  const out = expandReferences(input, projectId)
  expect(out).toBe(input)
  expect(out).not.toContain('<a')
})

it('leaves a reference inside a code fence alone', () => {
  // A code block showing the syntax is documentation, not a link. Fails if
  // the pre-pass regexes the whole string without tracking fences.
  const source = '```\n[[src:keynote@252]]\n```'
  expect(expandReferences(source, projectId)).toBe(source)
})

it('leaves a reference in inline code alone', () => {
  expect(expandReferences('`[[src:keynote]]`', projectId)).toBe('`[[src:keynote]]`')
})
```

- [ ] **Step 2: Run to verify they fail.** `cd frontend && npx vitest run src/infrastructure/rendering/references.test.ts`
- [ ] **Step 3: Implement.** Build the href from validated parts only — mirror how `projectHref` constructs one; never interpolate raw model text into markup.
- [ ] **Step 4: Green.** **Step 5: Commit.**

---

## Task 2: Wire it into `Markdown`

**Files:**
- Modify: `frontend/src/presentation/common/content.tsx`
- Test: `frontend/src/presentation/common/content.test.tsx`

**Interfaces:**
- Consumes: `expandReferences` from Task 1.

`Markdown` is memoised on its source because a conversation re-renders on every stream frame and re-parsing each time is "the difference between a smooth log and a stuttering one". **The pre-pass goes inside that same memo**, not in a separate one and not in the caller — two memos over one input is two chances to invalidate differently.

`Markdown` takes a `projectId`, since the href needs one. Where a caller has no project, references do not resolve and render as literal text; say which callers those are in the commit message.

- [ ] **Step 1: Write the failing tests**

```tsx
it('renders a reference as a link to the source', async () => {
  render(<Markdown source="see [[src:keynote@252]]" projectId={projectId} />)
  expect(screen.getByRole('link')).toHaveAttribute('href', expect.stringContaining('#t=252'))
})

it('cannot produce an href the sanitiser would reject', () => {
  // The claim is about what reaches the page, so this asserts on the rendered
  // DOM rather than on expandReferences' output. Fails if the pre-pass is ever
  // moved after sanitisation.
  render(<Markdown source={'[[src:javascript:alert(1)]]'} projectId={projectId} />)
  expect(screen.queryByRole('link')).not.toBeInTheDocument()
  expect(screen.getByText(/\[\[src:javascript/)).toBeInTheDocument()
})
```

- [ ] **Step 2:** Verify red. **Step 3:** Implement. **Step 4:** Green.
- [ ] **Step 5: Confirm the invariant holds.** Run `grep -rn "dangerouslySetInnerHTML" frontend/src` and paste the output in the report — it must still be exactly one occurrence.
- [ ] **Step 6:** `cd frontend && npm run verify`, rebuild and commit the built assets. **Step 7: Commit.**

---

## Task 3: Resolve a citation's span to a moment

**Files:**
- Modify: `research_team/application/entity_definitions.py`, `research_team/application/ask.py`, and whatever serves their `citations` to the web layer
- Test: `tests/application/test_citation_moments.py`

**Interfaces:**
- Consumes: `locators.resolve(locator_map, start, end)` — **its first production caller.**
- Produces: each served citation gains an optional resolved offset (seconds), absent when the source has no locator map.

A citation carries `{source_id, start, end}` and no time. The map lives on `CorpusDerivedTextStored`. Resolution is arithmetic and already written; this task is about calling it where citations are served and carrying the answer to the client.

**A source with no locator map must render exactly as it does today.** Text sources have no map and never will — that is the majority case, and a design treating a missing map as an error would break every existing citation to make media ones work. Assert this explicitly.

- [ ] **Step 1: Write the failing tests**

```python
async def test_a_citation_into_a_transcript_carries_the_second_it_came_from():
    """First production use of `locators.resolve`, whose docstring has named
    a citation renderer as an intended caller since it was written."""
    served = await serve_citations(project_id, [Citation(source_id=video, start=100, end=140)])
    assert served[0].at_seconds == 252


async def test_a_citation_into_a_text_source_is_unchanged():
    """Text sources have no locator map. This test fails if a missing map is
    treated as an error rather than as the ordinary case it is."""
    served = await serve_citations(project_id, [Citation(source_id=article, start=0, end=10)])
    assert served[0].at_seconds is None
```

- [ ] **Step 2:** Verify red. **Step 3:** Implement. **Step 4:** Green. **Step 5:** Commit.

---

## Task 4: Citations link to the moment, and the player seeks

**Files:**
- Modify: `frontend/src/presentation/research/GraphDetail.tsx:256-264`, `frontend/src/presentation/research/DocumentReader.tsx`, the citation DTO and mapper
- Test: alongside each

- [ ] **Step 1: Write the failing tests** — a citation carrying an offset renders a link with the fragment; one without renders today's link byte-for-byte; `DocumentReader` seeks a video to the fragment's second on mount and does not seek when there is none.
- [ ] **Step 2:** Verify red. **Step 3:** Implement, using the range support the content route already has. **Step 4:** `npm run verify`, rebuild and commit built assets. **Step 5: Commit.**

---

## Task 5: Teach the model the syntax

**Files:**
- Modify: the tool prompts that describe reading a source — `research_team/application/corpus_read.py` and the `Ask` prompt
- Test: `tests/application/test_prompts.py` (or alongside the prompt's own tests)

**A syntax nothing emits is dead code with tests.** This is the task most easily dropped, and dropping it makes the previous four inert.

The prompt must state: the exact grammar; that the offset is **seconds as an integer**; that a reference to a source the model has not read is a guess and should not be written; and that a reference is how you point at a moment, since the model cannot emit a URL.

- [ ] **Step 1:** Write a test asserting the grammar appears in the prompt a model actually receives — not that a constant exists, which passes while the prompt is unused.
- [ ] **Step 2:** Verify red. **Step 3:** Write the prompt text in the house voice. **Step 4:** Green. **Step 5: Commit.**

---

## Self-Review

**Spec coverage.** Syntax and its rejected alternatives → Task 1. Sanitisation ordering and the single-`dangerouslySetInnerHTML` invariant → Task 2. Citation → moment, and the no-map case → Tasks 3 and 4. Seeking → Task 4. The prompt half → Task 5. "No new events, no read model" → satisfied by construction; no task adds either.

**Gap found while reviewing:** the spec says a reference inside a code fence must not be transformed, and nothing in the original task list tested it. It is now Task 1's fifth and sixth cases. The failure would be a documentation example turning into a link, which is the kind of thing nobody notices until a user reports that the docs are broken.

**Known thin spot:** Task 4's steps are less granular than Tasks 1-3 because the citation DTO's shape depends on what Task 3 produces. An executor should expand them rather than treat brevity as permission to skip tests.
