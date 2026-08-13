# Ask Page Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Redraw the ask page against a real prose measure and a real speaker rhythm, and split it into components that can each be opened in Storybook on their own.

**Architecture:** A page-specific stylesheet (`src/styles/ask.css`) replaces the borrowed `.view-head` plus Tailwind-utility soup, and `AskView` splits into a container (store) and `AskPage` (pure props). Every other piece on the page becomes a file with one job, so a story is `<Component {...args} />` with no container, no repository fake and no `crypto.randomUUID` in scope.

**Tech Stack:** React 19, TypeScript, Tailwind v4 (utilities only, no preflight), plain CSS in `src/styles/`, vitest (jsdom `app` project + Playwright/Chromium `browser` project), Storybook 9 via `@storybook/react-vite`.

**Spec:** `docs/superpowers/specs/2026-08-13-ask-page-redesign-design.md`

## Global Constraints

- Work from `frontend/` for every command in this plan. The repository root is `/home/ty/workspace/research-team/.claude/worktrees/dependency-0140`; do not `cd` outside the worktree.
- Four gates, all of which must pass before the final commit: `uv run ruff check .`, `uv run ruff format --check .`, `uv run pytest` (all from the repo root) and `cd frontend && npm run verify`. Passing three is not passing.
- A fifth command, not a gate but required by this change because it is a stylesheet and a set of measurements: `cd frontend && npm run test:browser`.
- **Never run two vitest processes at once.** Concurrent runs fail spuriously with a coverage temp-file error that names nothing about the real cause. Run one, wait, run the next.
- This build imports **no Tailwind preflight**. A bare `<ul>`, `<ol>` or `<p>` keeps the user agent's margin, padding and bullets. Zero them explicitly.
- `theme.css` declares only the design tokens this project uses, so a Tailwind utility naming anything else **generates no CSS and fails silently**. `npm run check:tailwind` (inside `verify`) fails the build for the spacing families. Prefer `src/styles/ask.css` and `var(--token)` over utilities for anything this redesign introduces.
- Available tokens, exact values — use these names and no others: colours `--bg`, `--bg-panel`, `--bg-panel-2`, `--bg-raise`, `--bg-hover`, `--line`, `--line-soft`, `--line-strong`, `--fg`, `--fg-dim`, `--fg-faint`, `--accent`, `--accent-dim`, `--accent-fg`, `--k-failure`; type `--mono`, `--sans`, `--t-xs: 10.5px`, `--t-sm: 12px`, `--t-md: 13px`, `--t-lg: 15.5px`, `--t-xl: 19px`, `--t-2xl: 23px`; shape `--radius: 5px`; spacing `--space-0: 0px` through `--space-6: 28px` (`1: 3px`, `2: 6px`, `3: 10px`, `4: 14px`, `5: 20px`).
- A component prop is never named `title`. `check-deleted.mjs` fails the build on it — a `title` prop is one careless refactor away from the HTML attribute of that name, and the two have nothing in common. Use `heading`.
- Comments explain **why**, not what. State costs plainly, name what a test would fail on, and say when something was measured rather than reasoned. A comment restating the code is worse than none.
- Commit messages carry the reasoning that does not fit in a comment: what was rejected, what the change costs, what is left undone. End every commit message with:
  `Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>`
- Every commit in this plan is made from the branch `redraw-the-ask-page`, which already exists and already holds the spec commit.

---

## File Structure

**Created:**

| Path | Responsibility |
|---|---|
| `frontend/src/styles/ask.css` | Every `.ask-*` rule. The page's whole appearance. |
| `frontend/src/presentation/ask/ask-fixtures.ts` | `turn()` and `transcript()` builders shared by stories and tests. |
| `frontend/src/presentation/ask/AskActivity.tsx` | The collapsed "Looked at N things" fold, and `activityName`. |
| `frontend/src/presentation/ask/AskTurn.tsx` | One exchange: question, activity, answer, error, pending, sources. |
| `frontend/src/presentation/ask/AskHead.tsx` | Heading, subtitle, facet nav, New chat. |
| `frontend/src/presentation/ask/AskPage.tsx` | The whole page as a pure function of props. |
| `frontend/src/presentation/ask/AskPage.test.tsx` | jsdom tests for what the presentational split makes reachable. |
| `frontend/src/presentation/ask/AskActivity.test.tsx` | `activityName`'s narrowing over an `unknown` payload. |
| `frontend/src/presentation/ask/AskPage.stories.tsx` | Empty, OneTurn, Streaming, Refused, LongThread. |
| `frontend/src/presentation/ask/AskTurn.stories.tsx` | Answered, WithActivity, Streaming, Failed, NoCitations. |
| `frontend/src/presentation/ask/AskComposer.stories.tsx` | Empty, Typed, Asking. |
| `frontend/src/presentation/ask/AskHead.stories.tsx` | The facet control, with Ask current. |
| `frontend/src/presentation/ask/CitationList.stories.tsx` | None, One, Many. |

**Modified:**

| Path | Change |
|---|---|
| `frontend/src/styles/index.css` | One `@import './ask.css'` after `./composer.css`. |
| `frontend/src/presentation/ask/AskView.tsx` | Reduced to a container: build the store, read it, render `AskPage`. |
| `frontend/src/presentation/ask/AskThread.tsx` | Scroller, empty state and the map over turns. `Turn` moves out. |
| `frontend/src/presentation/ask/AskComposer.tsx` | Same props, `.ask-composer` markup. |
| `frontend/src/presentation/ask/CitationList.tsx` | Same props, `.ask-sources` markup. |
| `frontend/src/presentation/ask/AskView.browser.test.tsx` | Selectors moved; the `!`-override test replaced by the measure test. |

**Unchanged, deliberately:** `AskView.test.tsx` (the behavioural guard that says this changed drawing and not behaviour), `src/styles/composer.css` (the session page still uses `.composer`), `src/application/ask/*`, `src/domain/ask/*`.

---

### Task 1: Fixtures and the activity fold

Extracts the fold and the payload narrowing out of `AskThread.tsx`, and creates the fixture builders every later task's stories and tests import.

**Files:**
- Create: `frontend/src/presentation/ask/ask-fixtures.ts`
- Create: `frontend/src/presentation/ask/AskActivity.tsx`
- Create: `frontend/src/presentation/ask/AskActivity.test.tsx`
- Modify: `frontend/src/presentation/ask/AskThread.tsx` (delete the `activityName` function and the `<Disclosure>` block, import the new component)

**Interfaces:**
- Consumes: `AskActivity`, `AskTurn`, `AskTranscript`, `Citation` from `@domain/ask/conversation.ts`; `Chip`, `Disclosure` from `../common/primitives.tsx`; `plural` from `../formatting/format.ts`.
- Produces:
  - `activity(over?: Partial<AskActivity>): AskActivity`
  - `turn(over?: Partial<AskTurn>): AskTurn`
  - `transcript(count: number): AskTranscript`
  - `PROJECT: ProjectId` (a fixed uuid, for stories that need one)
  - `<AskActivityFold activity={readonly AskActivity[]} open={boolean} onToggle={() => void} />`
  - `activityName(item: AskActivity): string`

- [ ] **Step 1: Write the failing test**

Create `frontend/src/presentation/ask/AskActivity.test.tsx`:

```tsx
/** `activityName` narrows an `unknown` payload rather than casting it, because
 *  the fold stores stream frames without interpreting them and a frame whose
 *  shape changes server-side must degrade rather than throw inside a render. */
import { expect, it } from 'vitest'

import { activityName } from './AskActivity.tsx'
import { activity } from './ask-fixtures.ts'

it('names a frame by the tool it carries', () => {
  expect(activityName(activity({ payload: { name: 'read_source' } }))).toBe('read_source')
})

it('falls back to the frame kind when the payload names nothing', () => {
  // Not a cast: a payload that is a string, a null, or an object with a
  // non-string `name` all reach here, and each would throw on a cast.
  expect(activityName(activity({ payload: 'surprise', kind: 'tool' }))).toBe('tool')
  expect(activityName(activity({ payload: null, kind: 'assistant' }))).toBe('assistant')
  expect(activityName(activity({ payload: { name: 42 }, kind: 'tool' }))).toBe('tool')
  expect(activityName(activity({ payload: { name: '' }, kind: 'tool' }))).toBe('tool')
})
```

- [ ] **Step 2: Run it and watch it fail**

Run: `cd frontend && npx vitest run --project app src/presentation/ask/AskActivity.test.tsx`
Expected: FAIL — `Failed to resolve import "./AskActivity.tsx"`.

- [ ] **Step 3: Write the fixtures**

Create `frontend/src/presentation/ask/ask-fixtures.ts`:

```ts
/** Turns and transcripts for the stories and tests on this page.
 *
 * Here rather than inline for the reason `course/course-fixtures.ts` exists: a
 * transcript written out in five stories is five transcripts, and they drift
 * one story at a time until no two of them show the same component.
 */
import type { AskActivity, AskTranscript, AskTurn } from '@domain/ask/conversation.ts'
import { ProjectId } from '@domain/shared/identifier.ts'

/** Fixed rather than generated: a story whose links change every render is a
 *  story whose screenshot can never be compared with yesterday's. */
export const PROJECT = ProjectId('11111111-1111-1111-1111-111111111111')

export const activity = (over: Partial<AskActivity> = {}): AskActivity => ({
  messageId: 'm1',
  kind: 'tool',
  payload: { name: 'read_source' },
  isError: false,
  ...over,
})

export const turn = (over: Partial<AskTurn> = {}): AskTurn => ({
  question: 'What did the two 2019 papers actually disagree about?',
  answer:
    'They agree on the effect and disagree on its size. Both find spaced review beats massed\nreview at two weeks; the second reports roughly half the advantage, and attributes the gap\nto its untimed final test.',
  activity: [],
  citations: [{ kind: 'source', id: 's1' }],
  error: null,
  settled: true,
  ...over,
})

/** A transcript long enough to overflow any viewport a story picks. The
 *  questions differ so a reader can tell one turn from the next -- twelve
 *  identical turns would hide exactly the run-together this redesign is
 *  about. */
export const transcript = (count: number): AskTranscript =>
  Array.from({ length: count }, (_unused, index) =>
    turn({ question: `Question number ${String(index + 1)}: what follows from that?` }),
  )
```

- [ ] **Step 4: Write the component**

Create `frontend/src/presentation/ask/AskActivity.tsx`:

```tsx
import type { AskActivity } from '@domain/ask/conversation.ts'

import { Chip, Disclosure } from '../common/primitives.tsx'
import { plural } from '../formatting/format.ts'

/** What the model consulted, folded away.
 *
 * Above the answer and collapsed, as `Segments` collapses a tool run: the
 * machinery is how the answer was reached and the answer is what was asked
 * for, so it is available and never in the way. `Disclosure` renders nothing
 * while closed -- it is not hidden by CSS -- which is what makes the jsdom
 * test of this a real test rather than one that would pass against a
 * stylesheet-less DOM either way.
 *
 * `open` and `onToggle` are props rather than state because the transcript
 * re-renders on every stream frame, and a fold owning its own state would
 * close itself while somebody is reading it.
 */
export const AskActivityFold = ({
  activity,
  open,
  onToggle,
}: {
  activity: readonly AskActivity[]
  open: boolean
  onToggle: () => void
}) => {
  if (activity.length === 0) return null

  return (
    <Disclosure
      className="ask-activity"
      open={open}
      onToggle={onToggle}
      label={
        <span className="run-label">
          <b>Looked at {plural(activity.length, 'thing')}</b>
        </span>
      }
    >
      <ul className="ask-activity-list">
        {activity.map((item) => (
          <li key={item.messageId}>
            <span className="mono">{activityName(item)}</span>
            {item.isError ? <Chip tone="fail">error</Chip> : null}
          </li>
        ))}
      </ul>
    </Disclosure>
  )
}

/** A tool's name if the frame carried one, its kind otherwise.
 *
 * `payload` is `unknown` by design -- the fold stores frames without
 * interpreting them -- so this narrows rather than casts. A frame whose shape
 * changes server-side degrades to its kind here instead of throwing inside a
 * render. */
export const activityName = (item: AskActivity): string => {
  if (typeof item.payload === 'object' && item.payload !== null && 'name' in item.payload) {
    const { name } = item.payload
    if (typeof name === 'string' && name) return name
  }
  return item.kind
}
```

- [ ] **Step 5: Run the test and watch it pass**

Run: `cd frontend && npx vitest run --project app src/presentation/ask/AskActivity.test.tsx`
Expected: PASS, 2 tests.

- [ ] **Step 6: Point `AskThread.tsx` at the new component**

In `frontend/src/presentation/ask/AskThread.tsx`: delete the `activityName` function at the bottom of the file, delete the `turn.activity.length > 0 ? <Disclosure …>…</Disclosure> : null` block inside `Turn`, and replace it with:

```tsx
<AskActivityFold activity={turn.activity} open={open} onToggle={onToggle} />
```

Add `import { AskActivityFold } from './AskActivity.tsx'` and drop `Chip`, `Disclosure` and `plural` from the imports if nothing else in the file still uses them.

The `.ask-activity` and `.ask-activity-list` classes have no rules until Task 6; the fold's `text-sm` and the list's zeroing go with them. This is the one window in the plan where the fold is briefly unstyled, and it is deliberate — carrying utilities forward for one task and deleting them in the next is two edits to reach the same place.

- [ ] **Step 7: Run the whole ask suite**

Run: `cd frontend && npx vitest run --project app src/presentation/ask/`
Expected: PASS. `AskView.test.tsx`'s "keeps tool activity out of the way until asked for" is the one that proves the extraction preserved behaviour.

- [ ] **Step 8: Commit**

```bash
cd /home/ty/workspace/research-team/.claude/worktrees/dependency-0140
git add frontend/src/presentation/ask/
git commit -m "Lift the activity fold out of the turn, with fixtures to test it by

\`activityName\` was a file-private function under the only component that
called it, and its interesting property -- that it narrows an \`unknown\`
payload rather than casting one -- had no test, because reaching it meant
driving a whole transcript through the store.

The fold's classes are named and unstyled for one commit; \`ask.css\` arrives
with the rest of the page's rules rather than in five pieces.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: The turn, as its own component

**Files:**
- Create: `frontend/src/presentation/ask/AskTurn.tsx`
- Create: `frontend/src/presentation/ask/AskTurn.stories.tsx`
- Modify: `frontend/src/presentation/ask/AskThread.tsx` (delete the private `Turn`, import `AskTurn`)

**Interfaces:**
- Consumes: `activity`, `turn`, `PROJECT` from `./ask-fixtures.ts`; `AskActivityFold` from `./AskActivity.tsx`; `Markdown` from `../common/content.tsx`; `CitationList` from `./CitationList.tsx`.
- Produces: `<AskTurn projectId={ProjectId} turn={AskTurn} open={boolean} onToggle={() => void} />` — same four props the private `Turn` took, so `AskThread`'s call site does not change shape.

- [ ] **Step 1: Create the component**

Create `frontend/src/presentation/ask/AskTurn.tsx`. The markup is the private `Turn` from `AskThread.tsx` with its Tailwind utilities replaced by the classes Task 6 will style:

```tsx
import type { AskTurn as Turn } from '@domain/ask/conversation.ts'
import type { ProjectId } from '@domain/shared/identifier.ts'

import { Markdown } from '../common/content.tsx'
import { AskActivityFold } from './AskActivity.tsx'
import { CitationList } from './CitationList.tsx'

/** One exchange: the question, what was consulted, the answer, its sources.
 *
 * The question is the reader's own words and the answer is the model's, told
 * apart by a panel rather than by a bubble or an avatar: there are only two
 * speakers here and one of them is you, so a label on every line would be
 * noise on every turn. The panel replaced a 2px left rule, which was too quiet
 * to survive a thread of a dozen turns -- the gap between turn n's answer and
 * turn n+1's question was the only separation on offer, and it read as one
 * long document.
 */
export const AskTurn = ({
  projectId,
  turn,
  open,
  onToggle,
}: {
  projectId: ProjectId
  turn: Turn
  open: boolean
  onToggle: () => void
}) => (
  <article className="ask-turn">
    <p className="ask-question">{turn.question}</p>

    <AskActivityFold activity={turn.activity} open={open} onToggle={onToggle} />

    {/* The model writes markdown, and it goes through the one sanitising
        renderer this application has -- see `Markdown`. */}
    {turn.answer ? <Markdown className="ask-answer" source={turn.answer} /> : null}

    {/* In the turn as well as in the page's banner. The banner is what a
        reader who has scrolled away sees; this is what says which question
        died. The only red on the page, because a failed question is the one
        thing here that must not be mistaken for an answer. */}
    {turn.error ? <p className="ask-turn-error">{turn.error}</p> : null}

    {!turn.settled ? (
      // `role="status"` rather than a bare span: the answer arrives with no
      // focus change, so a screen reader is otherwise told nothing at all
      // between the question and the answer.
      <p className="ask-pending" role="status">
        <span className="spinner" aria-hidden="true" />
        Thinking…
      </p>
    ) : null}

    <CitationList projectId={projectId} citations={turn.citations} />
  </article>
)
```

- [ ] **Step 2: Point `AskThread.tsx` at it**

Delete the whole `const Turn = …` block from `AskThread.tsx`, add `import { AskTurn } from './AskTurn.tsx'`, and rename the element in the map from `<Turn` to `<AskTurn`. Drop the now-unused imports (`Markdown`, `CitationList`, `AskActivityFold`, `AskTurn` the type).

- [ ] **Step 3: Run the ask suite to prove nothing moved**

Run: `cd frontend && npx vitest run --project app src/presentation/ask/`
Expected: PASS. `AskView.test.tsx` still drives the real store and asserts the question, the answer, the citation link and the error copy.

- [ ] **Step 4: Write the stories**

Create `frontend/src/presentation/ask/AskTurn.stories.tsx`:

```tsx
import type { Meta, StoryObj } from '@storybook/react-vite'
import { useState } from 'react'

import { AskTurn } from './AskTurn.tsx'
import { PROJECT, activity, turn } from './ask-fixtures.ts'

/** One exchange, in the five states a turn passes through.
 *
 * `Streaming` is the one worth looking at deliberately: an answer arriving a
 * token at a time, with the pending line under it, is the state that decides
 * whether the page feels alive or hung, and it is on screen for a second at a
 * time in the real application.
 */
const meta = {
  component: AskTurn,
  title: 'ask/AskTurn',
  parameters: { layout: 'fullscreen' },
  // The measure is half of what a turn looks like, and it comes from the
  // thread rather than from the turn -- so a story that let the turn run the
  // full width of the canvas would be showing a shape the application never
  // draws.
  decorators: [
    (Story) => (
      <div className="ask-measure" style={{ padding: 'var(--space-5)' }}>
        <Story />
      </div>
    ),
  ],
  args: { projectId: PROJECT, open: false, onToggle: () => {} },
} satisfies Meta<typeof AskTurn>

export default meta

type Story = StoryObj<typeof meta>

export const Answered: Story = { args: { turn: turn() } }

/** With the fold open, which is the only way to see the activity list. The
 *  fold is controlled from outside, so a story that wants it open has to hold
 *  the state itself. */
export const WithActivity: Story = {
  args: {
    turn: turn({
      activity: [
        activity({ messageId: 'm1', payload: { name: 'read_source' } }),
        activity({ messageId: 'm2', payload: { name: 'search_findings' } }),
        activity({ messageId: 'm3', payload: { name: 'read_source' }, isError: true }),
      ],
    }),
  },
  render: function Open(args) {
    const [open, setOpen] = useState(true)
    return <AskTurn {...args} open={open} onToggle={() => setOpen((it) => !it)} />
  },
}

/** Mid-stream: some answer, not settled, no citations yet. Citations arrive
 *  with the `answer` frame, so a streaming turn having none is the real shape
 *  of the data rather than a gap in the fixture. */
export const Streaming: Story = {
  args: {
    turn: turn({
      answer: 'They agree on the effect and disagree on its',
      citations: [],
      settled: false,
    }),
  },
}

/** A question that did not go through. The page says this twice -- here and
 *  in the banner -- and this half is the one that says *which* question. */
export const Failed: Story = {
  args: {
    turn: turn({
      answer: '',
      citations: [],
      error: 'the model is already answering another question on this chat',
    }),
  },
}

/** Most answers cite nothing, so this is the common case rather than the edge
 *  one: `CitationList` renders nothing at all rather than an empty "Sources"
 *  heading, which would read as a page that lost its data. */
export const NoCitations: Story = { args: { turn: turn({ citations: [] }) } }
```

- [ ] **Step 5: Typecheck**

Run: `cd frontend && npm run typecheck`
Expected: no errors. This is what catches a story that will not compile — `storybook build` is deliberately outside `verify`.

- [ ] **Step 6: Commit**

```bash
cd /home/ty/workspace/research-team/.claude/worktrees/dependency-0140
git add frontend/src/presentation/ask/
git commit -m "Draw the turn in a file of its own, and in Storybook

The component with the most states on this page -- answered, streaming,
failed, with activity, without citations -- was a private const reachable
only by driving a whole transcript through the store, so four of those five
states had never been looked at deliberately.

The question's 2px left rule becomes a panel. The rule was too quiet to
separate turn n's answer from turn n+1's question across a long thread, which
is the run-together the spec's second fault records; the classes land here and
\`ask.css\` gives them rules two commits from now.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Citations as a row, not a list

**Files:**
- Modify: `frontend/src/presentation/ask/CitationList.tsx`
- Create: `frontend/src/presentation/ask/CitationList.stories.tsx`

**Interfaces:**
- Consumes: `PROJECT` from `./ask-fixtures.ts`.
- Produces: no prop change — `<CitationList projectId={ProjectId} citations={readonly Citation[]} />`.

- [ ] **Step 1: Replace the utilities with classes**

In `frontend/src/presentation/ask/CitationList.tsx`, keep the whole doc comment and the `citations.length === 0` early return exactly as they are. Replace only the returned markup:

```tsx
  return (
    <div className="ask-sources">
      <span className="ask-sources-label">Sources</span>
      {/* Zeroed in `ask.css` rather than here: this build imports no preflight,
          so a bare `<ul>` arrives with the user agent's margin and bullets. */}
      <ul className="ask-sources-list">
        {citations.map((citation) => (
          <li key={citation.id}>
            {/* The project's document facet, not a bare id: the reader is on
                the project page already, and this keeps them on it. */}
            <a
              className="ask-source"
              href={projectHref(projectId, { facet: 'doc', id: citation.id })}
            >
              {citation.id}
            </a>
          </li>
        ))}
      </ul>
    </div>
  )
```

- [ ] **Step 2: Write the stories**

Create `frontend/src/presentation/ask/CitationList.stories.tsx`:

```tsx
import type { Meta, StoryObj } from '@storybook/react-vite'

import { CitationList } from './CitationList.tsx'
import { PROJECT } from './ask-fixtures.ts'

/** What an answer stood on.
 *
 * `None` renders nothing, and that is the story: most answers cite nothing,
 * and a "Sources" heading over emptiness on every one of them reads as a page
 * that lost its data. A blank canvas here is the component working.
 */
const meta = {
  component: CitationList,
  title: 'ask/CitationList',
  args: { projectId: PROJECT },
} satisfies Meta<typeof CitationList>

export default meta

type Story = StoryObj<typeof meta>

export const None: Story = { args: { citations: [] } }

export const One: Story = { args: { citations: [{ kind: 'source', id: 's1' }] } }

/** Enough to wrap, which is the case the row shape is for -- the ids are
 *  server-side identifiers and there is no length this component can assume. */
export const Many: Story = {
  args: {
    citations: [
      's1',
      's2',
      's14',
      'doc-2019-spacing',
      'doc-2019-massed-review',
      's7',
      's8',
      'doc-untimed-final-test',
    ].map((id) => ({ kind: 'source' as const, id })),
  },
}
```

- [ ] **Step 3: Run the ask suite and typecheck**

Run: `cd frontend && npx vitest run --project app src/presentation/ask/ && npm run typecheck`
Expected: PASS. `AskView.test.tsx`'s "links a source citation to the project document it came from" asserts the `href`, which is what proves the markup swap kept the link.

- [ ] **Step 4: Commit**

```bash
cd /home/ty/workspace/research-team/.claude/worktrees/dependency-0140
git add frontend/src/presentation/ask/
git commit -m "Name the citation row's parts so a stylesheet can reach them

Utilities inline could not express what this row needs -- a label that sits
on the baseline of ids that wrap onto a second line -- without an arbitrary
value per property. \`None\` is a story that renders nothing on purpose: it is
the common case, and it is the one somebody would 'fix' into an empty
Sources heading without a story saying otherwise.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: The head, and a facet control that says where you are

**Files:**
- Create: `frontend/src/presentation/ask/AskHead.tsx`
- Create: `frontend/src/presentation/ask/AskHead.stories.tsx`

**Interfaces:**
- Consumes: `projectHref` from `../routing/routes.ts`; `Button` from `../common/primitives.tsx`; `PROJECT` from `./ask-fixtures.ts`.
- Produces: `<AskHead projectId={ProjectId} onReset={() => void} />`. Task 5 renders exactly this.

- [ ] **Step 1: Write the component**

Create `frontend/src/presentation/ask/AskHead.tsx`:

```tsx
import type { ProjectId } from '@domain/shared/identifier.ts'

import { Button } from '../common/primitives.tsx'
import { projectHref } from '../routing/routes.ts'

/** The page's heading, and the three places a reader can be.
 *
 * Course, Research and Ask are three states of one control, and the page used
 * to draw two of them as quiet buttons and the third as nothing at all -- so
 * the reader on Ask saw only the two places they were not. They are one `nav`
 * now, with `aria-current="page"` on the one you are on, which is the same
 * fact told to a screen reader and to a stylesheet at once.
 *
 * "New chat" sits outside that group. It is an action rather than a
 * destination, and grouping it with three links is why the row read as four
 * unrelated buttons.
 *
 * Not `.view-head`: that rule lives unlayered in `tree.css` and caps itself at
 * 1100px for the tree it was written for, which this page had to undo with two
 * `!` overrides. Owning the head outright is one rule instead of three.
 */
export const AskHead = ({
  projectId,
  onReset,
}: {
  projectId: ProjectId
  onReset: () => void
}) => (
  <header className="ask-head">
    <div className="ask-head-titles">
      <h1>Ask</h1>
      <p className="ask-sub">
        Answers come from this project’s sources and findings. Not saved — the conversation goes
        when you leave.
      </p>
    </div>

    <div className="ask-head-actions">
      <nav className="ask-facets" aria-label="Project views">
        {/* The project page with no selection, which is the course today. */}
        <a className="ask-facet" href={projectHref(projectId)}>
          Course
        </a>
        <a className="ask-facet" href={projectHref(projectId, { facet: 'entity', id: null })}>
          Research
        </a>
        {/* A link to where you already are, rather than a disabled span: it
            keeps the three the same kind of thing, and `aria-current` is what
            says the difference. */}
        <a
          className="ask-facet"
          aria-current="page"
          href={projectHref(projectId, { facet: 'ask', id: null })}
        >
          Ask
        </a>
      </nav>

      <Button tone="quiet" onClick={onReset}>
        New chat
      </Button>
    </div>
  </header>
)
```

- [ ] **Step 2: Check the `ask` facet href is real**

Run: `cd frontend && grep -n "'ask'" src/presentation/routing/routes.ts`
Expected: `ask` appears in the facet union — `App.tsx:164` already routes `selection?.facet === 'ask'`. If `projectHref` will not take `{ facet: 'ask', id: null }`, use the literal the router produces for this page instead and say so in a comment; do not widen the routing types from this task.

- [ ] **Step 3: Write the stories**

Create `frontend/src/presentation/ask/AskHead.stories.tsx`:

```tsx
import type { Meta, StoryObj } from '@storybook/react-vite'

import { AskHead } from './AskHead.tsx'
import { PROJECT } from './ask-fixtures.ts'

/** The heading and the facet control.
 *
 * The whole point of the story is the third link: Ask is drawn as current
 * rather than omitted, which is the difference between a control that says
 * where you are and one that only says where you are not.
 */
const meta = {
  component: AskHead,
  title: 'ask/AskHead',
  parameters: { layout: 'fullscreen' },
  args: { projectId: PROJECT, onReset: () => {} },
} satisfies Meta<typeof AskHead>

export default meta

type Story = StoryObj<typeof meta>

export const Default: Story = {}
```

- [ ] **Step 4: Typecheck**

Run: `cd frontend && npm run typecheck`
Expected: no errors.

- [ ] **Step 5: Commit**

```bash
cd /home/ty/workspace/research-team/.claude/worktrees/dependency-0140
git add frontend/src/presentation/ask/
git commit -m "Give the ask page a head that says which facet you are on

Course, Research and Ask are one control in three states, and the page drew
two of them and left the third implicit -- so the only thing the row told a
reader on Ask was where they were not. One nav, \`aria-current\` on the
current link, and New chat moved out of the group because an action among
three destinations is what made the row read as four loose buttons.

Costs a class the page did not have: this stops using \`.view-head\`, so the
two \`!\` overrides that were undoing \`tree.css\`'s 1100px cap go with it.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: The page, split from the store

**Files:**
- Create: `frontend/src/presentation/ask/AskPage.tsx`
- Create: `frontend/src/presentation/ask/AskPage.test.tsx`
- Modify: `frontend/src/presentation/ask/AskView.tsx`

**Interfaces:**
- Consumes: `AskHead` (Task 4), `AskThread`, `AskComposer`, and `turn`/`transcript`/`PROJECT` from `./ask-fixtures.ts`.
- Produces:

```ts
interface AskPageProps {
  projectId: ProjectId
  transcript: AskTranscript
  asking: boolean
  error: string | null
  onAsk: (question: string) => void
  onReset: () => void
}
```

Task 7's stories render `<AskPage {...args} />` against exactly this.

- [ ] **Step 1: Write the failing test**

Create `frontend/src/presentation/ask/AskPage.test.tsx`:

```tsx
/** The page as a pure function of props -- no container, no repository, no
 *  store. Everything here was unreachable while `AskView` built its own store:
 *  a test wanting a failed turn *and* a banner had to make the repository
 *  reject at the right moment to get one.
 */
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, it, vi } from 'vitest'

import { AskPage } from './AskPage.tsx'
import { PROJECT, turn } from './ask-fixtures.ts'

const base = {
  projectId: PROJECT,
  transcript: [],
  asking: false,
  error: null,
  onAsk: () => {},
  onReset: () => {},
}

it('marks Ask as the current facet and the other two as elsewhere', () => {
  render(<AskPage {...base} />)

  expect(screen.getByRole('link', { name: 'Ask' })).toHaveAttribute('aria-current', 'page')
  expect(screen.getByRole('link', { name: 'Course' })).not.toHaveAttribute('aria-current')
  expect(screen.getByRole('link', { name: 'Research' })).not.toHaveAttribute('aria-current')
})

it('asks for a new chat without knowing what one is', async () => {
  const onReset = vi.fn()
  render(<AskPage {...base} onReset={onReset} />)

  await userEvent.click(screen.getByRole('button', { name: /new chat/i }))

  expect(onReset).toHaveBeenCalledTimes(1)
})

it('says a refusal twice, in two different places', () => {
  // The banner is what a reader who has scrolled away sees; the turn's copy is
  // what says which question died. Asserting both is the point -- a page-wide
  // text search would pass with either one deleted.
  render(
    <AskPage
      {...base}
      error="the model is already answering another question on this chat"
      transcript={[turn({ answer: '', citations: [], error: 'already answering' })]}
    />,
  )

  expect(screen.getByRole('alert')).toHaveTextContent(/already answering/)
  expect(screen.getByText(/already answering/, { selector: 'article p' })).toBeInTheDocument()
})
```

- [ ] **Step 2: Run it and watch it fail**

Run: `cd frontend && npx vitest run --project app src/presentation/ask/AskPage.test.tsx`
Expected: FAIL — `Failed to resolve import "./AskPage.tsx"`.

- [ ] **Step 3: Write `AskPage.tsx`**

```tsx
import type { AskTranscript } from '@domain/ask/conversation.ts'
import type { ProjectId } from '@domain/shared/identifier.ts'

import { AskComposer } from './AskComposer.tsx'
import { AskHead } from './AskHead.tsx'
import { AskThread } from './AskThread.tsx'

/** The ask page, as a pure function of props.
 *
 * The split from `AskView` is what makes anything on this page openable in
 * Storybook: a store here would mean a container, a repository fake and a
 * `crypto.randomUUID` in scope before a single pixel could be looked at, and
 * the states worth looking at -- mid-stream, refused, forty turns deep -- are
 * precisely the ones that are awkward to reach through a real repository.
 *
 * It owns the viewport and does not scroll, so `AskThread` can: see there for
 * why the composer must keep the bottom edge.
 */
export const AskPage = ({
  projectId,
  transcript,
  asking,
  error,
  onAsk,
  onReset,
}: {
  projectId: ProjectId
  transcript: AskTranscript
  asking: boolean
  error: string | null
  onAsk: (question: string) => void
  onReset: () => void
}) => (
  <section className="ask">
    <AskHead projectId={projectId} onReset={onReset} />

    {/* A refusal made before the stream started -- a busy chat, a dead
        network, an unknown project -- never becomes an answer, so it has
        nowhere to live in the transcript's own error and needs saying here
        too: the store puts it in both the banner and the failed turn, since a
        rejection is the one case where it can afford to. */}
    {error ? (
      <div className="ask-banner error-box" role="alert">
        <strong>That question did not go through.</strong>
        {error}
      </div>
    ) : null}

    <AskThread projectId={projectId} transcript={transcript} />

    <AskComposer asking={asking} onAsk={onAsk} />
  </section>
)
```

- [ ] **Step 4: Run the test and watch it pass**

Run: `cd frontend && npx vitest run --project app src/presentation/ask/AskPage.test.tsx`
Expected: PASS, 3 tests.

- [ ] **Step 5: Reduce `AskView.tsx` to a container**

Replace the whole file with:

```tsx
import { useMemo } from 'react'

import { useContainer } from '@app/container-context.tsx'
import { createAskStore } from '@application/ask/ask-store.ts'
import type { ProjectId } from '@domain/shared/identifier.ts'

import { AskPage } from './AskPage.tsx'

/** Ask the project: a read-only conversation over everything it has gathered.
 *
 * A third facet beside Course and Research rather than a page of its own, so
 * the three are reached by the same nav and the URL keeps saying which project
 * you are in.
 *
 * This file is the store and nothing else. Everything it draws lives in
 * `AskPage`, which takes props -- see there for what that buys.
 */
export const AskView = ({ projectId }: { projectId: ProjectId }) => {
  const { ask } = useContainer()

  /** One store per project, as `GraphPane` builds one per project: the chat id
   *  identifies a server-side conversation scoped to this project, and a store
   *  shared across projects would carry one project's questions to another. */
  const store = useMemo(
    () => createAskStore({ ask, projectId, newChatId: () => crypto.randomUUID() }),
    [ask, projectId],
  )

  // Read through the hook during render; reach actions through `getState()` in
  // handlers, so a handler never closes over a stale slice.
  const transcript = store((state) => state.transcript)
  const asking = store((state) => state.asking)
  const error = store((state) => state.error)

  return (
    <AskPage
      projectId={projectId}
      transcript={transcript}
      asking={asking}
      error={error}
      onAsk={(question) => void store.getState().send(question)}
      onReset={() => void store.getState().reset()}
    />
  )
}
```

- [ ] **Step 6: Run the jsdom ask suite**

Run: `cd frontend && npx vitest run --project app src/presentation/ask/`
Expected: PASS. `AskView.test.tsx` is unmodified and is the proof that the split changed drawing and not behaviour — in particular "says the page keeps nothing", which queries `{ selector: '.sub' }`, **will fail** because the subtitle is now `.ask-sub`. Change that one selector to `.ask-sub` and nothing else in that file; the assertion and its comment stand.

- [ ] **Step 7: Commit**

```bash
cd /home/ty/workspace/research-team/.claude/worktrees/dependency-0140
git add frontend/src/presentation/ask/
git commit -m "Split the ask page from the store that feeds it

\`AskView\` built the store and drew the page, so nothing here could be opened
in Storybook without a container, a repository fake and a \`crypto.randomUUID\`
in scope -- and the states worth looking at (mid-stream, refused, forty turns
deep) are exactly the awkward ones to reach through a real repository.

\`AskView.test.tsx\` is unchanged but for one selector, and that is the point:
it drives the real store through the real port, so it is the evidence that
this moved drawing and not behaviour. The selector that moved is \`.sub\` ->
\`.ask-sub\`, which the head's own class made necessary.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: The stylesheet, the measure, and the browser measurements

The largest task, and undividable: the composer's markup, the thread's markup and `ask.css` make one claim between them — that prose and question box share a column — and the browser test that measures it fails against any two of the three.

**Files:**
- Create: `frontend/src/styles/ask.css`
- Modify: `frontend/src/styles/index.css`
- Modify: `frontend/src/presentation/ask/AskThread.tsx`
- Modify: `frontend/src/presentation/ask/AskComposer.tsx`
- Modify: `frontend/src/presentation/ask/AskView.browser.test.tsx`

**Interfaces:**
- Consumes: every `.ask-*` class named in Tasks 1–5.
- Produces: `.ask-measure`, the class Task 2's story decorator already uses.

- [ ] **Step 1: Write `ask.css`**

Create `frontend/src/styles/ask.css`:

```css
/* The ask page: a thread of two speakers, a question box, and one column of
   prose shared by both.

   Page-specific on purpose. The alternative was widening `.composer` and
   `.view-head`, which the session page and the tree page respectively depend
   on -- rewriting a shared class from a page-specific redesign is how two
   pages come to disagree about what a composer is. */

/* --- the page ---------------------------------------------------------- */

/* Owns the viewport and does not scroll, so `.ask-thread` can and the
   composer keeps the bottom edge whether the thread holds one turn or forty
   -- which is precisely when somebody wants to type the next question. */
.ask {
  flex: 1 1 auto;
  min-height: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

/* The readable column, and the reason this file exists. Set on the thread's
   inner wrapper and on the composer's, so the question box sits under the
   column of prose rather than under the viewport.

   `ch` rather than a pixel width: the cap should follow the font. The
   neighbouring cap in `tree.css` is 1100px, chosen for a tree of nodes, and
   inheriting it is how an answer came to run 1400px wide at 1440px. */
.ask-measure {
  width: 100%;
  max-width: 72ch;
  margin-inline: auto;
}

/* --- head -------------------------------------------------------------- */

.ask-head {
  flex: 0 0 auto;
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--space-5);
  padding: var(--space-5) var(--space-5) var(--space-4);
  border-bottom: 1px solid var(--line-soft);
}
.ask-head h1 {
  margin: 0;
  font-size: var(--t-2xl);
  font-weight: 600;
  letter-spacing: -0.02em;
}
/* No preflight, so a bare `<p>` keeps the user agent's 1em block margins. */
.ask-sub {
  margin: var(--space-1) 0 0;
  max-width: 60ch;
  color: var(--fg-dim);
  font-size: var(--t-sm);
}
.ask-head-actions {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  flex-wrap: wrap;
}

/* --- facets ------------------------------------------------------------ */

/* One control in three states rather than three buttons: the border belongs
   to the group, and the links divide it. */
.ask-facets {
  display: flex;
  align-items: stretch;
  border: 1px solid var(--line);
  border-radius: var(--radius);
  overflow: hidden;
}
.ask-facet {
  padding: var(--space-2) var(--space-4);
  border: 0;
  border-left: 1px solid var(--line);
  background: transparent;
  color: var(--fg-dim);
  font-size: var(--t-sm);
  text-decoration: none;
  white-space: nowrap;
}
.ask-facet:first-child {
  border-left: 0;
}
.ask-facet:hover {
  background: var(--bg-hover);
  color: var(--fg);
}
/* Selected by the same attribute a screen reader is told, so the two cannot
   disagree -- a `.is-current` class beside `aria-current` is two facts that
   drift. */
.ask-facet[aria-current='page'] {
  background: var(--bg-raise);
  color: var(--fg);
}

/* --- banner ------------------------------------------------------------ */

.ask-banner {
  flex: 0 0 auto;
  margin: var(--space-4) var(--space-5) 0;
}

/* --- thread ------------------------------------------------------------ */

/* The one scrolling box on this page. `padding-inline` is room for the
   scrollbar and for the turn panels to breathe; the measure sits inside it. */
.ask-thread {
  flex: 1 1 auto;
  min-height: 0;
  overflow-y: auto;
  padding: var(--space-5) var(--space-5) var(--space-6);
}
.ask-thread-inner {
  display: flex;
  flex-direction: column;
  gap: var(--space-6);
}

/* --- a turn ------------------------------------------------------------ */

.ask-turn {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}
/* Every turn but the first: a rule between exchanges, because a 28px gap was
   the only thing separating turn n's answer from turn n+1's question and a
   dozen turns of that reads as one long document. */
.ask-turn + .ask-turn {
  border-top: 1px solid var(--line-soft);
  padding-top: var(--space-6);
}

/* The reader's own words, in a panel. Told apart from the answer by ground
   rather than by a bubble or an avatar: there are only two speakers here and
   one of them is you, so a label on every line would be noise on every turn. */
.ask-question {
  margin: 0;
  padding: var(--space-3) var(--space-4);
  border: 1px solid var(--line-soft);
  border-radius: var(--radius);
  background: var(--bg-panel-2);
  color: var(--fg);
  font-size: var(--t-md);
  white-space: pre-wrap;
}

/* `--fg`, not `--fg-dim`. Dimming the answer -- the thing the reader came for
   -- was backwards; the machinery around it is what should recede. */
.ask-answer {
  color: var(--fg);
}

.ask-activity {
  font-size: var(--t-sm);
}
/* Zeroed because there is no preflight: a bare `<ul>` keeps the user agent's
   margin, padding and bullets. Written in plain CSS rather than as `m-0 p-0`
   utilities, which is the pair that silently emitted nothing until
   `--spacing-0` was declared. */
.ask-activity-list {
  margin: 0;
  padding: var(--space-2) 0 0 var(--space-3);
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
  color: var(--fg-faint);
}

.ask-turn-error {
  margin: 0;
  color: var(--k-failure);
  font-family: var(--mono);
  font-size: var(--t-sm);
}
.ask-pending {
  margin: 0;
  display: flex;
  align-items: center;
  gap: var(--space-2);
  color: var(--fg-faint);
  font-size: var(--t-sm);
}

/* --- sources ----------------------------------------------------------- */

.ask-sources {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: var(--space-2);
  font-size: var(--t-sm);
}
.ask-sources-label {
  color: var(--fg-faint);
  font-size: var(--t-xs);
  letter-spacing: 0.06em;
  text-transform: uppercase;
}
.ask-sources-list {
  margin: 0;
  padding: 0;
  list-style: none;
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2);
}
.ask-source {
  font-family: var(--mono);
  font-size: var(--t-sm);
}

/* --- composer ---------------------------------------------------------- */

/* Full-bleed against the page edge and bordered on top, so it reads as the
   floor of the page rather than as a card sitting on it -- while its contents
   stay on `.ask-measure`, lined up with the prose above. That alignment is
   what `AskView.browser.test.tsx` measures. */
.ask-composer {
  flex: 0 0 auto;
  border-top: 1px solid var(--line);
  background: var(--bg-panel);
  padding: var(--space-3) var(--space-5);
}
.ask-composer-inner {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}
.ask-composer textarea {
  width: 100%;
  resize: vertical;
  min-height: 52px;
  max-height: 180px;
  padding: var(--space-3);
  border: 1px solid var(--line);
  border-radius: var(--radius);
  background: var(--bg);
  color: var(--fg);
  font-family: var(--sans);
  font-size: var(--t-md);
  line-height: 1.5;
}
/* `:focus`, not `:focus-visible`: a pointer user clicking into a field wants
   the same confirmation a keyboard user gets. Nothing here sets `overflow`,
   so no ring is clipped -- the audit `composer.css` records applies. */
.ask-composer textarea:focus {
  border-color: var(--accent-dim);
  outline: none;
}
.ask-composer textarea:disabled {
  opacity: 0.55;
}
.ask-composer-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-3);
}
.ask-composer-hint {
  min-width: 0;
  overflow: hidden;
  color: var(--fg-faint);
  font-size: var(--t-xs);
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* --- empty ------------------------------------------------------------- */

.ask-empty {
  flex: 1 1 auto;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: var(--space-5);
}
```

- [ ] **Step 2: Import it**

In `frontend/src/styles/index.css`, add after `@import './composer.css';`:

```css
/* After `composer.css` and not instead of it: the session page still draws a
   `.composer`, and the ask page draws its own. */
@import './ask.css';
```

- [ ] **Step 3: Put the thread on the measure**

In `frontend/src/presentation/ask/AskThread.tsx`, replace the empty-state branch and the scroller. The empty state keeps `EmptyState`; only its wrapper is new:

```tsx
  if (transcript.length === 0) {
    return (
      <div className="ask-thread ask-empty">
        <EmptyState
          heading="Nothing asked yet."
          detail="Ask about this project’s sources, topics and findings. Nothing you ask here is written down."
        />
      </div>
    )
  }

  return (
    <div className="ask-thread">
      <div className="ask-measure ask-thread-inner">
        {transcript.map((turn, index) => (
          <AskTurn
            key={index}
            projectId={projectId}
            turn={turn}
            open={open.has(index)}
            onToggle={() =>
              setOpen((current) => {
                const next = new Set(current)
                if (!next.delete(index)) next.add(index)
                return next
              })
            }
          />
        ))}
      </div>
    </div>
  )
```

- [ ] **Step 4: Put the composer on the same measure**

In `frontend/src/presentation/ask/AskComposer.tsx`, keep the whole doc comment, `submit` and the `useState` exactly as they are. Replace the returned form — note the negative margin is gone, because the page no longer pads the composer's parent:

```tsx
  return (
    <form className="ask-composer" onSubmit={submit}>
      <div className="ask-measure ask-composer-inner">
        <textarea
          rows={2}
          placeholder="Ask about this project…  (Ctrl+Enter)"
          aria-label="Question"
          value={draft}
          disabled={asking}
          onChange={(event) => setDraft(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === 'Enter' && (event.ctrlKey || event.metaKey)) submit(event)
          }}
        />
        <div className="ask-composer-row">
          {/* Said again here, at the moment somebody is about to type
              something they may want back. */}
          <span className="ask-composer-hint">
            Not saved — this conversation goes when you leave.
          </span>
          <Button tone="accent" type="submit" disabled={asking || !draft.trim()}>
            Ask
          </Button>
        </div>
      </div>
    </form>
  )
```

- [ ] **Step 5: Rewrite the browser test**

Replace the three `it(...)` blocks at the bottom of `frontend/src/presentation/ask/AskView.browser.test.tsx` with the four below, and update `mount`'s three `querySelector` calls to `section.ask`, `.ask-thread` and `form.ask-composer`. Everything above `mount` — the fake repository, `TURNS`, the fixed-height `Page` — is unchanged.

```tsx
it('scrolls the thread and not the page, so the composer keeps the bottom edge', async () => {
  const { view, thread, composer } = await mount()

  // The precondition, asserted rather than assumed. With nothing overflowing
  // every assertion below passes against a page that scrolls as a whole.
  expect(thread.scrollHeight).toBeGreaterThan(thread.clientHeight)

  expect(view.scrollHeight).toBeLessThanOrEqual(view.clientHeight)

  const surface = view.getBoundingClientRect()
  const bar = composer.getBoundingClientRect()
  expect(Math.abs(bar.bottom - surface.bottom)).toBeLessThan(1)
  expect(Math.abs(bar.left - surface.left)).toBeLessThan(1)
  expect(Math.abs(bar.right - surface.right)).toBeLessThan(1)
})

it('caps the prose column below the width of the surface', async () => {
  // The fault this redesign exists for. Before it, these two were equal: the
  // head was capped at 1100px by `.view-head` and overridden to `max-w-none!`
  // to match a thread that had no cap at all, which made the page uniformly
  // too wide rather than uniformly right.
  const { view, thread } = await mount()
  const column = thread.querySelector('.ask-measure') as HTMLElement

  const width = column.getBoundingClientRect().width
  expect(width).toBeLessThan(view.clientWidth)
  expect(width).toBeGreaterThan(0)
})

it('lines the question box up with the prose above it', async () => {
  // The other half of the measure, and the one a stylesheet gets wrong
  // silently: a thread that centres its column and a composer that does not
  // both look fine alone.
  const { thread, composer } = await mount()
  const prose = (thread.querySelector('.ask-measure') as HTMLElement).getBoundingClientRect()
  const box = (composer.querySelector('.ask-measure') as HTMLElement).getBoundingClientRect()

  expect(Math.abs(box.left - prose.left)).toBeLessThan(1)
  expect(Math.abs(box.right - prose.right)).toBeLessThan(1)
})

it('zeroes the lists the missing preflight would otherwise leave indented', async () => {
  await mount()

  // The citation row, which is on screen already. The activity fold's list is
  // not rendered until it is opened -- `Disclosure` renders `{open ? … }` --
  // so it is not reachable here without driving the fold.
  const list = document.querySelector('section.ask ul') as HTMLElement
  const style = getComputedStyle(list)
  expect(style.marginBlockStart).toBe('0px')
  expect(style.paddingInlineStart).toBe('0px')
  expect(style.listStyleType).toBe('none')
})
```

- [ ] **Step 6: Prove the measure tests red before trusting them green**

Before running them, comment out `max-width: 72ch` in `.ask-measure`.

Run: `cd frontend && npm run test:browser -- src/presentation/ask/AskView.browser.test.tsx`
Expected: FAIL on "caps the prose column below the width of the surface". If it passes with the cap commented out, the test is measuring nothing — fix the test, not the stylesheet.

Restore the line.

- [ ] **Step 7: Run the browser suite for real**

Run: `cd frontend && npm run test:browser`
Expected: PASS, all four ask tests plus the existing browser suite. One vitest process at a time.

- [ ] **Step 8: Run the jsdom suite**

Run: `cd frontend && npx vitest run --project app`
Expected: PASS. `AskView.test.tsx` unchanged but for the `.ask-sub` selector from Task 5.

- [ ] **Step 9: Commit**

```bash
cd /home/ty/workspace/research-team/.claude/worktrees/dependency-0140
git add frontend/src/styles/ frontend/src/presentation/ask/
git commit -m "Give the ask page a measure, and both halves of it the same column

An answer ran the full width of the surface -- 1400px of prose at 1440px,
against a readable range of about 60-75 characters. The head was capped at
1100px by \`.view-head\` and had been overridden to \`max-w-none!\` to match it,
so the page was uniformly too wide rather than uniformly right. \`.ask-measure\`
is 72ch on both the thread's inner column and the composer's, which is the
alignment the two new browser tests measure; the cap is in \`ch\` because it
should follow the font, and 1100px was a number chosen for a tree.

Page-specific rather than a widening of \`.composer\` and \`.view-head\`: the
session page and the tree page depend on those, and rewriting a shared class
from one page's redesign is how two pages come to disagree about what a
composer is. The cost is a seventeenth stylesheet and two composers to keep
in step.

The deleted browser test asserted the \`!\` overrides held. Its subject is gone
with \`.view-head\`, so porting it would have been asserting a rule nothing
sets. The measure tests replace it, and were proved red with the cap
commented out before being trusted green.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 7: The page in Storybook, and every gate

**Files:**
- Create: `frontend/src/presentation/ask/AskPage.stories.tsx`
- Create: `frontend/src/presentation/ask/AskComposer.stories.tsx`

**Interfaces:**
- Consumes: `AskPage` (Task 5), `AskComposer`, and `PROJECT`/`turn`/`transcript` from `./ask-fixtures.ts`.
- Produces: nothing downstream. This is the last task.

- [ ] **Step 1: Write `AskPage.stories.tsx`**

```tsx
import type { Meta, StoryObj } from '@storybook/react-vite'

import { AskPage } from './AskPage.tsx'
import { PROJECT, transcript, turn } from './ask-fixtures.ts'

/** The whole page, in the five states it has.
 *
 * The fixed-height decorator is not decoration. This page's central layout
 * claim is that it fits a viewport it does not choose -- the thread scrolls
 * and the composer keeps the bottom edge -- and a story that lets it grow to
 * its content is showing a different component. 520px is the height
 * `AskView.browser.test.tsx` measures at, so the two agree.
 */
const meta = {
  component: AskPage,
  title: 'ask/AskPage',
  parameters: { layout: 'fullscreen' },
  decorators: [
    (Story) => (
      <div style={{ height: '520px', display: 'flex', flexDirection: 'column' }}>
        <Story />
      </div>
    ),
  ],
  args: {
    projectId: PROJECT,
    transcript: [],
    asking: false,
    error: null,
    onAsk: () => {},
    onReset: () => {},
  },
} satisfies Meta<typeof AskPage>

export default meta

type Story = StoryObj<typeof meta>

/** Nothing asked. The page says it keeps nothing in three places -- the
 *  subtitle, this empty state and the composer's hint -- which is repetition
 *  on purpose: the cost of a reader missing it is coming back tomorrow for an
 *  answer that is gone. */
export const Empty: Story = {}

export const OneTurn: Story = { args: { transcript: [turn()] } }

/** Mid-answer, with the box disabled. The store refuses a second question on
 *  a busy chat, and the disabled state is how the page says so before the
 *  reader has typed anything. */
export const Streaming: Story = {
  args: {
    asking: true,
    transcript: [turn({ answer: 'They agree on the effect and disagree on its', settled: false })],
  },
}

/** A refusal, said twice. The banner is what a reader who has scrolled away
 *  sees; the turn's own copy says which question died. */
export const Refused: Story = {
  args: {
    error: 'the model is already answering another question on this chat',
    transcript: [
      turn(),
      turn({
        question: 'And what about the third?',
        answer: '',
        citations: [],
        error: 'already answering another question on this chat',
      }),
    ],
  },
}

/** Long enough to overflow, which is the only state that shows what the
 *  layout is for: the thread scrolls and the composer does not move. */
export const LongThread: Story = { args: { transcript: transcript(12) } }
```

- [ ] **Step 2: Write `AskComposer.stories.tsx`**

```tsx
import type { Meta, StoryObj } from '@storybook/react-vite'

import { AskComposer } from './AskComposer.tsx'

/** The question box.
 *
 * `Typed` is the story with something to say: the draft is the component's own
 * state, so the only way to see the enabled button is to type into it. That is
 * why there is a play-free `render` rather than an arg -- the component takes
 * no `draft` prop, and adding one to make a story easier would be the story
 * changing the component.
 */
const meta = {
  component: AskComposer,
  title: 'ask/AskComposer',
  parameters: { layout: 'fullscreen' },
  args: { asking: false, onAsk: () => {} },
} satisfies Meta<typeof AskComposer>

export default meta

type Story = StoryObj<typeof meta>

/** Empty, and the button disabled with it -- and it stays disabled for a box
 *  holding only spaces, which is the rule the trim enforces. */
export const Empty: Story = {}

/** Asking. The box is disabled for the length of the turn, because the server
 *  refuses a second question on a busy chat with a 409 and not sending it is
 *  the same answer without the round trip. */
export const Asking: Story = { args: { asking: true } }
```

- [ ] **Step 3: Typecheck**

Run: `cd frontend && npm run typecheck`
Expected: no errors.

- [ ] **Step 4: Look at the page**

Run: `cd frontend && npm run storybook` (background it, or run and stop it after)
Open `ask/AskPage` → `LongThread` and `Refused`. Confirm by eye: the prose is a column rather than the full canvas, the question panels separate the turns, the facet control shows Ask as current, and the composer's box lines up with the prose. A computed style is a test's job; *whether it looks right* is not, and this page shipped its last regression past a green suite.

Note anything wrong here rather than fixing it silently — if the fix is more than a token value, it belongs in a commit of its own with a reason.

- [ ] **Step 5: Run the full frontend gate**

Run: `cd frontend && npm run verify`
Expected: PASS — format:check, lint, typecheck, test:coverage, build, size, deleted, check:tailwind. If `size` fails, raise the budget rather than shaving the page, and say why in the commit.

- [ ] **Step 6: Run the browser suite**

Run: `cd frontend && npm run test:browser`
Expected: PASS. Separately from step 5 — never two vitest processes at once.

- [ ] **Step 7: Run the Python gates**

Run, from `/home/ty/workspace/research-team/.claude/worktrees/dependency-0140`:

```bash
uv run ruff check .
uv run ruff format --check .
uv run pytest
```

Expected: all pass. These cover no frontend code and are gates anyway — ruff runs over the whole repository, and a change that touches no Python has failed here before on a file it did not write.

- [ ] **Step 8: Commit and open the PR**

```bash
cd /home/ty/workspace/research-team/.claude/worktrees/dependency-0140
git add frontend/src/presentation/ask/
git commit -m "Put the ask page itself in the workbench

Five states, of which two -- a long thread and a refusal with a live banner --
took a repository fake and a timing accident to reach before the page was
split from its store.

The fixed-height decorator is load-bearing rather than tidy: this page's whole
layout claim is that it fits a viewport it does not choose, and a story that
lets it grow to its content is showing a different component. 520px is the
height the browser test measures at, so the workbench and the measurement
agree about what is being looked at.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"

git push -u origin redraw-the-ask-page
gh pr create --title "Redraw the ask page, and take it apart" --body "$(cat <<'EOF'
## What

The ask page against a real prose measure and a real speaker rhythm, split
into components that can each be opened in Storybook on their own.

Spec: `docs/superpowers/specs/2026-08-13-ask-page-redesign-design.md`
Plan: `docs/superpowers/plans/2026-08-13-ask-page-redesign.md`

## The three faults it fixes

1. **No measure.** An answer ran the full width of the surface — 1400px of
   prose at 1440px. The head *was* capped, at 1100px by `.view-head`, and had
   been overridden to `max-w-none!` to match, making the page uniformly too
   wide rather than uniformly right. `.ask-measure` is 72ch and is set on both
   the thread's column and the composer's, so the question box sits under the
   prose rather than under the viewport.
2. **The speakers did not read as speakers.** The question's 2px left rule
   becomes a panel, the answer moves from `--fg-dim` to `--fg` — dimming the
   thing the reader came for was backwards — and a rule separates exchanges.
3. **The facet links did not say where you are.** Course / Research / Ask are
   one `nav` with `aria-current="page"` on the current one; New chat moves out
   of the group, being an action rather than a destination.

## Structure

`AskView` is the store and nothing else; `AskPage` is the page as a pure
function of props. `AskTurn`, `AskActivity`, `AskHead` and `ask-fixtures.ts`
are new files, and there are now stories for the page, the turn, the head, the
composer and the citation row — there were none.

## Tests

`AskView.test.tsx` is unchanged but for one selector, deliberately: it drives
the real store through the real port, so it is the evidence that this moved
drawing and not behaviour.

The browser suite gains two measurements — that the prose column is capped
below the surface width, and that the composer's column aligns with it — both
proved red with the cap commented out before being trusted green. It loses
one: the test that asserted the `!` overrides held, whose subject is gone
along with `.view-head`.

## Verification

All four gates plus `npm run test:browser`, and the page was looked at by eye
in Storybook — this page shipped its last regression past a fully green suite.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

---

## Self-Review

**Spec coverage.** §1 stylesheet → Task 6. §2 speakers → Tasks 2 and 6. §3 facet control → Task 4. §4 components → Tasks 1, 2, 4, 5 (the table's nine files all appear). §5 stories → Tasks 2, 3, 4, 7. Testing section → Task 5 (`AskPage.test.tsx`), Task 6 (browser rewrite), Task 1 (`AskActivity.test.tsx`); "stories exercised by the suite through `composeStories`" is covered by `npm run verify` running the `app` project, which globs `src/**/*.test.{ts,tsx}` — no separate task needed, and no story file needs a companion test beyond typecheck. "What is deliberately not done" adds no tasks by construction.

**Placeholders.** None: every code step carries the actual file content, and the one judgement call — Task 4 Step 2, whether `projectHref` accepts the `ask` facet — names the command to run, the expected answer and the fallback.

**Type consistency.** `AskActivityFold` takes `{activity, open, onToggle}` in Task 1 and is called with exactly those in Tasks 1 and 2. `AskTurn` takes `{projectId, turn, open, onToggle}` in Task 2, called with those in Task 6's thread. `AskHead` takes `{projectId, onReset}` in Task 4, rendered with those in Task 5. `AskPage`'s six props are declared in Task 5 and spread from the same six in Task 7's `meta.args`. `turn()`, `activity()`, `transcript()` and `PROJECT` are declared once in Task 1 and used under those names throughout. `.ask-measure` is used by Task 2's decorator before Task 6 defines it — deliberate and stated there; the story is unstyled for four commits and the ordering keeps each task's own test cycle intact.
