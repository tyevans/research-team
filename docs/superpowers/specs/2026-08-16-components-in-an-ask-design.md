# Components in an ask

A reader asks the corpus a question and gets prose back. Sometimes the honest
answer to "do I understand this?" is not a paragraph — it is a question the
reader has to answer, and then be told whether they were right. The component
system already knows how to do that. It just cannot be reached from the ask
page.

Today an ask answer renders through `<Markdown>` (`AskTurn.tsx:52`), and a
fenced `component:mcq` block in an answer renders as a code block: the
unknown-fence path, which is the safe failure and is also the whole feature
missing. The ask agent has never been told the syntax either, so it does not
author one in the first place.

This is both halves: tell the agent, and render what it writes.

It also carries a third thing that is not about the ask page at all. The
session agent — the one authoring course artifacts — already receives the
component reference and writes mediocre items with it, because the reference
teaches syntax and not craft. §7 puts that guidance in the registry, where both
agents read it from one copy.

## What already carries

Three things make this smaller than it looks, and they are the reason this is
worth doing now rather than after B18.

**`parse_document` is pure.** It takes `(source, path)` — a string and a label,
not a file handle. Nothing in `application/components.py` requires an artifact
on disk. An ask answer is a string.

**The authoring reference is generated from the registry.**
`component_reference(only=…)` (`components.py:531`) produces the syntax from
`REGISTRY`, which is what keeps the file path's prompt from drifting. The ask
prompt gets the identical guarantee for free.

**An answer is already addressable.** The 2026-08-16 ask-persistence work put
every turn on an `AskConversation` stream and projected it to `ask_turns`, with
`position` stored rather than inferred (`read_models.py:3014-3035`). So
`(conversation_id, position)` names one answer, permanently, and the row holds
the answer text verbatim. That is the same trick the file surface uses — the
server re-reads the source of truth and re-parses it to recover the key — with
`ask_turns` standing where `session.state.files` stands.

Without that last one this design would have had to invent a home for the
answer key, and the honest options were all bad.

## The shape

### 1. The agent is told, narrowly

`ASK_PROMPT` (`ask_agent.py:89`) gains a component section built from
`component_reference(only=("mcq", "cloze", "flashcards"))`.

**`checklist` is excluded**, and this is a ruling rather than an oversight. A
checklist is a record of a procedure someone performed; its only interesting
mode is `persist: true`, and persistence needs a learner identity the ask path
does not have (§4). A checklist that cannot remember a tick is a list of
bullets with worse affordances than a list of bullets.

**The occasion matters more than the syntax here, and gets more words than the
syntax does.** The file path can assume the occasion — a stage writing an
`EVIDENCE_SPEC` is writing assessment items by definition. An ask has no such
signal, and the failure mode is specific and likely: a model handed four widget
schemas turns every answer into a quiz, which is exactly the behaviour that
makes a feature like this get switched off within a day. The guidance says a
component earns its place when the reader would learn more by *doing* than by
reading, that the default is prose, and that a question about a fact the corpus
states plainly is not worth asking back.

This mirrors `component_guidance`'s reasoning (`components.py:604`) that a
stage with no component-bearing output is told nothing at all: the cost of
carrying inapplicable instructions is not tokens, it is teaching the model that
most of its instructions do not apply to it.

### 2. The parse happens on the server, twice, in one place

A new `application/ask_components.py` holds one function — given answer text,
return the projected document — and both surfaces call it. Server-side for the
same four reasons `components.py` opens with, of which the second is the one
that binds here: withholding is only real if the projection happens before the
bytes leave.

The two surfaces:

- **The live answer frame.** `_ask_frame`'s `AskAnswer` branch
  (`app.py:2922`) gains `blocks` beside `text`, and gains `position`.
- **The stored turn.** `read_ask`'s turn view (`app.py:3060`) gains the same
  `blocks`.

`position` on the live frame is what lets a widget the reader is looking at
*right now* be graded, and it is available: `RecordAskTurn` is executed before
the final `yield` (`ask.py:301-309`, whose comment explains why moving it after
was tried and rejected), so by the time the answer frame is built the turn is
on disk. The ordinal is `len(conversation.messages) // 2` — what the registry
already holds — rather than a second load to ask the aggregate.

**The answer keeps its `text` field.** Both surfaces return prose *and* blocks
rather than blocks alone, so a client that does nothing with `blocks` renders
exactly what it renders today. This is what makes the frontend change
independently deployable, and it is also the honest position on withholding
(§5).

### 3. Grading, against the stored answer

```
POST /api/projects/{project_id}/asks/{conversation_id}/attempts
{ position, component_id, response }
```

The route reads `ask_turns` for `(conversation_id, position)`, checks the
conversation belongs to `project_id` (404 for both misses, as `read_ask`
already rules), re-parses `answer`, and calls the existing
`grade(component, response)`. No new grading logic exists — `grading.py` takes
a `ComponentBlock` and knows nothing about where it came from.

The 400/404 boundary is inherited: `GradingError` is a 400, a missing component
is a 404, a wrong answer is a 200 with `correct: false`.

### 4. Nothing is recorded, and that is the ruling

The file path records every attempt on `LearnerProgress`, keyed by the session.
The ask path records nothing. A verdict is returned, rendered, and forgotten
when the page closes.

Three reasons, in order of weight:

1. **There is no principal to key on.** `LearnerProgress` shares its session's
   UUID because a session is the only thing in this codebase meaning "one
   person working through material" — and `BACKLOG.md` B33 already records that
   this is what breaks first when authentication arrives. An ask is
   deliberately *not* a session (`ask.py`'s opening docstring: a parallel path,
   not a caller). Inventing a second identity here would be answering B33 by
   accident, in the surface least suited to it.
2. **The record would not be worth much.** Progress exists so an author can see
   which distractor is doing work across a cohort. A question the model
   improvised for one reader in one conversation has no cohort and is not part
   of anyone's course.
3. **It is reversible.** The turn is addressable, so an attempt aggregate keyed
   on `(conversation_id, position, component_id)` can be added later without
   changing anything designed here. Doing it now is speculative.

The visible consequence: refresh the ask history and the widgets are blank
again. That is worth stating in the UI rather than discovering, and the design
takes it as the cost of not answering B33 here.

### 5. Withholding on this surface is weaker than on a file, and says so

The learner projection is applied to the blocks, so the key is not in the
payload and the browser cannot mark an answer. But `text` is returned beside
`blocks` (§2), and the raw answer contains the key inline.

**This is `BACKLOG.md` B30 restated, one surface further along, and it is
knowingly weaker than B30's subject** — there, the answer key is a fetch away
at a *different* route; here it is in the same response. Two reasons for taking
it anyway:

- The alternative is worse. Stripping `text` when blocks are present means the
  answer's prose — the part the reader asked for — is reconstructed from blocks
  by a client, which is a second renderer and a new class of bug, to defend
  against a reader who wants to know the answer to a question they asked for
  themselves.
- The threat model is different. On a course file, the withholding is between
  an author and a *learner*, who are two people. On an ask, they are the same
  person: the reader asked the question and the model wrote it for them. The
  affordance is "don't show me the answer until I've tried", which is what it
  will be described as.

The UI's existing "answers withheld" tooltip is honest on the file surface and
would be *dishonest* here, so the ask surface gets its own wording naming the
weaker property. A new BACKLOG entry records it, referencing B30 and B18.

### 6. The frontend renders blocks when there are any

`AskTurn` branches on `hasComponents(doc)` — the same predicate
`LessonDocument.tsx` uses, and for the same reason it exists: a turn with no
widgets keeps the plain path and the common case grows no second render tree.

`useAttempts` (`application/lesson/use-attempts.ts`) is scoped to
`(sessionId, path, at)` and posts to the session attempts route. Rather than
duplicate 120 lines of it, the hook is refactored so the *submit and load
ports* are injected and the state machine is shared:

- `useAttempts(sessionId, path, at)` keeps its exact signature and behaviour;
- a sibling `useAskAttempts(conversationId, position)` supplies the ask route
  and a null progress loader.

The document-key reset logic transfers unchanged — the key becomes the
conversation and position instead of the session and path, and "a different
turn is a different set of answers" is the same rule.

`LessonDocument` is reused as-is: it takes `{ doc, attempts }` and nothing in
it names a file. This is the whole reason §3 grades against a re-parse rather
than inventing a payload shape — the renderer is already correct.

### 7. The registry teaches craft, not only syntax — and the session agent gets it too

The ask agent is not the only one authoring these badly. The session agent
already receives `component_guidance(outputs)` (`components.py:604`), narrowed
to the types its stage's artifacts admit, and what that guidance contains is a
schema, an example, and four lines about when a component earns its place.
Nothing in it says what a *good* one looks like, so the model supplies the
average of its training data: four options where three are obviously wrong, a
cloze that blanks the word most easily guessed from the sentence around it, a
deck of forty cards on one screen.

`ComponentType` gains a `craft: tuple[str, ...]` field, rendered by
`component_reference` under each type's example. Registry-resident for the
reason `summary` and `example` are: guidance maintained beside the schemas
drifts from them within two edits, and the drift is invisible until a model
authors faithfully to a stale description.

What goes in it is per-type and short — these are the failure modes the format
actually produces, not a course in assessment design:

- **mcq** — every distractor should be something a reader who half-understands
  would actually pick, and the per-option `feedback` should say why that
  particular misunderstanding is wrong. An option nobody chooses teaches
  nothing and costs a line. Prefer three or four options over five.
- **cloze** — blank the thing being learned, not the word that happens to be a
  noun. If the surrounding sentence gives the answer away, the blank tests
  reading rather than recall. Use `::hint` where the answer is a term with
  several defensible spellings, since grading normalises case and spacing but
  not word choice (`grading.py:normalize_answer`).
- **flashcards** — one fact per card. A card whose back is a paragraph is a
  passage that has been put in the wrong container.
- **checklist** — steps someone performs in order, not facts they should know.

This is the same one-place change reaching both agents: the ask prompt (§1)
calls `component_reference` too, so it inherits every word of this without a
second copy to maintain. That property is the whole argument for putting it in
the registry rather than in either prompt.

**One measured caveat before this section is trusted.** Whether richer guidance
produces better items is a claim about model behaviour, and this design asserts
it rather than having measured it. The cost if it is wrong is bounded — a
longer prompt on stages already carrying the reference — but the honest note is
that nothing here proves the items improve. The implementation ends with a
before/after read of one generated evidence spec, recorded in the commit
message, so the next person has at least one observation rather than only this
paragraph.

## Testing

The gates are the four in `CLAUDE.md`, plus a rebuilt console
(`frontend/src/**` changes → `npm run build` → commit `web/static`).

What is worth writing beyond the obvious:

- **A property test that no answer survives the ask projection**, matching the
  one `components.py` describes for files. The generated document there is
  reusable; only the projection call site differs.
- **A test that grades against a turn that is not the last one.** The bug this
  is written red for is a route that reads "the conversation's answer" and gets
  the most recent — invisible in every single-turn test, and every hand test is
  a single turn.
- **A test whose fixture does not open the conversation first.** `CLAUDE.md`'s
  entity-definitions entry: a fixture that seeds through the same call the code
  depends on cannot see that dependency go missing. The ask attempts route
  reads a *read model*, so the analogous hole is a test that posts an attempt
  in the same process that just streamed the answer — where the projection
  happened to have caught up. At least one test posts against a conversation
  the projection was started fresh against.
- **A browser test only if a computed style is the assertion.** Rendering a
  widget inside a chat turn is a layout question the jsdom suite can judge
  (roles, text, keyboard) — unless the widget's containment in a narrower
  column turns out to be a measurement, in which case it is
  `*.browser.test.tsx` per the stylesheet rule.

## What this deliberately does not do

- **No `checklist`** (§1) and no new component types. `widget-horizons.md`
  ranks the unregistered ones; none of them become more urgent here.
- **No progress, no history, no resume** (§4).
- **No authoring into files.** The ask agent holds `READ_ONLY_TOOLS` and a
  backend that raises on write. A component in an answer is a thing to do in
  the conversation, not a draft to be saved, and nothing here loosens that
  allowlist.
- **No approval gate.** Unchanged from today: the ask path wires none because
  there is nothing to gate, and this adds nothing gateable.
