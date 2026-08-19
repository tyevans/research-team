# Socratic Dialogue — Plan 3 of 4: the console

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make a dialogue something a reader can hold in a browser — a facet on the project, a streaming transcript that runs in the right direction, its goal and stopping condition visible, and answers that survive a refresh.

**Architecture:** One `FACETS` entry, one `regionOf` arm, one `App.tsx` intercept — the grammar already supports it and `regionOf` is total over `Facet`, so a new facet fails to compile until registered. Behind that, a `HttpDialogueRepository` parsing the SSE frames Plan 2 emits, a pure transcript fold in `domain/dialogue/`, and a store wiring the two. Deliberately **not** a reuse of the ask's components: the surface runs in the opposite direction and the ask's turn renderer would draw every dialogue with the speakers swapped.

**Tech Stack:** React 19 + zustand + TanStack Query + TypeScript (`exactOptionalPropertyTypes` on); zod at the wire boundary; vitest (jsdom) + vitest browser mode; hand-written `components.css` over Tailwind v4.

**Spec:** `docs/superpowers/specs/2026-08-17-socratic-dialogue-design.md` — §6 is this plan's.

**Predecessors:** Plan 1 (`docs/superpowers/plans/2026-08-17-socratic-dialogue.md`) and Plan 2 (`docs/superpowers/plans/2026-08-17-socratic-dialogue-agent.md`), both merged — `b3300f1` is the tip this plan is written against.

---

## The wire contract, read from the code rather than from the plans

**Plan 1's plan document shows three code blocks with the OLD key names.** They carry as-built notes now, but do not copy from them. Plan 2's Task 5 found the answer key leaking on three dialogue surfaces — the raw question text shipped beside correctly-withheld `blocks` — and the fix renamed every key that carried prose. Everything below is read from `app.py` at `b3300f1`.

**SSE frames, from `_socratic_frame`:**

| `type` | fields | notes |
| --- | --- | --- |
| `dialogue` | `dialogue_id`, `goal`, `stopping_condition`, `pending_blocks` | first frame, always |
| `delta` | `message_id`, `text` | **raw model prose — see the ruling below** |
| `message` | `message_id`, `kind`, `payload`, `is_error` | `kind` is `assistant`, `tool`, or **`remark`** |
| `prompt` | `blocks`, `position`, `citations`, `concluded` | last frame. **No `text` key at all** |
| `error` | `detail` | |

A note type with no branch returns `None` and is skipped — it draws nothing rather than an empty bubble. So the frame set is closed and a sixth type would simply not arrive.

**Route bodies**, from `_dialogue_view` and `read_dialogue`:

- dialogue: `dialogueId`, `projectId`, `topic`, `goal`, `stoppingCondition`,
  `openingBlocks`, `pendingBlocks`, `openedAt`, `status`, `concludedReason`,
  `turnCount`, `observations`
- each turn: `position`, `blocks`, `reply`, `citations`, `recordedAt`

**There is no raw prompt string on any surface.** Not on the frame, not on the row view, not on a turn. A client wanting the prose walks `blocks` for its `kind: "markdown"` entries. That is deliberate: on this surface a projection is only real if there is nothing beside it.

## Global Constraints

- **Four gates, and passing three is not passing.** `uv run ruff check .`,
  `uv run ruff format --check .`, `uv run pytest`, `cd frontend && npm run verify`.
  The ruff commands run over the whole repository.
- **The fifth gate is invisible from `verify`.** `research_team/interfaces/web/static`
  is a committed build artefact and CI fails on drift. **Every task here touches
  `frontend/src`, so every task ends with `cd frontend && npm run build` and a
  commit of the rebuilt `assets/app.js` and `assets/index.css`.** `npm run verify`
  runs the build and never compares its output against the tree.
- **jsdom lays nothing out.** `scrollHeight` is 0, `getComputedStyle` returns only
  what an inline style said, and a selector matching nothing is indistinguishable
  from one that matches. Any assertion about a measurement or a computed style
  belongs in a `*.browser.test.tsx`, run by hand with
  `cd frontend && npm run test:browser` — it is outside `verify` and outside CI.
- **Never run two `vitest` processes at once.** Concurrent runs fail spuriously
  with a coverage temp-file error naming nothing about the real cause.
- **Never default an optional collaborator with `or`.** Use `?? fallback` only
  where the falsy value is impossible, and `x !== undefined ? x : fallback`
  otherwise. An empty array, an empty string and `0` are all falsy and all
  legitimate.
- **A render-helper option typed `projectId?: ProjectId` with a destructuring
  default is inert when passed `undefined`** — the default fires and restores the
  value, so the "absent" test silently exercises the ordinary path. Type it
  `ProjectId | null` and pass `null`.
- **Container keys are plural** — `graphs`, `timelines`, `documents`. The new one
  is `dialogues`.
- **`--fg-muted` and `--bg-raised` do not exist.** Use `--fg-dim` and `--bg-raise`,
  and grep `frontend/src/styles/tokens.css` for every token you name. An undefined
  custom property sets nothing and looks exactly like a rule that worked.
- **Typographic apostrophes.** The widgets emit `’`; a straight-quote regex never
  matches. Assert on a fragment without one.
- **`border-solid` beside one directional width draws three unwanted sides.** Pair
  `border: 0` with the directional width.

---

## Rulings this plan makes, and why

**Deltas are a liveness signal, not the question's text.** This is the one
decision that shapes the whole plan, and it comes from a leak I found reading
the executor rather than from the spec.

`_socratic_frame` emits `delta` frames straight from `to_activity_delta`, which
carries the main agent's prose **verbatim as the model produces it**. When the
model writes an `mcq`, the fenced YAML streams through that channel with
`correct: true` in it — before the `prompt` frame arrives carrying the withheld
projection. Plan 2's `test_the_answer_key_never_reaches_the_reader` measures the
`prompt` frame, `pending_blocks` and all three route views; it does not measure
the delta stream, because its stub executor emits no deltas.

So a page that folded deltas into the question's text would render the answer key
on screen, then swap it for the projection a moment later. That is worse than the
byte-level leak: it is visible.

**Therefore the transcript's question text comes only from `blocks`, and deltas
drive nothing but a "composing" indicator.** Three things follow, and all three
are good independently: no flicker between raw prose and rendered blocks; no
half-parsed fence rendering as literal YAML mid-stream; and the page has no code
path that could render an un-projected utterance at all.

**What this does not fix, and must be said plainly: the bytes still reach the
browser.** A reader with devtools open sees the key in the delta frames. Closing
that is a server change — suppressing deltas on the socratic stream, or filtering
them — and it is **not in this plan's scope**, because it is Plan 2's surface and
it needs its own measurement. It is written up for the lead as a finding. This
plan reduces the blast radius from "rendered on screen" to "present in the
network tab"; it does not claim more.

**The ask's transcript components are not reused, and this is not a preference.**
`prompt` is the system's utterance and `reply` is the reader's — the inverse of
`AskTurn`'s `question`/`answer`. A view reusing `AskTurn` unchanged draws every
dialogue with the speakers swapped, **and it still reads as a conversation**,
which is why nothing but a deliberate assertion catches it. `AskActivity` is
reused (activity is activity), and `LessonDocument` is reused (blocks are
blocks); the turn shape is not.

**The pending question renders after the last turn, and it is not a turn.** A
turn pairs the reader's `reply` with the question it *produced*, so the
transcript's first utterance is `openingBlocks` on the dialogue and belongs to no
turn. A client rendering only `turns` draws a reader answering something nobody
asked; a client that forgets `pendingBlocks` draws a transcript ending on the
reader's own words with nothing asking them anything. Both are pinned.

**`concluded` is rendered and will always be false.** Nothing writes
`SocraticDialogueConcluded` until Plan 4, so the "this dialogue is finished"
state is unreachable in practice. Rendering it now costs one branch and means
Plan 4 lands without touching this file; the test that covers it constructs the
state directly and says so.

**Progress needs a route that does not exist** — `BACKLOG` B114. Task 5 records
attempts against the dialogue id and nothing can read them back, so "your answers
survive a refresh" is real in storage and invisible in the browser. Task 6 adds
the dialogue-scoped read route and the client that calls it. That is a Python
task inside a frontend plan, deliberately: the property is the reason this
surface is its own principal, and shipping the console without it would ship the
claim without the thing.

---

## File structure

| File | Responsibility |
| --- | --- |
| `frontend/src/domain/dialogue/conversation.ts` | `DialogueTurn`, `DialogueTranscript`, `DialogueEvent`, `applyEvent`, `answered` |
| `frontend/src/domain/dialogue/conversation.test.ts` | the fold, including both direction traps |
| `frontend/src/infrastructure/http/dialogue-repository.ts` | `HttpDialogueRepository` — SSE parse, start, attempts, progress |
| `frontend/src/infrastructure/http/dialogue-repository.test.ts` | frame parsing, buffering, unknown frames |
| `frontend/src/application/ports/repositories.ts` | `DialogueRepository` |
| `frontend/src/app/container.ts` | `dialogues: DialogueRepository` |
| `frontend/src/application/dialogue/dialogue-store.ts` | store: send, resume, attempts |
| `frontend/src/presentation/dialogue/DialogueView.tsx` | store owner |
| `frontend/src/presentation/dialogue/DialoguePage.tsx` | layout, goal + stopping condition |
| `frontend/src/presentation/dialogue/DialogueThread.tsx` | the transcript, in the right order |
| `frontend/src/presentation/dialogue/DialogueExchange.tsx` | one turn: question then answer |
| `frontend/src/presentation/routing/routes.ts` | `'dialogue'` in `FACETS` |
| `frontend/src/presentation/project/ProjectView.tsx` | the `regionOf` arm |
| `frontend/src/app/App.tsx` | the intercept |
| `frontend/src/styles/components.css` | `.dlg-*` |
| `research_team/interfaces/web/app.py` | `GET .../dialogues/{id}/progress` (Task 6) |

---

### Task 1: The transcript fold

**Files:**
- Create: `frontend/src/domain/dialogue/conversation.ts`
- Create: `frontend/src/domain/dialogue/conversation.test.ts`

**Interfaces:**
- Consumes: `DocumentBlock` (`@domain/lesson/document.ts`); `AskActivity` and
  `Citation` re-used from `@domain/ask/conversation.ts` — activity is activity and
  a citation is a citation, and a second copy of either would be a second thing to
  keep in step.
- Produces:

```ts
export interface DialogueTurn {
  /** What the dialogue asked. Blocks, never a string -- no surface carries a
   *  raw prompt. */
  readonly blocks: readonly DocumentBlock[]
  /** What the reader answered. Raw, because it is their own words. */
  readonly reply: string
  readonly position: number
  readonly activity: readonly AskActivity[]
  readonly citations: readonly Citation[]
  readonly concluded: boolean
  readonly error: string | null
  readonly settled: boolean
}
export type DialogueTranscript = readonly DialogueTurn[]

export type DialogueEvent =
  | { type: 'dialogue'; dialogueId: string; goal: string
      stoppingCondition: string; pendingBlocks: readonly DocumentBlock[] }
  | { type: 'delta'; messageId: string; text: string }
  | { type: 'message'; messageId: string
      kind: 'assistant' | 'tool' | 'remark'; payload: unknown; isError: boolean }
  | { type: 'prompt'; blocks: readonly DocumentBlock[]; position: number
      citations: readonly Citation[]; concluded: boolean }
  | { type: 'error'; detail: string }

export const answered: (t: DialogueTranscript, reply: string) => DialogueTranscript
export const applyEvent: (t: DialogueTranscript, e: DialogueEvent) => DialogueTranscript
export const composing: (t: DialogueTranscript) => boolean
```

  `answered` and not `asked`: on this surface the reader's move opens a turn.

- [ ] **Step 1: Write the failing tests**

Create `frontend/src/domain/dialogue/conversation.test.ts`:

```ts
/** The dialogue transcript, as a fold over the stream.
 *
 * Pure on purpose, for the reason `ask/conversation.ts` gives: streaming order
 * is the part that goes subtly wrong and is far cheaper to get right here than
 * through a rendered component.
 *
 * Two traps have their own tests because both produce something that still
 * looks like a conversation: the speakers running the wrong way, and the
 * question text coming from deltas rather than from the projection.
 */
import { expect, it } from 'vitest'

import { answered, applyEvent, composing } from './conversation.ts'
import type { DialogueTranscript } from './conversation.ts'

const BLOCKS = [{ kind: 'markdown', text: 'Why do you say that?' }] as const
const KEYED = [
  { kind: 'markdown', text: 'Try this:' },
  { kind: 'component', type: 'mcq', id: 'q1', data: {}, withheld: ['correct'] },
] as const

const opened = (): DialogueTranscript => answered([], 'It settled Arianism.')

it('opens a turn on the reader’s answer, not on the dialogue’s question', () => {
  // `answered`, not `asked`. On this surface the reader's move is what opens a
  // turn: the dialogue has already asked, and its question is either the
  // opening one on the row or the previous turn's. Red against a fold copied
  // from the ask, where the turn opens on the question.
  const transcript = opened()

  expect(transcript).toHaveLength(1)
  expect(transcript[0]?.reply).toBe('It settled Arianism.')
  expect(transcript[0]?.blocks).toEqual([])
  expect(transcript[0]?.settled).toBe(false)
})

it('settles a turn from the prompt frame’s blocks', () => {
  const transcript = applyEvent(opened(), {
    type: 'prompt',
    blocks: BLOCKS,
    position: 3,
    citations: [{ kind: 'source', id: 's1' }],
    concluded: false,
  })

  expect(transcript[0]?.blocks).toEqual(BLOCKS)
  expect(transcript[0]?.position).toBe(3)
  expect(transcript[0]?.citations).toEqual([{ kind: 'source', id: 's1' }])
  expect(transcript[0]?.settled).toBe(true)
})

it('never puts delta text into the question, however much of it arrives', () => {
  // **The leak this fold exists to not have.** `delta` frames carry the model's
  // prose verbatim as it is produced -- including the raw fenced YAML of a
  // component, `correct: true` and all -- because `to_activity_delta` streams
  // the main agent's text untouched. The `prompt` frame that follows carries
  // the withheld projection.
  //
  // A fold that accumulated deltas into the question would render the answer
  // key on screen and then swap it out a moment later. Red against
  // `blocks: [...turn.blocks, {kind: 'markdown', text: event.text}]` or any
  // other accumulation: the assertion below finds the key in the transcript.
  const streamed = applyEvent(opened(), {
    type: 'delta',
    messageId: 'm1',
    text: '```component:mcq\nid: q1\noptions:\n  - text: "Nicaea"\n    correct: true\n```',
  })

  expect(streamed[0]?.blocks).toEqual([])
  expect(JSON.stringify(streamed)).not.toContain('correct')
})

it('reports that the dialogue is composing while deltas arrive, and stops when it settles', () => {
  // What the deltas are actually for. The reader gets a liveness signal and
  // never the text. Red against a fold that drops deltas entirely -- the page
  // then shows nothing at all between the reader's answer and the question,
  // which on a slow model reads as a hung page.
  const streaming = applyEvent(opened(), { type: 'delta', messageId: 'm1', text: 'Why' })
  expect(composing(streaming)).toBe(true)

  const settled = applyEvent(streaming, {
    type: 'prompt',
    blocks: BLOCKS,
    position: 0,
    citations: [],
    concluded: false,
  })
  expect(composing(settled)).toBe(false)
})

it('keeps activity, including a remark, in arrival order', () => {
  // `remark` is a third `kind` the ask never sees: Plan 2 carries an
  // `ActivityRemark` as a message with an empty `message_id` so a page can
  // style it apart from a model utterance without a sixth frame type. Red
  // against a fold whose `kind` union is copied from `AskActivity`.
  const transcript = applyEvent(
    applyEvent(opened(), {
      type: 'message',
      messageId: 'm1',
      kind: 'tool',
      payload: { name: 'read_source' },
      isError: false,
    }),
    { type: 'message', messageId: '', kind: 'remark', payload: { text: 'thinking' }, isError: false },
  )

  expect(transcript[0]?.activity.map((a) => a.kind)).toEqual(['tool', 'remark'])
})

it('settles a turn on an error and closes it to later frames', () => {
  const failed = applyEvent(opened(), { type: 'error', detail: 'the model is down' })
  expect(failed[0]?.error).toBe('the model is down')
  expect(failed[0]?.settled).toBe(true)

  // A settled turn is closed: a late frame belongs to nothing, and writing it
  // in would overwrite something the reader has already read.
  const late = applyEvent(failed, {
    type: 'prompt',
    blocks: BLOCKS,
    position: 0,
    citations: [],
    concluded: false,
  })
  expect(late[0]?.blocks).toEqual([])
})

it('carries the concluded flag off the prompt frame', () => {
  // Rendered from today and always false until Plan 4, which is the slice that
  // makes anything write `SocraticDialogueConcluded`. Constructed directly
  // here for that reason -- no live path produces it.
  const transcript = applyEvent(opened(), {
    type: 'prompt',
    blocks: BLOCKS,
    position: 0,
    citations: [],
    concluded: true,
  })

  expect(transcript[0]?.concluded).toBe(true)
})

it('ignores the dialogue frame, which is the store’s business and not a turn’s', () => {
  const transcript = applyEvent(opened(), {
    type: 'dialogue',
    dialogueId: 'd1',
    goal: 'g',
    stoppingCondition: 's',
    pendingBlocks: BLOCKS,
  })

  expect(transcript).toEqual(opened())
})

it('drops any event that arrives before the reader has answered anything', () => {
  expect(applyEvent([], { type: 'delta', messageId: 'm', text: 'hi' })).toEqual([])
})

it('does not let a withheld component’s key into the transcript', () => {
  // The projection has already withheld it server-side; this asserts the fold
  // carries blocks through without reconstructing anything.
  const transcript = applyEvent(opened(), {
    type: 'prompt',
    blocks: KEYED,
    position: 0,
    citations: [],
    concluded: false,
  })

  expect(transcript[0]?.blocks).toEqual(KEYED)
  expect(JSON.stringify(transcript)).not.toContain('"correct"')
})
```

- [ ] **Step 2: Run them to verify they fail**

Run: `cd frontend && npx vitest run src/domain/dialogue/conversation.test.ts`

Expected: FAIL — cannot resolve `./conversation.ts`.

- [ ] **Step 3: Write the fold**

Create `frontend/src/domain/dialogue/conversation.ts`. Mirror
`domain/ask/conversation.ts`'s structure — same `replaced` helper, same
settled-turn guard — with these differences, each of which has a test above:

```ts
/** A dialogue's transcript, as a fold over the stream.
 *
 * A sibling of `ask/conversation.ts` and deliberately not a reuse of it. The
 * two surfaces run in opposite directions: an ask is reader-asks /
 * agent-answers, a dialogue is agent-asks / reader-answers. A transcript type
 * shared between them would make that inversion a runtime concern, and a view
 * that drew it the wrong way round would still look like a conversation.
 *
 * **The question is `blocks` and never a string, and deltas never touch it.**
 * No server surface carries a raw prompt -- `_socratic_frame` dropped its
 * `text` key when the answer key was found shipping beside the projection --
 * so a turn's question is the projection or nothing. The `delta` frames do
 * carry the model's raw prose, fenced components and answer keys included, and
 * folding them into the question would render the key on screen for the moment
 * before the `prompt` frame replaced it. They drive `composing` and nothing
 * else.
 *
 * `AskActivity` and `Citation` are imported rather than redeclared: activity is
 * activity, and the citation kinds are the server's, not this surface's.
 */
import type { AskActivity, Citation } from '@domain/ask/conversation.ts'
import type { DocumentBlock } from '@domain/lesson/document.ts'
```

`answered` opens a turn with `blocks: []`, `settled: false`, `composing: false`.
`applyEvent`'s `delta` arm sets a private `composing` flag on the open turn and
appends nothing; `prompt` replaces `blocks`, `position`, `citations`, `concluded`
and settles; `message` appends activity; `error` settles; `dialogue` returns the
transcript unchanged. `composing(transcript)` reads the open turn's flag.

`composing` is a field on the turn, not a derivation — and it carries its
reasoning in the code rather than only here, because `activity.length > 0` is
the obvious simplification and it is wrong:

```ts
  /** Whether the dialogue is mid-utterance right now.
   *
   * A field rather than `activity.length > 0`, which is the derivation someone
   * will reach for. A turn whose model ran a tool and then went quiet has
   * activity and is *not* composing, and the two states look different on
   * screen: one says "reading the corpus", the other says "writing". Deriving
   * it would leave the composing indicator stuck on for the whole of a long
   * tool call and then never turn off, which reads as a hang.
   *
   * Set by `delta` frames and cleared when the turn settles. The text those
   * frames carry never reaches the page -- see this module's docstring. */
  readonly composing: boolean
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd frontend && npx vitest run src/domain/dialogue/conversation.test.ts`

Expected: PASS, 10 tests.

- [ ] **Step 5: Prove the delta test red**

Temporarily make the `delta` arm accumulate:

```ts
    case 'delta':
      return replaced({
        ...turn,
        blocks: [...turn.blocks, { kind: 'markdown', text: event.text }],
      })
```

Re-run. Expected: `never puts delta text into the question` fails on the
`not.toContain('correct')` assertion — the raw fence with the answer key is in
the transcript. Revert.

This is the repository's convention and it is the measurement this task exists
to take: the accumulating version renders perfectly well and shows the key.

- [ ] **Step 6: Wiring**

Nothing imports this yet; Task 2 is its first reader. Confirm the shapes it
narrows match the server's, by reading them side by side:

Run: `grep -n '"type": "prompt"' -A 12 research_team/interfaces/web/app.py`

Every key in the `prompt` frame must have a field in `DialogueEvent`, and there
must be no `text`. A mismatch here fails no test in either language and produces
a transcript whose questions are all empty.

- [ ] **Step 7: Gates and the committed build**

Run: `cd frontend && npm run verify` then `cd frontend && npm run build`

- [ ] **Step 8: Commit**

```bash
git add frontend/src/domain/dialogue/ research_team/interfaces/web/static
git commit -m "Fold a dialogue's transcript, in the direction it actually runs

A sibling of the ask's fold, not a reuse. The two surfaces run opposite ways --
an ask is reader-asks/agent-answers, a dialogue is agent-asks/reader-answers --
and a shared transcript type would make that inversion a runtime concern in
every view. A view that drew it backwards would still look like a
conversation, which is why the turn opens on the reader's answer here and has
its own test saying so.

The question is blocks and never a string, and deltas never touch it. No server
surface carries a raw prompt any more: _socratic_frame dropped its text key
when the answer key was found shipping beside the projection. But the delta
frames still carry the model's raw prose as it is produced -- a fenced mcq
streams through with correct: true in it -- so a fold that accumulated deltas
into the question would render the key on screen and swap it out a moment
later. Proved by making the delta arm accumulate: the raw fence lands in the
transcript and the test finds the key.

Deltas drive a composing flag instead, which is what they are useful for. A
fold that dropped them entirely would leave the page blank between the reader's
answer and the question, which on a slow model reads as a hang.

composing is a field rather than activity.length > 0: a turn whose model ran a
tool and went quiet has activity and is not composing, and those look different
on screen.

The remark kind is carried. Plan 2 sends an ActivityRemark as a message with an
empty id so a page can style it apart without a sixth frame type, and a kind
union copied from AskActivity would drop it."
```

---

### Task 2: The streaming repository

**Files:**
- Create: `frontend/src/infrastructure/http/dialogue-repository.ts`
- Create: `frontend/src/infrastructure/http/dialogue-repository.test.ts`
- Modify: `frontend/src/application/ports/repositories.ts`
- Modify: `frontend/src/app/container.ts`

**Interfaces:**
- Consumes: Task 1's `DialogueEvent`; `ApiError`, `seg`, `verdictDto`, `toVerdict`.
- Produces:

```ts
export interface DialogueRepository {
  /** Frames a dialogue and returns its server-minted id. Not a stream. */
  start(projectId: ProjectId, topic: string): Promise<string>
  /** Streams one exchange. Rejects with a 404 for an unknown or concluded
   *  dialogue and a 409 for one already running -- both are raised before the
   *  stream opens, so both are status codes. A failure after the first frame
   *  arrives as an `error` event and resolves. */
  reply(
    projectId: ProjectId, dialogueId: string, reply: string,
    onEvent: (event: DialogueEvent) => void, signal?: AbortSignal,
  ): Promise<void>
  submitDialogueAttempt(
    projectId: ProjectId, dialogueId: string,
    input: { position: number; componentId: ComponentId; response: AttemptResponse },
  ): Promise<Verdict>
  /** Task 6. */
  progress(projectId: ProjectId, dialogueId: string): Promise<DialogueProgress>
}
```

  Container key: `dialogues` (plural), matching `graphs`/`timelines`/`documents`.

- [ ] **Step 1: Write the failing tests**

Create `frontend/src/infrastructure/http/dialogue-repository.test.ts`:

```ts
/** The SSE parser for the dialogue stream.
 *
 * Owning the parser means framing bugs are this file's problem, which is why
 * buffering across reads and tolerating an unknown frame are both tested here:
 * nothing else in the stack would catch either.
 */
import { expect, it, vi } from 'vitest'

import { ProjectId } from '@domain/shared/identifier.ts'

import { HttpDialogueRepository } from './dialogue-repository.ts'

const PROJECT = ProjectId('11111111-1111-4111-8111-111111111111')

const streaming = (body: string) => {
  const encoder = new TextEncoder()
  return vi.fn().mockResolvedValue({
    ok: true,
    status: 200,
    body: {
      getReader: () => {
        let sent = false
        return {
          read: async () => {
            if (sent) return { done: true, value: undefined }
            sent = true
            return { done: false, value: encoder.encode(body) }
          },
        }
      },
    },
  })
}

const frame = (body: unknown) => `data: ${JSON.stringify(body)}\n\n`

it('parses the dialogue frame the server actually sends', async () => {
  const events: unknown[] = []
  const fetcher = streaming(
    frame({
      type: 'dialogue',
      dialogue_id: 'd1',
      goal: 'understand it',
      stopping_condition: 'the reader explains it unaided',
      pending_blocks: [{ kind: 'markdown', text: 'Where would you start?' }],
    }),
  )

  await new HttpDialogueRepository('', fetcher).reply(PROJECT, 'd1', 'hello', (e) =>
    events.push(e),
  )

  expect(events).toEqual([
    {
      type: 'dialogue',
      dialogueId: 'd1',
      goal: 'understand it',
      stoppingCondition: 'the reader explains it unaided',
      pendingBlocks: [{ kind: 'markdown', text: 'Where would you start?' }],
    },
  ])
})

it('parses a prompt frame that has no text key at all', async () => {
  // The server dropped `text` from this frame when the answer key was found
  // shipping beside the projection. A schema requiring it would reject every
  // real frame; a schema defaulting it would invite a page to render the
  // default. Red against `text: z.string()` and against `.default('')`.
  const events: unknown[] = []
  const fetcher = streaming(
    frame({
      type: 'prompt',
      blocks: [{ kind: 'markdown', text: 'Why?' }],
      position: 2,
      citations: [{ kind: 'source', id: 's1' }],
      concluded: false,
    }),
  )

  await new HttpDialogueRepository('', fetcher).reply(PROJECT, 'd1', 'x', (e) => events.push(e))

  expect(events).toEqual([
    {
      type: 'prompt',
      blocks: [{ kind: 'markdown', text: 'Why?' }],
      position: 2,
      citations: [{ kind: 'source', id: 's1' }],
      concluded: false,
    },
  ])
  expect(JSON.stringify(events)).not.toContain('"text":"Why?"')
})

it('accepts a remark, which the ask stream never sends', async () => {
  const events: { kind?: string }[] = []
  const fetcher = streaming(
    frame({
      type: 'message',
      message_id: '',
      kind: 'remark',
      payload: { text: 'reading the corpus' },
      is_error: false,
    }),
  )

  await new HttpDialogueRepository('', fetcher).reply(PROJECT, 'd1', 'x', (e) =>
    events.push(e as { kind?: string }),
  )

  expect(events[0]?.kind).toBe('remark')
})

it('holds a frame that straddles two reads', async () => {
  // The network decides where a body splits, and a parser assuming one chunk
  // is one frame drops events the first time one straddles the boundary.
  const encoder = new TextEncoder()
  const whole = frame({ type: 'delta', message_id: 'm', text: 'why' })
  const chunks = [whole.slice(0, 12), whole.slice(12)]
  const fetcher = vi.fn().mockResolvedValue({
    ok: true,
    status: 200,
    body: {
      getReader: () => ({
        read: async () => {
          const next = chunks.shift()
          return next === undefined
            ? { done: true, value: undefined }
            : { done: false, value: encoder.encode(next) }
        },
      }),
    },
  })
  const events: unknown[] = []

  await new HttpDialogueRepository('', fetcher).reply(PROJECT, 'd1', 'x', (e) => events.push(e))

  expect(events).toEqual([{ type: 'delta', messageId: 'm', text: 'why' }])
})

it('skips a frame type it does not know rather than throwing', async () => {
  // The server skips a note it cannot render rather than sending an empty
  // one, so an unknown type here means a newer server. Dropping it is the same
  // contract the unknown-fence path keeps: an older reader draws what it can.
  const events: unknown[] = []
  const fetcher = streaming(
    frame({ type: 'something-new', detail: 'x' }) +
      frame({ type: 'error', detail: 'the model is down' }),
  )

  await new HttpDialogueRepository('', fetcher).reply(PROJECT, 'd1', 'x', (e) => events.push(e))

  expect(events).toEqual([{ type: 'error', detail: 'the model is down' }])
})

it('rejects with the status when the stream never opens', async () => {
  // 404 for an unknown or concluded dialogue, 409 for one already running --
  // both raised before streaming, so both are statuses rather than in-band
  // error frames. A caller that only handled `error` events would show a turn
  // that silently stops.
  const fetcher = vi.fn().mockResolvedValue({
    ok: false,
    status: 409,
    text: async () => JSON.stringify({ detail: 'already running' }),
  })

  await expect(
    new HttpDialogueRepository('', fetcher).reply(PROJECT, 'd1', 'x', () => {}),
  ).rejects.toMatchObject({ status: 409 })
})

it('starts a dialogue and returns the server’s id', async () => {
  const fetcher = vi.fn().mockResolvedValue({
    ok: true,
    status: 200,
    text: async () => JSON.stringify({ dialogueId: 'd1' }),
  })

  const id = await new HttpDialogueRepository('', fetcher).start(PROJECT, 'the creed')

  expect(id).toBe('d1')
  expect(fetcher.mock.calls[0]?.[1]).toMatchObject({
    method: 'POST',
    body: JSON.stringify({ topic: 'the creed' }),
  })
})
```

- [ ] **Step 2: Run them to verify they fail**

Run: `cd frontend && npx vitest run src/infrastructure/http/dialogue-repository.test.ts`

Expected: FAIL — cannot resolve `./dialogue-repository.ts`.

- [ ] **Step 3: Write the repository**

Create `frontend/src/infrastructure/http/dialogue-repository.ts`. Mirror
`ask-repository.ts` exactly in structure — the same wrapped `fetcher`, the same
`pending` buffer across reads, the same trailing `emit(pending, onEvent)` for a
body that ends without its blank line. The zod union differs:

```ts
const dialogueFrameDto = z.discriminatedUnion('type', [
  z.object({
    type: z.literal('dialogue'),
    dialogue_id: z.string(),
    goal: z.string(),
    stopping_condition: z.string(),
    pending_blocks: z.array(z.unknown()).default([]),
  }),
  z.object({ type: z.literal('delta'), message_id: z.string(), text: z.string() }),
  z.object({
    type: z.literal('message'),
    message_id: z.string(),
    // Three kinds, not the ask's two. `remark` is Plan 2's way of carrying an
    // `ActivityRemark` without a sixth frame type, and a union copied from the
    // ask's DTO rejects every one of them.
    kind: z.enum(['assistant', 'tool', 'remark']),
    payload: z.unknown(),
    is_error: z.boolean().default(false),
  }),
  z.object({
    type: z.literal('prompt'),
    // **No `text`.** The server dropped it when the answer key was found
    // shipping beside the projection; requiring it rejects every real frame,
    // and defaulting it invites a page to render the default as the question.
    // `unknown` blocks for `ask-repository`'s reason: the domain's readers
    // narrow an open `data` record at the one boundary that needs it, and
    // re-deriving the component shape in zod would be a second schema to keep
    // in step with the registry.
    blocks: z.array(z.unknown()).default([]),
    position: z.number().int().nonnegative().default(0),
    citations: z.array(citationDto).default([]),
    concluded: z.boolean().default(false),
  }),
  z.object({ type: z.literal('error'), detail: z.string() }),
])
```

`start` posts `{topic}` and reads `dialogueId` from the JSON body.
`submitDialogueAttempt` mirrors `submitAskAttempt` against
`/dialogues/{id}/attempts`. `progress` is Task 6 — stub it there, not here.

- [ ] **Step 4: Add the port and the container key**

In `application/ports/repositories.ts`, add `DialogueRepository` with the
docstrings from the Interfaces block above. In `app/container.ts`, add
`readonly dialogues: DialogueRepository` and
`dialogues: new HttpDialogueRepository(baseUrl)`.

**Plural.** A singular key typechecks through the `as unknown as AppContainer`
cast every test harness uses and resolves to `undefined` at runtime, so the
symptom is a page stuck loading forever rather than a type error.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd frontend && npx vitest run src/infrastructure/http/dialogue-repository.test.ts`

Expected: PASS, 7 tests.

- [ ] **Step 6: Wiring**

Run: `cd frontend && grep -n "dialogues" src/app/container.ts`

Expected: the import, the interface field, and the construction — three hits. A
port added to the interface and never constructed is a `undefined` at every call
site, and TypeScript will not catch it through the harness cast.

- [ ] **Step 7: Gates and the committed build**

Run: `cd frontend && npm run verify` then `cd frontend && npm run build`

- [ ] **Step 8: Commit**

```bash
git add frontend/src/infrastructure/http/dialogue-repository.ts \
  frontend/src/infrastructure/http/dialogue-repository.test.ts \
  frontend/src/application/ports/repositories.ts frontend/src/app/container.ts \
  research_team/interfaces/web/static
git commit -m "Parse the dialogue stream, three frame kinds and no raw prompt

The prompt frame has no text key and the schema must not invent one. Requiring
it rejects every real frame; defaulting it invites a page to render the empty
default as the dialogue's question. The server dropped that key deliberately
when the answer key was found shipping beside the projection, and the schema is
where a client would quietly put it back.

Three message kinds, not the ask's two. Plan 2 carries an ActivityRemark as a
message with an empty id and kind: remark so a page can style it apart without
a sixth frame type, and a union copied from the ask's DTO rejects every one.

An unknown frame type is skipped rather than thrown on: the server already
skips notes it cannot render, so an unknown type here means a newer server, and
an older reader drawing what it can is the same contract the unknown-fence path
keeps.

Container key is dialogues, plural. A singular one typechecks through the cast
every harness uses and resolves to undefined, so the symptom is a page stuck
loading rather than a type error."
```

---

### Task 3: The store

**Files:**
- Create: `frontend/src/application/dialogue/dialogue-store.ts`
- Create: `frontend/src/application/dialogue/dialogue-store.test.ts`

**Interfaces:**
- Consumes: `DialogueRepository`, Task 1's fold.
- Produces:

```ts
export interface DialogueState {
  readonly transcript: DialogueTranscript
  readonly dialogueId: string | null
  readonly goal: string
  readonly stoppingCondition: string
  /** The question the reader is answering right now: the opening one on a
   *  fresh dialogue, the outstanding one on a resumed one. Blocks, never a
   *  string. */
  readonly pendingBlocks: readonly DocumentBlock[]
  readonly replying: boolean
  readonly starting: boolean
  readonly error: string | null
  start(topic: string): Promise<void>
  send(reply: string): Promise<void>
}
export const createDialogueStore: (deps: {
  dialogues: DialogueRepository
  projectId: ProjectId
}) => DialogueStore
```

  No `newChatId`: the dialogue's id is the server's and arrives from `start`.
  That is the whole difference from `createAskStore`, and it is why `send`
  refuses before `start` has returned rather than minting anything.

- [ ] **Step 1: Write the failing tests**

Create `frontend/src/application/dialogue/dialogue-store.test.ts`:

```ts
/** The dialogue store: what it refuses, and what it keeps.
 *
 * The ask's store mints a `chatId` in the browser and can send immediately.
 * This one cannot: the dialogue id is the server's, so every guard here is
 * about not sending before there is a dialogue to send to.
 */
import { expect, it, vi } from 'vitest'

import { ProjectId } from '@domain/shared/identifier.ts'

import { createDialogueStore } from './dialogue-store.ts'

const PROJECT = ProjectId('11111111-1111-4111-8111-111111111111')
const BLOCKS = [{ kind: 'markdown', text: 'Where would you start?' }] as const

const repo = (over: Record<string, unknown> = {}) => ({
  start: vi.fn().mockResolvedValue('d1'),
  reply: vi.fn().mockResolvedValue(undefined),
  submitDialogueAttempt: vi.fn(),
  progress: vi.fn().mockResolvedValue({ items: {} }),
  ...over,
})

it('keeps the framing off the dialogue frame so the reader can see it', async () => {
  // The design's §5: a dialogue whose goal the reader cannot see is a quiz
  // pretending to be a conversation. The framing arrives on the stream's first
  // frame and lives on the store, not in the transcript -- it is not a turn.
  const dialogues = repo({
    reply: vi.fn().mockImplementation(async (_p, _d, _r, onEvent) => {
      onEvent({
        type: 'dialogue',
        dialogueId: 'd1',
        goal: 'understand the creed',
        stoppingCondition: 'the reader explains it unaided',
        pendingBlocks: BLOCKS,
      })
    }),
  })
  const store = createDialogueStore({ dialogues, projectId: PROJECT })

  await store.getState().start('the creed')
  await store.getState().send('It settled Arianism.')

  expect(store.getState().goal).toBe('understand the creed')
  expect(store.getState().stoppingCondition).toBe('the reader explains it unaided')
  expect(store.getState().pendingBlocks).toEqual(BLOCKS)
})

it('refuses to send before a dialogue has been started', async () => {
  // Red against a store that posts anyway: the route would 404 on a null id
  // rendered into the URL, and the reader would see a failure that reads as
  // the server's rather than as "you have not started yet".
  const dialogues = repo()
  const store = createDialogueStore({ dialogues, projectId: PROJECT })

  await store.getState().send('hello?')

  expect(dialogues.reply).not.toHaveBeenCalled()
})

it('refuses a second reply while one is running', async () => {
  // The server answers 409; not sending is the same answer without the round
  // trip. Red against a store with no `replying` guard.
  let release = (): void => {}
  const dialogues = repo({
    reply: vi.fn().mockImplementation(
      () => new Promise<void>((resolve) => (release = resolve)),
    ),
  })
  const store = createDialogueStore({ dialogues, projectId: PROJECT })
  await store.getState().start('t')

  const first = store.getState().send('one')
  await store.getState().send('two')
  release()
  await first

  expect(dialogues.reply).toHaveBeenCalledTimes(1)
})

it('settles the open turn when the request fails before streaming', async () => {
  // A 404 or 409 arrives as a rejection rather than an in-band error frame, so
  // this is the only place that path closes the turn. Without it the turn
  // spins forever with no question and no reason, which reads as a hung model
  // rather than a failed request.
  const dialogues = repo({ reply: vi.fn().mockRejectedValue(new Error('already running')) })
  const store = createDialogueStore({ dialogues, projectId: PROJECT })
  await store.getState().start('t')

  await store.getState().send('one')

  const transcript = store.getState().transcript
  expect(transcript[0]?.settled).toBe(true)
  expect(transcript[0]?.error).toContain('already running')
  expect(store.getState().replying).toBe(false)
})

it('does not start a second dialogue while one is being framed', async () => {
  // Framing calls a model and takes seconds. A double-click would otherwise
  // mint two dialogues and strand the first, which is a stream nobody can
  // reach again.
  let release = (): void => {}
  const dialogues = repo({
    start: vi.fn().mockImplementation(
      () => new Promise<string>((resolve) => (release = () => resolve('d1'))),
    ),
  })
  const store = createDialogueStore({ dialogues, projectId: PROJECT })

  const first = store.getState().start('t')
  await store.getState().start('t')
  release()
  await first

  expect(dialogues.start).toHaveBeenCalledTimes(1)
})

it('surfaces a framing failure as an error rather than an empty dialogue', async () => {
  // The route answers 502 when the model botched the framing. A store that
  // swallowed it would leave the page on an empty dialogue with a composer
  // that 404s on every send.
  const dialogues = repo({
    start: vi.fn().mockRejectedValue(new Error('the dialogue could not be framed')),
  })
  const store = createDialogueStore({ dialogues, projectId: PROJECT })

  await store.getState().start('t')

  expect(store.getState().dialogueId).toBeNull()
  expect(store.getState().error).toContain('could not be framed')
  expect(store.getState().starting).toBe(false)
})
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd frontend && npx vitest run src/application/dialogue/dialogue-store.test.ts`

Expected: FAIL — cannot resolve `./dialogue-store.ts`.

- [ ] **Step 3: Write the store**

Mirror `createAskStore`: `create<DialogueState>((set, get) => ({...}))`, the same
`errorMessage(err)` translation, the same `finally { set({ replying: false }) }`.
Intercept the `dialogue` event in the `onEvent` callback and write `goal`,
`stoppingCondition`, `pendingBlocks` and `dialogueId` onto the store rather than
into the fold — the framing is not a turn, exactly as the ask intercepts its
`conversation` frame.

Both guards carry their reasoning in the code, not only here — the `start` one
especially, because a store that only guarded `send` looks complete:

```ts
    async start(topic) {
      // Guarded as well as `send`, and for a worse failure. Framing calls a
      // model and takes seconds, so a double-click on a slow connection posts
      // twice: two dialogues are minted, the page keeps the second, and the
      // first is a stream with a goal and an opening question that no client
      // will ever name again -- an orphan the reader paid a model call for and
      // cannot reach. `send`'s guard only saves a round trip the server would
      // have refused with a 409 anyway; this one prevents state nothing can
      // clean up.
      if (get().starting || get().dialogueId !== null) return
      ...
    },

    async send(reply) {
      // No dialogue means no id to put in the URL. Posting anyway would 404 on
      // a `null` rendered into the path, and the reader would read that as the
      // server failing rather than as "you have not started one yet".
      if (!get().dialogueId || get().replying) return
      ...
    },
```

- [ ] **Step 4: Run to verify they pass**

Run: `cd frontend && npx vitest run src/application/dialogue/dialogue-store.test.ts`

Expected: PASS, 6 tests.

- [ ] **Step 5: Wiring**

Run: `cd frontend && npx vitest run src/domain/dialogue/ src/application/dialogue/ src/infrastructure/http/dialogue-repository.test.ts`

Expected: PASS. The store is the first thing that exercises the fold and the
repository together; a shape mismatch between them shows up here and nowhere
earlier.

- [ ] **Step 6: Gates and the committed build**

Run: `cd frontend && npm run verify` then `cd frontend && npm run build`

- [ ] **Step 7: Commit**

```bash
git add frontend/src/application/dialogue/ research_team/interfaces/web/static
git commit -m "Wire the dialogue stream to the fold, and guard what the ask cannot

The ask's store mints a chatId in the browser and can send immediately. This
one cannot: the dialogue id is minted by the server, because it is an aggregate
id, a row key and a URL segment. So every guard here is about not sending
before there is a dialogue to send to -- send refuses on a null id rather than
rendering it into a URL and letting the route 404, which would read to a reader
as the server failing rather than as not having started.

start is guarded too. Framing calls a model and takes seconds, so a double
click would otherwise mint two dialogues and strand the first, which is a
stream nobody can reach again.

The framing lives on the store, not in the transcript. It is not a turn, and a
reader who cannot see the goal is in a quiz pretending to be a conversation."
```

---

### Task 4: The transcript, drawn in the right direction

**Files:**
- Create: `frontend/src/presentation/dialogue/DialogueExchange.tsx`
- Create: `frontend/src/presentation/dialogue/DialogueThread.tsx`
- Create: `frontend/src/presentation/dialogue/DialoguePage.tsx`
- Create: `frontend/src/presentation/dialogue/DialoguePage.test.tsx`
- Create: `frontend/src/presentation/dialogue/dialogue-fixtures.ts`
- Modify: `frontend/src/styles/components.css`

**Interfaces:**
- Consumes: Task 1's `DialogueTurn`; `LessonDocument` (blocks are blocks);
  `AskActivity` component (activity is activity).
- Produces:

```tsx
export const DialoguePage: (props: {
  projectId: ProjectId
  transcript: DialogueTranscript
  goal: string
  stoppingCondition: string
  pendingBlocks: readonly DocumentBlock[]
  dialogueId: string | null
  replying: boolean
  starting: boolean
  error: string | null
  onStart: (topic: string) => void
  onReply: (reply: string) => void
}) => React.ReactElement
```

  DOM contract: `.dlg-framing` on the goal block, `.dlg-goal`,
  `.dlg-condition`, `.dlg-exchange`, `.dlg-question`, `.dlg-answer`,
  `.dlg-pending`, `.dlg-composing`.

- [ ] **Step 1: Write the failing tests**

Create `frontend/src/presentation/dialogue/DialoguePage.test.tsx`:

```tsx
/** What jsdom can judge about the dialogue page: the order of the transcript,
 *  who said what, and that the framing is on screen.
 *
 * Height and layout belong in `DialoguePage.browser.test.tsx` (Task 5), for
 * CLAUDE.md's reason: jsdom lays nothing out.
 */
import { render, screen, within } from '@testing-library/react'
import { expect, it, vi } from 'vitest'

import { ProjectId } from '@domain/shared/identifier.ts'

import { DialoguePage } from './DialoguePage.tsx'
import { exchange, PROJECT } from './dialogue-fixtures.ts'

const props = (over: Record<string, unknown> = {}) => ({
  projectId: PROJECT,
  transcript: [],
  goal: 'understand what the creed settled',
  stoppingCondition: 'the reader separates the settlement from the politics',
  pendingBlocks: [{ kind: 'markdown', text: 'Where would you start?' }],
  dialogueId: 'd1',
  replying: false,
  starting: false,
  error: null,
  onStart: vi.fn(),
  onReply: vi.fn(),
  ...over,
})

it('shows the goal and the stopping condition to the reader', () => {
  // The design's §5, and the one thing that separates this from a quiz: a
  // reader who disagrees with the goal should be able to see that they
  // disagree before spending twenty minutes on it. Red against a page that
  // reads the framing off the store and renders neither.
  render(<DialoguePage {...props()} />)

  expect(screen.getByText(/what the creed settled/)).toBeInTheDocument()
  expect(screen.getByText(/separates the settlement from the politics/)).toBeInTheDocument()
})

it('draws the dialogue asking and the reader answering, in that order', () => {
  // **The direction trap.** `blocks` is the dialogue's utterance and `reply`
  // is the reader's -- the inverse of an ask. A page that reused `AskTurn`
  // unchanged would render these swapped and it would still read as a
  // conversation, which is why this asserts on which element holds which text
  // rather than on both being present.
  render(
    <DialoguePage
      {...props({
        transcript: [
          exchange({
            blocks: [{ kind: 'markdown', text: 'What makes you say settled?' }],
            reply: 'It settled Arianism.',
          }),
        ],
      })}
    />,
  )

  const drawn = screen.getByTestId('dlg-exchange-0')
  expect(within(drawn).getByTestId('dlg-question')).toHaveTextContent('What makes you say settled?')
  expect(within(drawn).getByTestId('dlg-answer')).toHaveTextContent('It settled Arianism.')
})

it('puts the question before the answer in the document, not merely in the data', () => {
  // Order on screen, not order in the array. A page that rendered the reply
  // first would satisfy the test above and still show the reader answering a
  // question printed underneath their answer.
  render(
    <DialoguePage
      {...props({
        transcript: [
          exchange({
            blocks: [{ kind: 'markdown', text: 'QUESTION FIRST' }],
            reply: 'ANSWER SECOND',
          }),
        ],
      })}
    />,
  )

  const text = screen.getByTestId('dlg-exchange-0').textContent ?? ''
  expect(text.indexOf('QUESTION FIRST')).toBeLessThan(text.indexOf('ANSWER SECOND'))
})

it('renders the outstanding question after the last exchange', () => {
  // The pending question belongs to no turn -- it is the one the reader is
  // answering now. A page that omitted it ends the transcript on the reader's
  // own words with nothing asking them anything. Red against a thread that
  // renders `transcript` alone.
  render(
    <DialoguePage
      {...props({
        transcript: [
          exchange({ blocks: [{ kind: 'markdown', text: 'EARLIER' }], reply: 'answered' }),
        ],
        pendingBlocks: [{ kind: 'markdown', text: 'OUTSTANDING' }],
      })}
    />,
  )

  const thread = screen.getByTestId('dlg-thread').textContent ?? ''
  expect(thread.indexOf('EARLIER')).toBeLessThan(thread.indexOf('OUTSTANDING'))
  expect(screen.getByTestId('dlg-pending')).toHaveTextContent('OUTSTANDING')
})

it('shows the opening question when nothing has been answered yet', () => {
  // A fresh dialogue: no turns, one outstanding question. Red against a thread
  // that renders the pending block only when the transcript is non-empty.
  render(<DialoguePage {...props({ transcript: [] })} />)

  expect(screen.getByTestId('dlg-pending')).toHaveTextContent('Where would you start?')
})

it('says the dialogue is composing rather than showing a half-written question', () => {
  // Deltas drive this and nothing else -- see `domain/dialogue/conversation.ts`
  // for why the text they carry never reaches the page.
  render(<DialoguePage {...props({ transcript: [exchange({ composing: true })] })} />)

  expect(screen.getByTestId('dlg-composing')).toBeInTheDocument()
})

it('offers a topic composer and no reply composer before a dialogue exists', () => {
  render(<DialoguePage {...props({ dialogueId: null, pendingBlocks: [] })} />)

  expect(screen.getByLabelText(/topic/i)).toBeInTheDocument()
  expect(screen.queryByLabelText(/your answer/i)).not.toBeInTheDocument()
})

it('says a dialogue has finished when it concludes', () => {
  // Constructed directly, because nothing writes `SocraticDialogueConcluded`
  // until Plan 4 -- `concluded` is false on every frame a live server sends
  // today. Rendered now so Plan 4 lands without touching this file.
  render(<DialoguePage {...props({ transcript: [exchange({ concluded: true })] })} />)

  expect(screen.getByText(/this dialogue has reached its goal/i)).toBeInTheDocument()
})
```

Create `dialogue-fixtures.ts` with `PROJECT` and an `exchange()` builder
defaulting every `DialogueTurn` field — for `ask-fixtures.ts`'s reason: an
inline literal per test is a place to get `settled` wrong, which routes the turn
down a path the test is not about.

- [ ] **Step 2: Run to verify they fail**

Run: `cd frontend && npx vitest run src/presentation/dialogue/DialoguePage.test.tsx`

Expected: FAIL — cannot resolve `./DialoguePage.tsx`.

- [ ] **Step 3: Write the components and the CSS**

`DialogueExchange` renders `<LessonDocument doc={{blocks: turn.blocks}} …>` in a
`.dlg-question` block with `data-testid="dlg-question"`, then the reader's
`reply` in `.dlg-answer`. `DialogueThread` maps the transcript and renders
`pendingBlocks` after it in `.dlg-pending`. `DialoguePage` renders `.dlg-framing`
above the thread and the composer below.

Before writing any rule:

Run: `cd frontend && grep -nE -- "--(fg|fg-dim|bg-raise|line|radius|t-sm|space-3):" src/styles/tokens.css`

Expected: one hit each. `--fg-muted` and `--bg-raised` do not exist and a rule
naming one sets nothing while looking exactly like a rule that worked.

The framing block gets `--bg-raise` and `--fg-dim` for the condition; the
question and the answer are visually distinct (the whole point), and the
distinction is asserted in Task 5's browser test rather than here.

- [ ] **Step 4: Run to verify they pass**

Run: `cd frontend && npx vitest run src/presentation/dialogue/DialoguePage.test.tsx`

Expected: PASS, 8 tests.

- [ ] **Step 5: Prove the direction test red**

Swap the two children in `DialogueExchange` so the reply renders above the
question. Re-run. Expected: `puts the question before the answer in the document`
fails on the index comparison, and the `within` test still passes — which is the
finding: the per-element assertion cannot catch an ordering swap on its own.
Revert.

- [ ] **Step 6: Wiring**

Run: `cd frontend && grep -n "dlg-" src/presentation/dialogue/*.tsx src/styles/components.css`

Every class in the stylesheet must appear in a component and vice versa. A class
in only one place is inert and no gate catches it.

- [ ] **Step 7: Gates and the committed build**

Run: `cd frontend && npm run verify` then `cd frontend && npm run build`

- [ ] **Step 8: Commit**

```bash
git add frontend/src/presentation/dialogue/ frontend/src/styles/components.css \
  research_team/interfaces/web/static
git commit -m "Draw a dialogue the way it actually runs

blocks is the dialogue's utterance and reply is the reader's -- the inverse of
an ask -- so a page reusing AskTurn unchanged renders every dialogue with the
speakers swapped, and it still reads as a conversation. That is why there are
two assertions rather than one: which element holds which text, and which
appears first in the document. Proved by swapping the children: the per-element
assertion still passes, and only the ordering one fails.

The outstanding question renders after the last exchange and belongs to no
turn. A page that omitted it ends the transcript on the reader's own words with
nothing asking them anything, and a fresh dialogue would show nothing at all.

The goal and the stopping condition are on screen. A dialogue whose goal the
reader cannot see is a quiz pretending to be a conversation, and a reader who
disagrees with the goal should be able to see that before spending twenty
minutes on it.

concluded is rendered and is false on every frame a live server sends: nothing
writes SocraticDialogueConcluded until Plan 4. The test constructs the state
directly and says so. Rendering it now means Plan 4 does not touch this file.

Tokens grepped against tokens.css rather than reasoned. --fg-muted and
--bg-raised do not exist here and set nothing while looking like rules that
worked."
```

---

### Task 5: The facet, the route, and a measured page

**Files:**
- Modify: `frontend/src/presentation/routing/routes.ts` (`FACETS`)
- Modify: `frontend/src/presentation/project/ProjectView.tsx` (`regionOf`)
- Modify: `frontend/src/app/App.tsx` (the intercept)
- Create: `frontend/src/presentation/dialogue/DialogueView.tsx`
- Create: `frontend/src/presentation/dialogue/DialoguePage.browser.test.tsx`
- Modify: `frontend/src/presentation/routing/routes.test.ts`

**Interfaces:**
- Consumes: Task 3's store, Task 4's page.
- Produces: `DialogueView({ projectId }: { projectId: ProjectId })`, and
  `'dialogue'` as a member of `Facet`.

- [ ] **Step 1: Add the facet and watch the compiler demand the rest**

Add `'dialogue'` to `FACETS` in `routes.ts`, with a comment in the register its
neighbours use:

```ts
  // A place on the project with a durable id, unlike `ask` beside it: a
  // dialogue's id is minted by the server and is a row key, so it has a better
  // claim to a URL segment than an ask does. The grammar already supports it
  // unchanged -- `Selection` carries an id for every plain facet.
  'dialogue',
```

Run: `cd frontend && npx tsc --noEmit -p tsconfig.json`

Expected: **FAIL** in `ProjectView.tsx` — `regionOf` is total over `Facet` by
design, so a new facet fails to compile until it is registered. **Watching this
happen is the point of the step**: it is the guard that makes a facet
unforgettable.

- [ ] **Step 2: Add the `regionOf` arm and the intercept**

In `ProjectView.tsx`, add `case 'dialogue':` beside `case 'ask':` in the `queue`
arm, and extend that arm's comment:

```ts
    // `dialogue` joins `ask` here for the same reason and with the same
    // caveat: `App.tsx` intercepts both above this view, so neither is drawn
    // by a region. The map is total over `Facet`, so they have to be somewhere,
    // and "what is there to do" is where a conversation belongs.
```

In `App.tsx`, beside the ask intercept:

```tsx
  // Intercepted for `ask`'s reason -- a dialogue is one conversation with no
  // parts worth a URL segment beyond its own id, so it is a view rather than a
  // region. `key` on the dialogue id and not the project: switching dialogues
  // within a project must remount the store, or the second dialogue inherits
  // the first's transcript.
  if (selection?.facet === 'dialogue') {
    return <DialogueView key={`${id}:${selection.id ?? 'new'}`} projectId={id} />
  }
```

- [ ] **Step 3: Write `DialogueView`**

The store owner, mirroring `AskView`: `useMemo` one store per project, read
slices through the hook, reach actions through `getState()` in handlers.

```tsx
  const store = useMemo(
    () => createDialogueStore({ dialogues, projectId }),
    [dialogues, projectId],
  )
```

`dialogues`, plural, off `useContainer()`.

- [ ] **Step 4: Extend the route test — which is already failing**

`routes.test.ts` ends with `test('covers every facet the module declares')`,
asserting its `cases` table against `FACETS` itself rather than a hand-copied
list. **Adding the facet in Step 1 turned that red**, naming `dialogue` as the
untested one — run it now and see, before adding the case:

Run: `cd frontend && npx vitest run src/presentation/routing/routes.test.ts`

Expected: FAIL on the coverage assertion. Then add one entry to `cases` in the
shape its neighbours use — `{ facet: 'dialogue', selection: { facet: 'dialogue',
id: 'd1' } }` — which gives the facet its round-trip, its truncation case
(`#/p/abc/dialogue` with nothing after it) and its coverage in one line, because
all three blocks iterate the table.

Re-run. Expected: PASS.

- [ ] **Step 5: Write the browser test**

Create `DialoguePage.browser.test.tsx`. jsdom cannot judge any of this:

```tsx
/** That a dialogue reads as a conversation with two speakers.
 *
 * jsdom applies no stylesheet, so `getComputedStyle` returns only what an
 * inline style said and every colour assertion below is meaningless there.
 * This is the suite that can judge them.
 */
import { expect, it } from 'vitest'
import { render } from 'vitest-browser-react'

it('draws the dialogue’s question and the reader’s answer as visibly different things', async () => {
  const screen = await render(/* DialoguePage with one exchange, in a .md.doc flow */)

  const question = screen.container.querySelector('[data-testid="dlg-question"]') as HTMLElement
  const answer = screen.container.querySelector('[data-testid="dlg-answer"]') as HTMLElement

  // Compared against each other rather than to literals, so a token value
  // change does not fail this. If these match, the transcript is a wall of
  // identical paragraphs and a reader cannot tell who is speaking -- which is
  // the failure a jsdom test cannot see at all.
  expect(getComputedStyle(question).backgroundColor).not.toBe(
    getComputedStyle(answer).backgroundColor,
  )

  // An undefined custom property sets no background and resolves to a
  // transparent computed value, which is how `--bg-raised` would have shipped
  // looking like a rule that worked.
  expect(getComputedStyle(question).backgroundColor).not.toBe('rgba(0, 0, 0, 0)')

  const rect = question.getBoundingClientRect()
  expect(rect.height).toBeGreaterThan(20)
  expect(rect.width).toBeGreaterThan(200)
})

it('keeps the outstanding question below the last exchange on screen', async () => {
  // Order in the document is asserted in jsdom; this asserts order in the
  // layout, which a `position: absolute` or a flex `order` could break while
  // the DOM order stayed correct.
  const screen = await render(/* DialoguePage with one exchange and a pending question */)

  const last = screen.container.querySelector('[data-testid="dlg-exchange-0"]') as HTMLElement
  const pending = screen.container.querySelector('[data-testid="dlg-pending"]') as HTMLElement

  expect(pending.getBoundingClientRect().top).toBeGreaterThanOrEqual(
    last.getBoundingClientRect().bottom,
  )
})
```

Fill both render calls with the real `DialoguePage` and the Task 4 fixtures.

- [ ] **Step 6: Run it**

Run: `cd frontend && npm run test:browser`

Expected: PASS. Not in `verify`, not in CI — it runs only because someone ran it.
No other vitest process at the same time.

- [ ] **Step 7: Prove the colour assertion red**

Delete the `background` declaration from `.dlg-question` and re-run
`npm run test:browser`. Expected: the first test fails on the transparent
comparison. Restore it.

- [ ] **Step 8: Wiring — the whole chain**

| Link | Where | Confirm |
| --- | --- | --- |
| facet registered | `FACETS` | `'dialogue'` present |
| region total | `regionOf` | compiles |
| intercepted | `App.tsx` | returns `DialogueView` |
| store owned | `DialogueView` | `useContainer().dialogues` |
| container key | `container.ts` | plural |
| frames parsed | `dialogue-repository.ts` | Task 2 |
| fold | `domain/dialogue` | Task 1 |

Run: `cd frontend && npx vitest run src/presentation/ src/application/ src/domain/`

Expected: PASS.

- [ ] **Step 9: Gates and the committed build**

Run: `cd frontend && npm run verify` then `cd frontend && npm run build`

- [ ] **Step 10: Commit**

```bash
git add frontend/src/presentation/routing/routes.ts \
  frontend/src/presentation/project/ProjectView.tsx frontend/src/app/App.tsx \
  frontend/src/presentation/dialogue/ frontend/src/presentation/routing/routes.test.ts \
  research_team/interfaces/web/static
git commit -m "Give the dialogue a place on the project

One FACETS entry, one regionOf arm, one App.tsx intercept -- the grammar
already supported it. regionOf is total over Facet by design, so adding the
facet failed the type check until the arm existed, which is the guard that
makes a facet unforgettable. Watched it go red before adding the arm.

key is the dialogue id and not the project. Switching dialogues within one
project must remount the store, or the second inherits the first's transcript
-- which looks like a resumed conversation and is not one.

The browser test asserts the two speakers are visibly different, which jsdom
cannot judge at all: it applies no stylesheet, so getComputedStyle returns only
what an inline style said. Compared against each other rather than to literals
so a token change does not fail it, and against transparent so an undefined
custom property cannot pass. Proved red by deleting the question's background."
```

---

### Task 6: Progress a reader can see (B114)

> **Reviewer: this task is the odd one out in this plan, deliberately.** The five
> before it touch only `frontend/src`; this one adds a Python route, an
> integration test, and a `BACKLOG.md` edit alongside its client changes. It is
> here rather than in a backend plan because the property it delivers —
> answers surviving a refresh — is the entire argument for a dialogue being its
> own principal (design §3), and a console that shipped without it would ship
> the claim without the thing. A different review shape for one task is the
> smaller cost; splitting the property from the page that demonstrates it is the
> larger one. Expect a Python diff and review it as such.

**Files:**
- Modify: `research_team/interfaces/web/app.py` — `GET /api/projects/{project_id}/dialogues/{dialogue_id}/progress`
- Create: `tests/integration/test_socratic_progress_route.py`
- Modify: `frontend/src/infrastructure/http/dialogue-repository.ts` — `progress`
- Modify: `frontend/src/application/dialogue/dialogue-store.ts` — fold it in
- Modify: `frontend/src/presentation/dialogue/DialoguePage.test.tsx`
- Modify: `BACKLOG.md` — close B114

**Interfaces:**
- Consumes: `socratic.progress_for(dialogue_id)`, `progress_view`.
- Produces: `{"scope": "dialogue", "dialogueId": "...", "items": {...}}` keyed by
  `f"turn/{position}"` → `{componentId: item}`; and on the client
  `DialogueProgress = { readonly items: Readonly<Record<string, ItemProgress>> }`.

- [ ] **Step 1: Write the failing route test**

Create `tests/integration/test_socratic_progress_route.py`. Assert on **stored
values through the route**, never on the status alone — an empty `items` is the
right answer for a dialogue nobody has answered anything in, so a test asserting
only 200 passes against a route that reads the wrong id:

```python
async def test_a_recorded_attempt_is_readable_back(client):
    """B114: the attempts route records against the dialogue id and, until this
    route existed, nothing could read it. The property the attempts route was
    built for -- widgets that stay filled in across a reload, the thing that
    distinguishes this surface from the ask -- was real in the log and
    invisible in the browser.

    Red against a route that resolves through `_load(session_id)`: a dialogue
    id is not a session id and that path 404s.
    """
    http, application = client
    project_id = await _project(http)
    dialogue_id = await _dialogue_with_an_mcq(http, project_id)
    await http.post(
        f"/api/projects/{project_id}/dialogues/{dialogue_id}/attempts",
        json={"position": 0, "component_id": "council-1", "response": 0},
    )

    response = await http.get(
        f"/api/projects/{project_id}/dialogues/{dialogue_id}/progress"
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["items"]["turn/0"]["council-1"]["correct"] is True


async def test_a_dialogue_from_another_project_is_a_404(client): ...
async def test_an_untouched_dialogue_answers_an_empty_map_not_a_404(client): ...
```

Write the two stubs out in full following the first's shape.

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/integration/test_socratic_progress_route.py -x`

Expected: FAIL — 404, the route does not exist.

- [ ] **Step 3: Add the route**

Beside the attempts route. It checks the dialogue belongs to the project the
same way its neighbours do, then reads `socratic.progress_for(dialogue_id)`.

**Build the third shape here; do not widen `progress_view`.** It already has two
(`scope: "file"` keyed by component id, and the unnarrowed one keyed by path *and*
component id), and this is a third: `scope: "dialogue"`, keyed
`turn/{position}` then component id, because a component id is only unique
within one utterance. Passing a fake `path` to reuse the file-narrowed shape
would be worse than either.

Widening the shared presenter is the smaller diff and the more dangerous one: a
presenter shared by two surfaces, widened so a third can reuse it, is how
surfaces couple without anyone deciding to couple them. **The cost of the third
shape, stated rather than hidden: it is a third thing to keep true**, and a
change to how progress is reported now has three call sites to check instead of
two. That is the trade, and it is taken deliberately.

Put that reasoning in the route's docstring, not only here.

- [ ] **Step 4: Run to verify it passes, then wire the client**

Add `progress` to `HttpDialogueRepository`, call it from the store after a
successful attempt and on mount, and render a filled-in widget state.

- [ ] **Step 5: Close B114**

Edit its entry to record what landed and where, in the register the file's other
closed entries use.

- [ ] **Step 6: Wiring**

Run: `uv run pytest tests/integration/ -k socratic -v` and
`cd frontend && npx vitest run src/`

Expected: PASS both.

- [ ] **Step 7: All five gates**

- `uv run ruff check .`
- `uv run ruff format --check .`
- `uv run pytest`
- `cd frontend && npm run verify`
- `cd frontend && npm run build`, then
  `git status --porcelain research_team/interfaces/web/static` — anything printed
  belongs in the commit.

- [ ] **Step 8: Commit**

```bash
git add research_team/interfaces/web/app.py tests/integration/test_socratic_progress_route.py \
  frontend/src BACKLOG.md research_team/interfaces/web/static
git commit -m "Let a reader see the answers the dialogue remembered (B114)

The attempts route has recorded against the dialogue id since 95076c9 and
nothing could read it back: the only progress read route resolves its id
through _load(session_id) and cannot serve a dialogue id, and progress_for is
in-process only. So the property that route was built for -- widgets that stay
filled in across a reload, which is what distinguishes this surface from the
ask -- was real in the event log and invisible in the browser.

scope is 'dialogue', a third shape beside 'file' and the unnarrowed one. The
keys differ because the addressing does: a dialogue's items are keyed by
turn/{position} and then by component id, because a component id is only unique
within one utterance.

The test asserts a stored verdict through the route rather than a 200. An empty
items map is the right answer for a dialogue nobody has answered anything in,
so a status-only assertion passes against a route reading the wrong id
entirely."
```

---

## Self-review

**Spec coverage — §6 and the parts of §3/§5 that surface here.**

| Spec | Where |
| --- | --- |
| §6 one `FACETS` entry, one `regionOf` arm, total over `Facet` | Task 5, with the compile failure watched |
| §6 one `App.tsx` intercept, as `ask` does | Task 5 |
| §6 a dialogue has a better claim to a URL segment than an ask | Task 5 — the facet carries an id and `key` uses it |
| §5 goal and stopping condition **visible to the reader** | Tasks 3 and 4 |
| §5 the pending question renders after the last turn | Task 4, two tests |
| §3 `mcq`/`cloze` gradeable in-dialogue, attempts against the dialogue id | Task 6 — the read side; the write side landed in Plan 2 |
| §3 "the surface where components can finally be graded and remembered" | Task 6 — remembering is only real once it is readable |
| §9 the four gates plus the fifth | every task; Task 6 Step 7 checks the tree |
| §9 measurements in a browser test | Task 5 |
| §7 out: multi-reader, cross-project resumption | untouched |

**What I could not plan cleanly:**

1. **The delta channel ships the answer key, and this plan cannot fix it.**
   `_socratic_frame` emits `delta` frames from `to_activity_delta`, which carries
   the main agent's prose verbatim — so a model writing an `mcq` streams the raw
   fence with `correct: true` before the withheld `prompt` frame arrives. Plan 2's
   `test_the_answer_key_never_reaches_the_reader` does not cover it: its stub
   executor emits no deltas. This plan's fold refuses to render delta text, which
   takes the leak from "on screen" to "in the network tab" — **but the bytes still
   go over the wire, and closing that is a server change on Plan 2's surface.**
   Flagged for routing rather than silently absorbed. I did not widen this plan to
   include it because it needs its own measurement against a real streaming model,
   which is a different kind of test from anything here.
2. **Task 6 is a Python task inside a frontend plan.** B114 assigns it here and
   the reasoning holds — the property is the whole argument for this surface being
   its own principal — but it means one task in this plan touches `app.py` and
   `BACKLOG.md` and has a different review shape from the five before it. The
   alternative was shipping a console that claims answers survive a refresh while
   nothing reads them back.
3. **`progress_view`'s two existing shapes do not fit**, so Task 6 builds a third
   (`scope: "dialogue"`, keyed by `turn/{position}` then component id) rather than
   passing a fake `path` to reuse the file-narrowed one. That is a judgement call
   about a presenter I did not write; if the lead would rather widen
   `progress_view` itself, that is a smaller diff and a wider blast radius.

**Inline decisions worth knowing:**

- **Deltas drive a `composing` flag and nothing else** — the headline ruling
  above. `composing` is a field on the turn rather than `activity.length > 0`,
  because a turn whose model ran a tool and went quiet has activity and is not
  composing.
- **`answered`, not `asked`.** The reader's move opens a turn on this surface.
- **The ask's fold, store and turn component are not reused; `AskActivity`,
  `Citation` and `LessonDocument` are.** The direction is what differs; activity,
  citations and blocks are the same things.
- **Two direction tests, not one.** Which element holds which text, *and* which
  comes first in the document — the per-element assertion cannot catch an ordering
  swap, which Task 4 Step 5 proves.
- **`key={`${id}:${selection.id ?? 'new'}`}` on the intercept**, not `key={id}`.
  Switching dialogues within a project must remount the store or the second
  inherits the first's transcript.
- **The store guards `start` as well as `send`.** Framing calls a model and takes
  seconds; a double-click would mint two dialogues and strand the first, which is
  a stream nobody can reach again.
- **A framing failure surfaces as an error with a null `dialogueId`**, so the page
  does not land on an empty dialogue whose composer 404s on every send.
- **`concluded` is rendered now and is always false** until Plan 4; its test
  constructs the state directly and says so.

**Placeholder scan.** No "TBD", no "add error handling", no "write tests for the
above". Three places deliberately say "mirror the neighbour and match it":
`ask-repository.ts`'s buffering loop (Task 2), `createAskStore`'s body (Task 3),
and `AskView`'s `useMemo` (Task 5) — all structural copies where inventing a
second shape is the risk, and all name the exact file. Task 5's browser test has
two `/* … */` render placeholders with the instruction to fill them from Task 4's
fixtures; Task 6's Steps 1 and 4 name two test bodies to write out in full rather
than showing them, which is the one place this plan is thinner than the five
before it — Task 6 is a follow-on whose shape is fully determined by the three
tests above it.

**Type consistency.** `DialogueTurn`, `DialogueTranscript`, `DialogueEvent`,
`applyEvent`, `answered`, `composing` are spelled identically in Tasks 1, 3 and 4.
`DialogueRepository`, `HttpDialogueRepository`, `start`, `reply`,
`submitDialogueAttempt`, `progress` are identical in Tasks 2, 3 and 6. The
container key is `dialogues` at every mention. The wire keys —
`dialogue_id`/`goal`/`stopping_condition`/`pending_blocks` on the frame,
`dialogueId`/`goal`/`stoppingCondition`/`openingBlocks`/`pendingBlocks` on the
route, `blocks`/`reply`/`position`/`citations`/`recordedAt` on a turn — are read
from `app.py` at `b3300f1` and appear once, in the contract table at the top,
which is what Tasks 1 and 2 are written against. **No `text` key appears on any
`prompt` frame or turn anywhere in this plan.**
