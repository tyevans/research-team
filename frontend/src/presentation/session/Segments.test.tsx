import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import { expect, it, vi } from 'vitest'

import type { Message } from '@domain/conversation/message.ts'
import type { TranscriptSegment } from '@domain/conversation/transcript.ts'

import { Segments } from './Segments.tsx'
import { hitList } from './shapes/fixtures.ts'

/** The conversation's folds, which had no test at all.
 *
 * `docs/component-system-spec.md` §10 names this file as a prerequisite of
 * phase 2, and it is the right call for a reason the spec states in one line
 * and is worth expanding: `Segments` is the *largest consumer of folds in the
 * console*, and the property phase 2 turns on is that a fold's open state is
 * owned by its caller rather than by the DOM. Nothing here asserted that, so
 * the migration would have been a rewrite of the most fold-dense component in
 * the repository with no net under it.
 *
 * The load-bearing property is S-F48: **a tool run stays open while its
 * conversation refetches.** `Conversation` re-renders on every turn end, so a
 * `<details>` inside it snaps shut mid-read; `Disclosure` takes `open` and
 * `onToggle` as props precisely so the state lives above the refetch. That is
 * one assertion below, and it is the one that would have caught a migration
 * back to `<details>`.
 *
 * **What this file deliberately does not assert:** appearance, markdown
 * rendering (`content.tsx`'s job), and how a transcript is cut into segments
 * (`transcript.test.ts`'s job). It asks only what `Segments` itself decides —
 * which folds exist, what they are labelled, and who owns whether they are
 * open.
 */

const message = (over: Partial<Message> = {}): Message => ({
  role: 'assistant',
  content: 'hello',
  toolCalls: [],
  name: null,
  artifact: null,
  isError: false,
  ...over,
})

/** A caller that owns the open set, which is the shape the real
 *  `Conversation` uses. A test driving `open` as a fixed prop could never
 *  observe a toggle at all. */
const Host = ({
  segments,
  initial = [],
}: {
  segments: readonly TranscriptSegment[]
  initial?: readonly string[]
}) => {
  const [open, setOpen] = useState<ReadonlySet<string>>(new Set(initial))
  const [, force] = useState(0)
  return (
    <>
      <button type="button" onClick={() => force((n) => n + 1)}>
        refetch
      </button>
      <Segments
        segments={segments}
        open={open}
        onToggle={(key) =>
          setOpen((current) => {
            const next = new Set(current)
            if (!next.delete(key)) next.add(key)
            return next
          })
        }
      />
    </>
  )
}

it('folds a tool run, collapsed to begin with', async () => {
  const user = userEvent.setup()
  const segments: readonly TranscriptSegment[] = [
    {
      kind: 'toolRun',
      at: 0,
      messages: [message({ role: 'tool', content: 'the result body' })],
    },
  ]

  render(<Host segments={segments} />)

  // Collapsed by default, and that is a decision rather than an accident: a
  // run is machinery and the prose around it is what the conversation is
  // saying. `Disclosure` renders `null` rather than `hidden` children, so the
  // body is absent from the tree, not merely invisible.
  const head = screen.getByRole('button', { expanded: false })
  expect(screen.queryByText('the result body')).not.toBeInTheDocument()

  await user.click(head)

  expect(screen.getByText('the result body')).toBeInTheDocument()
})

/** S-F48, and the reason `Disclosure` exists rather than `<details>`.
 *
 *  Proved red by giving `Disclosure` DOM-owned state — a `<details>` with no
 *  `open` prop — at which point the run shuts on the refetch and the body is
 *  gone. That is not a hypothetical: `Conversation` re-renders on every turn
 *  end, so this is the difference between reading a tool result and watching
 *  it close under you every few seconds. */
it('keeps a run open across a re-render driven from outside it', async () => {
  const user = userEvent.setup()
  const segments: readonly TranscriptSegment[] = [
    { kind: 'toolRun', at: 0, messages: [message({ role: 'tool', content: 'the result body' })] },
  ]

  render(<Host segments={segments} />)
  await user.click(screen.getByRole('button', { expanded: false }))
  expect(screen.getByText('the result body')).toBeInTheDocument()

  await user.click(screen.getByRole('button', { name: 'refetch' }))

  expect(screen.getByText('the result body')).toBeInTheDocument()
})

it('gives each fold a key of its own, so opening one does not open its neighbour', async () => {
  const user = userEvent.setup()
  const segments: readonly TranscriptSegment[] = [
    { kind: 'toolRun', at: 0, messages: [message({ role: 'tool', content: 'first result' })] },
    { kind: 'toolRun', at: 1, messages: [message({ role: 'tool', content: 'second result' })] },
  ]

  render(<Host segments={segments} />)
  const [first] = screen.getAllByRole('button', { expanded: false })

  await user.click(first!)

  // Keyed `run:${index}` off the segment's `at`, which `segmentTranscript`
  // documents as stable across the compaction split. A key derived from array
  // position instead would make every fold reopen somewhere else the moment a
  // compaction shifted the list.
  expect(screen.getByText('first result')).toBeInTheDocument()
  expect(screen.queryByText('second result')).not.toBeInTheDocument()
})

it('folds a message’s tool calls separately from its prose', async () => {
  const user = userEvent.setup()
  const segments: readonly TranscriptSegment[] = [
    {
      kind: 'message',
      at: 0,
      message: message({
        content: 'I will look that up.',
        toolCalls: [{ name: 'fetch', args: { url: 'https://example.test/a' } }],
      }),
    },
  ]

  render(<Host segments={segments} />)

  // The prose is visible without opening anything: a message that also said
  // something keeps its calls behind a fold so what it *said* is what you see
  // first.
  expect(screen.getByText('I will look that up.')).toBeInTheDocument()

  // Asserting on the argument preview rather than the tool's name, because the
  // name legitimately appears twice once the fold is open -- in the outer
  // label ("1 tool call · fetch") and again on the call itself. A `/fetch/`
  // query matches both and fails as ambiguous, which is the test telling us
  // something true about the markup rather than a fault to route around.
  await user.click(screen.getByRole('button', { expanded: false }))
  expect(screen.getByText(/example\.test/)).toBeInTheDocument()
})

it('does not put a fold over a call that took no arguments', () => {
  const segments: readonly TranscriptSegment[] = [
    {
      kind: 'message',
      at: 0,
      message: message({ content: '', toolCalls: [{ name: 'list_topics', args: {} }] }),
    },
  ]

  render(<Host segments={segments} />)

  // "A disclosure over an empty body is a control that punishes the reader for
  // trying it" -- the component's own comment, and the only assertion here
  // that is about something *not* being rendered. The call still appears; it
  // just is not a control.
  expect(screen.getByText('list_topics')).toBeInTheDocument()
  expect(screen.queryByRole('button', { expanded: false })).not.toBeInTheDocument()
})

it('marks an errored run so it is visible while still folded', () => {
  const segments: readonly TranscriptSegment[] = [
    {
      kind: 'toolRun',
      at: 0,
      messages: [message({ role: 'tool', content: 'boom', isError: true })],
    },
  ]

  render(<Host segments={segments} />)

  // On the *head*, not in the body: a reader scanning a folded conversation
  // has to be able to see that something failed without opening every run.
  expect(screen.getByRole('button', { expanded: false })).toHaveTextContent('error')
})

it('reports each toggle to its caller rather than handling it internally', async () => {
  const user = userEvent.setup()
  const onToggle = vi.fn()
  const segments: readonly TranscriptSegment[] = [
    { kind: 'toolRun', at: 3, messages: [message({ role: 'tool', content: 'x' })] },
  ]

  render(<Segments segments={segments} open={new Set()} onToggle={onToggle} />)
  await user.click(screen.getByRole('button', { expanded: false }))

  // The key, not just the fact of a click: `Conversation` persists this set,
  // so the string is a stored value and changing its shape silently discards
  // whatever a reader had open.
  expect(onToggle).toHaveBeenCalledWith('run:3')
})

it('drops the bubble frame around a result that draws its own spine', () => {
  // The doubled boundary the stream design exists to remove: a border and a
  // background around content that is already indented behind a rule in its
  // own gutter. The head goes with it -- `TOOL` above a header that reads
  // `search_sources · "magic" · 19 in 3 sources` is the same word twice.
  //
  // Asserted on the class rather than on a computed style deliberately. What
  // the class *does* is `.msg.bare` in `conversation.css`, and jsdom returns
  // only what an inline style said, so a computed-style assertion here would
  // read `''` against a stylesheet that never loaded and would pass either
  // way. This asserts the half jsdom can see -- that the decision reached the
  // markup -- and the stylesheet carries the half it cannot.
  const segments: readonly TranscriptSegment[] = [
    {
      kind: 'toolRun',
      at: 0,
      messages: [message({ role: 'tool', content: '19 match(es)', artifact: hitList })],
    },
  ]

  const { container } = render(<Host segments={segments} initial={['run:0']} />)

  expect(container.querySelector('.msg.bare')).not.toBeNull()
  expect(container.querySelector('.msg.bare .msg-head')).toBeNull()
  expect(container.querySelector('.msg.bare [data-testid="stream"]')).not.toBeNull()
})

it('keeps the frame and the head around a result with no artifact', () => {
  // The other half, and the one that would otherwise pass with `bare` applied
  // to every tool message: on a real database nothing has an artifact, so a
  // rule that stripped the frame unconditionally would leave the whole
  // transcript's machinery undressed and nothing above here would notice.
  const segments: readonly TranscriptSegment[] = [
    { kind: 'toolRun', at: 0, messages: [message({ role: 'tool', content: 'the result body' })] },
  ]

  const { container } = render(<Host segments={segments} initial={['run:0']} />)

  expect(container.querySelector('.msg.bare')).toBeNull()
  expect(container.querySelector('.msg-tool .msg-head')).not.toBeNull()
})
