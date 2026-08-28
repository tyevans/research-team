# Dead-code survey

A whole-project survey, run read-only on 2026-08-27 against
`worktree-remove-workflow-system` at `a501489`. Not scoped to the workflow
removal, though that removal is where two of the five highest-value findings
come from.

## What was run, and what it can and cannot see

Four AST passes over `research_team/`, `tests/` and `web.py`, plus three token
passes over `frontend/src`. The AST passes count *code* references
(`ast.Name`, `ast.Attribute`, `ast.ImportFrom`) rather than text, because this
repository's comments name almost every symbol in it at least once — a grep
for a name here returns the prose that explains why the name exists, and
counting that as a caller makes the survey return nothing. String constants
are counted separately, so a symbol reached by a registry key still shows as
used.

What the method still cannot see, and where I have said "uncertain" because of
it: decorator-registered projection handlers (`@handles(...)`), pydantic
validators, CSF story exports, and CSS classes written from template
literals. Every one of those was checked by hand where it mattered rather than
trusted to the count.

Not run: the test suites, `npm run verify`, or any browser. Collection only
(`pytest --co -q`: 3631/3640 collected, 9 deselected, no errors — so there is
no parametrised test in the tree collecting zero cases).

Two negative results worth recording, because they bound the search: **no
Python module in `research_team/` is unimported by anything**, and **no
frontend module in `frontend/src/` has a filename that appears in no other
file**. There are no orphan files. Everything below is a symbol, a branch or a
rule inside a live file.

---

## (a) Confidently dead, safe to delete

**Total: ~210 lines**, of which ~70 are Python production code, ~55 are Python
tests that exist only to test something nothing calls, and ~85 are frontend.

### 1. `SessionService.record_tool_decision` — 29 lines

`research_team/application/session_service.py:710-738`. A public use case with
**no caller in `research_team/`, `web.py`, or `tests/`**. Its own docstring
describes the seam it was built for ("A caller deciding something *between*
turns holds no aggregate, and this is the seam for it") and no such caller was
ever written. The path that does record decisions —
`infrastructure/agent/deep_agent.py:552,577,598,608` — constructs
`RecordToolDecision` on the aggregate it already holds and never goes through
this method.

Evidence: `grep -rn "record_tool_decision" research_team tests web.py
frontend/src` returns only the definition. The AST method pass reports zero
attribute uses of the name anywhere.

This is the cleanest instance in the tree of the CLAUDE.md "port with one
adapter and no test between them" shape, one step further along: a port with
*no* adapter, kept plausible by a docstring.

### 2. `fetch.format_page` and its five tests — ~70 lines

`research_team/infrastructure/agent/fetch.py:162-176`, and the five tests at
`tests/infrastructure/test_fetch.py:131,141,150,159,168,174,177`.

Production reference count: **zero**. The one caller it had inside the module
(`fetch.py:457`) now calls `extract_page` directly. This is the "only called
by its own test" category, and it is documented into place: the plan at
`docs/superpowers/plans/2026-08-10-remember-by-reference.md:1134` explicitly
tells a future executor *not* to delete it, on the grounds that "other call
sites read it". They no longer do. The tests are still green, so nothing
signals the change.

Cost of deleting: the citation-header shape that `_citation` produces loses
its only direct coverage. That is a real cost and the reason this is worth a
sentence in the commit message rather than a silent removal — but coverage of
a function nothing calls is not coverage of anything.

### 3. The `stage` worker kind, in four places — ~32 lines

The workflow removal deleted `"stage"` from `WorkerKind`
(`research_team/application/workers.py:26` now reads `Literal["run", "turn",
"extraction", "dispatch"]`). Four things downstream still describe it:

- `frontend/src/domain/worker/worker.ts:10` — `'stage'` in the `kind` union.
- `frontend/src/infrastructure/http/mappers.ts:352` — the explicit
  `worker.kind === 'stage'` branch, unreachable: no server response can carry
  it.
- `frontend/src/infrastructure/http/mappers.test.ts:243-265` — a 23-line test
  named "keeps a stage runner labelled as a stage rather than folding it into
  turn", which hand-writes a `kind: 'stage'` DTO. It passes, and it is the
  exact CLAUDE.md fixture shape: the fixture supplies the wire contract the
  server no longer states.
- `frontend/src/styles/agents.css:253-259` — `.agents-kind-stage`, plus the
  four-line comment explaining its colour choice. Written from
  `` `agents-kind-${worker.kind}` `` (`AgentWidget.tsx:247`), so a grep for the
  literal class finds nothing; it is dead because the *kind* is gone, not
  because the grep is empty.

Confidence: high. Settled by reading `WorkerKind` at both ends, not by a
caller count.

### 4. Six frontend exports with no reference outside their defining file — 27 lines

Each verified by counting every token occurrence of the name across all 550
`.ts`/`.tsx` files: total occurrence count is **1**, the definition itself.

| symbol | file:line | lines |
| --- | --- | --- |
| `RAIL_WIDTH_PX` | `frontend/src/presentation/layout/layout-tokens.ts:55-56` | 2 |
| `emptyProgress` | `frontend/src/domain/lesson/attempt.ts:40-46` | 7 |
| `noAuthoring` | `frontend/src/domain/knowledge/authoring.ts:80` | 1 |
| `wasCancelled` | `frontend/src/domain/knowledge/authoring.ts:101-106` | 6 |
| `projectRollupHeadOf` | `frontend/src/domain/entity/heads.ts:46-47` | 2 |
| `topicHeadOf` | `frontend/src/domain/entity/heads.ts:63-71` | 9 |

`RAIL_WIDTH_PX` is worth reading aloud, because its comment is the CLAUDE.md
"comment explaining an absence" pattern in miniature: *"The same width as a
number, for the one place that needs to compare it."* There is no such place.
`wasCancelled` carries a five-line comment distinguishing it from
`endedIncomplete` beside it; `endedIncomplete` is used and this is not.

### 5. Three small Python orphans — 35 lines

- `_Community` — `research_team/application/area_projection.py:176-190`, 15
  lines. A frozen dataclass with a nine-line docstring about tie-break
  determinism. Zero references anywhere, including the merge it describes.
- `MediaCandidate` — `research_team/application/media_curation.py:186-199`, 14
  lines. Its own docstring says it: *"nothing here constructs a
  `MediaCandidate` yet."* Nothing anywhere else does either. The module
  docstring at `:19` also refers to it and would need one line adjusted.
- `Application.definitions_caught_up` — `research_team/composition.py:1388-1399`,
  12 lines. Documented as "a test affordance, like `interaction_log_caught_up`";
  `interaction_log_caught_up` is called by tests and this is called by nothing.
  Note two *other* docstrings (`composition.py:273`, `:1209`) cite it by name
  as the pattern they follow, so deleting it means editing those two lines.

### 6. `config.embeddings_enabled` — 3 lines + 2 test assertions

`research_team/infrastructure/config.py:641-643`. Described as "a convenience
over `vector_store`, not a knob", and no production code takes the
convenience: `composition.py:2107,2118` both write `vector_kind != "none"`
inline. Referenced only by
`tests/infrastructure/test_embedding_config.py:44,52`.

---

## (b) Probably dead, needs one check first

### 7. `markdown.css`'s element-class families — ~84 lines, and a live defect

`frontend/src/styles/markdown.css:16-74` and `:86-110`, plus
`frontend/src/styles/conversation.css:60-61`.

`.md-h` (8 rules), `.md-p`, `.md-hr`, `.md-list`, `.md-li`, `.md-task`,
`.md-quote`, `.md-inline-code` and `.md-table` (4 rules) dress classes that
**nothing emits**. The renderer at
`frontend/src/infrastructure/rendering/markdown.ts` was rewritten to
`marked` + `DOMPurify` — its own docstring records replacing "a hand-written
block-and-inline renderer" — and `marked` emits bare `<h1>`, `<p>`, `<ul>`,
`<hr>`, `<blockquote>`, `<table>`, `<code>` with no classes. The only classes
the file adds are `md-link`, `md-link-internal` and `md-link-inert`
(`markdown.ts:68,76,81`), all in the `afterSanitizeAttributes` anchor hook.
`.md-code`, `.md-bare` and `.md-ref` are hand-applied at
`LessonDocument.tsx:157,176`, `DocumentReader.tsx:117`,
`GraphDetail.tsx:334` and `references.ts:189` and are live.

**This is not only dead CSS — it means rendered markdown is currently
unstyled**, falling back to browser defaults in a build that imports no
Tailwind preflight. Headings, tables, blockquotes and lists in every document
pane, message body and lesson.

**The check before acting:** open a document pane and inspect a rendered
`<h2>`. If it has no `md-h` class, the right change is a decision — re-attach
the classes in `markdown.ts`, or restyle by element selector under `.md`, or
delete — and only the third of those is a dead-code removal. I have marked it
(b) for that reason, not because the grep is in doubt. The grep is
conclusive: zero occurrences of `md-h`, `md-hr`, `md-list`, `md-li`,
`md-task`, `md-quote`, `md-inline-code`, `md-table` outside stylesheets and
one test comment.

No gate catches this. jsdom applies no stylesheet, and
`mention-snippet.browser.test.tsx:121` — the one browser test that reads a
margin here — asserts `marginBottom === '0px'` on a `.md-bare > :last-child`,
which is satisfied whether `.md-p` applies or not.

### 8. `SessionService.default_system_prompt` — 5 lines

`research_team/application/session_service.py:231-235`. A property with no
reader; the private `self._default_system_prompt` it wraps is used four times
inside the class (`:509,609,872`) and the constructor argument is passed at
`composition.py:2413`. **The check:** confirm no test or REPL formatter reads
it through `getattr` or a string key — the AST pass found zero of both, but a
property is exactly the shape a template or a `dir()`-driven debug view would
reach dynamically.

---

## (c) Alive but redundant

### 9. Exported types used only inside their own module — 64 symbols

The `export` keyword is dead, not the type. `Flashcard`, `FlashcardDeck`,
`McqOption`, `ClozeSegment`, `ChecklistItem`, `CompareRow`, `Evidence`,
`GraphRef` and `ExplorerAxis` in `frontend/src/domain/lesson/widgets.ts` are
the densest cluster; the full list is 64 names across 40 files, all `type` or
`interface`, each with zero occurrences outside its defining file.

Removing the keyword is a mechanical change with no behaviour attached and no
line-count saving. Recorded because it is the population a future "unused
export" lint rule would fire on, and somebody should know in advance that the
answer is "unexport", not "delete".

### 10. Value exports referenced only by their own test — ~40 symbols

Constants like `ABSENT` (`presentation/interactions/duration.ts:21`),
`ACTIVITY_SUMMARY_LIMIT`, `ARG_DETAIL_LIMIT`, `SAMPLE_CHARS`, `FLUSH_AT`, and
mapper functions `toGraphLink`, `toMessage`, `toApprovalSummary`,
`toBrowserSession`, `toProjectionFailure`, `toViewDwell`.

**These are not dead.** Each is used inside its own module by the exported
function that wraps it, and the test imports it to assert against the same
constant the code uses rather than a copy — which is the convention CLAUDE.md
argues for elsewhere (`FACETS` is exported for exactly this reason and says
so). Listed only so that a later pass does not "discover" them and act.

### 11. `ChunkCoMentions` named in a test that no longer has one

`tests/infrastructure/test_co_mentions.py:5,16,268,312,469` name a class that
does not exist — the adapter is `CoMentionIndex`
(`infrastructure/knowledge/co_mentions.py`, wired at `composition.py:2159`).
Docstrings only, so nothing fails; five stale names in the file whose whole
subject is a defect that stale documentation caused.

---

## (d) Suspicious, not settled

### 12. Four CSS classes in template-literal families

`.ev-strategy` (`timeline.css:166`), `.k-other` (`timeline.css:203`),
`.provisional-tool` (`conversation.css:299`), `.run-note`
(`components.css:521`). Each belongs to a family written from a template
literal — `` `k-${kindOf(entry)}` `` (`Timeline.tsx:262`),
`` `k-${classifyEventType(revision.type)}` `` (`FileHistory.tsx:84`),
`` `provisional-${entry.kind}` `` (`ActivityFeed.tsx:19`) — so the literal
name appearing nowhere proves nothing, exactly as `course.css`'s header
warns.

**Not grep-confident.** What would settle each: enumerate the return values of
`kindOf`, `classifyEventType` and the `ActivityEntry['kind']` union and check
whether `other`, `strategy` and `tool` are among them. I did not do this; it
is perhaps twenty minutes and worth ~15 lines.

The other 26 classes my scan flagged were checked and are **false positives** —
`.chip-fail`, `.chip-ok`, `.chip-warn`, `.chip-readonly`, `.chip-run-done`,
`.chip-run-short` reached through `` `chip-${tone}` `` (`primitives.tsx:79`)
with tones supplied at `AskActivity.tsx:62`, `WorkerList.tsx:44`,
`RunPanel.tsx:185,248,353`, `Segments.tsx:80,156`, `ScrubBar.tsx:147,149`;
`.msg-user`/`.msg-assistant` through `` `msg-${message.role}` ``
(`Segments.tsx:153`); `.run-ending-done/short/bad` through
`` `run-ending-${ending.tone}` `` (`RunPanel.tsx:351`) against
`EndingTone = 'done' | 'short' | 'bad'`; `.worker-dot-*` and the surviving
`.agents-kind-*` through their own template literals.

### 13. Exception classes raised but caught nowhere — 6 classes

`CheckpointFailed`, `MountedSourceIsReadOnly`, `PerceivedTextTooLong`,
`ReadOnlyFilesystem`, `ReferencesUnavailableError`, `UnknownTopic`. All are
raised at least once; none has an `except` naming it. That is usually correct
— they surface to a base-class handler or to the caller — and I could not
distinguish "deliberately unhandled" from "handler deleted" without reading
each call path. Recorded so nobody re-derives the list. None is a deletion
candidate.

### 14. Ports with a single adapter — 53 `Protocol`s in `application/`

The population CLAUDE.md points at is 53 protocols; auditing which have a
seam test is a day's work and is not a removal survey. Two spot checks: the
`CoMentionPort`/`CoMentionIndex` pair that the CLAUDE.md incident is about now
has `tests/infrastructure/test_co_mentions.py` driving both ends over a real
store, and `MediaCurationTextPort`/`MediaSearchPort` are wired at
`composition.py:1732`. Nothing here is dead; the audit is a separate task.

---

## Five highest-value findings

1. **`markdown.css`'s orphaned families (~84 lines)** — the only finding that
   is a live defect as well as dead weight. Rendered markdown is unstyled
   everywhere it appears.
2. **`SessionService.record_tool_decision` (29 lines)** — a use case with no
   caller, kept plausible by its own docstring.
3. **`format_page` and its five tests (~70 lines)** — dead in production, held
   alive by tests and by a plan document that says not to delete it.
4. **The `stage` worker kind (~32 lines across four files)** — a leftover of
   the workflow removal, including a passing test whose fixture asserts a wire
   contract the server no longer states.
5. **`_Community`, `MediaCandidate`, `definitions_caught_up`,
   `embeddings_enabled` (~38 lines)** — four small orphans, three of which
   document their own deadness in prose and were never acted on.

## What I could not check

- Whether `.ev-strategy`, `.k-other`, `.provisional-tool` and `.run-note` are
  reachable (item 12) — needs three union enumerations.
- Whether the 53 application ports each have a test driving both ends (item
  14) — out of scope for a removal survey, and the shape CLAUDE.md says costs
  the most when it goes wrong.
- Read-model columns nothing backfills. `apply_schema` reconciles added
  columns, so a column added and never written looks identical to one written
  by an event that has not occurred yet; separating the two needs a real
  database, and I had none to open read-only.
- Anything requiring a running browser or a test run. `npm run verify` and
  `pytest` were deliberately not run: another agent holds the machine.
- Dead prose. `docs/superpowers/plans/` holds plan documents describing code
  that has since changed (the `format_page` instruction in item 2 is one), and
  they are stale in the way a design record is allowed to be. I have not
  treated them as findings.
