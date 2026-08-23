import { composeStories } from '@storybook/react-vite'
import { render, screen } from '@testing-library/react'
import { expect, it } from 'vitest'

import * as stories from './Segments.stories.tsx'

/** The fold hides detail, not evidence -- and it counts what it contains.
 *
 * `segmentTranscript` runs consecutive tool activity together into one
 * `toolRun`. The fold is what stops a turn that made six calls from burying
 * the sentence either side of it, and everything below is about the fold
 * telling the truth while shut.
 *
 * **The error case is the one that matters.** `segmentHasError` looks *inside*
 * a run, so a failure surfaces on the closed label -- because a failure hidden
 * behind a fold a reader had no reason to open is a failure they will not
 * find. Asserted while the run is shut, which is the only state where it can
 * be wrong: opened, the errored message speaks for itself.
 *
 * **Proved red** two ways. Dropping the `segmentHasError` chip fails the error
 * test alone -- the messages still render, so this is a defect about what a
 * *closed* fold admits rather than about content going missing. And replacing
 * `tally.total || messages.length` with `tally.total` fails the
 * results-without-calls test alone, rendering "0 tool calls" over a fold that
 * contains two.
 *
 * Not asserted: the tool dressing's colours. `.msg-tool` and `.msg-tool.errored`
 * carry their own background and border, and jsdom resolves neither -- the axe
 * sweep is what covers them, and it is clean over these stories, which is the
 * first time either had been rendered by anything.
 */
const { AFoldedRun, AnOpenRun, AFailedRun, ALongRun, OneCall, ResultsWithoutCalls } =
  composeStories(stories)

it('folds consecutive tool activity into a single run', () => {
  const { container } = render(<AFoldedRun />)
  // One fold for four messages: the ask, the run, the answer.
  expect(container.querySelectorAll('.run')).toHaveLength(1)
  expect(screen.getByText(/tetrarchy create/)).toBeInTheDocument()
  expect(screen.getByText(/provincial subdivision/)).toBeInTheDocument()
})

/** Six calls, still one fold -- the whole point of running them together. */
it('keeps a long run to one fold', () => {
  const { container } = render(<ALongRun />)
  expect(container.querySelectorAll('.run')).toHaveLength(1)
  expect(screen.getByText(/6 tool calls/)).toBeInTheDocument()
})

/** The rule. Asserted with the run shut, which is the only state it can be
 *  wrong in. */
it('surfaces an error on a run that is still folded', () => {
  const { container } = render(<AFailedRun />)

  const run = container.querySelector('.run')
  expect(run).not.toBeNull()
  // Shut: the errored message's own text is not on the page yet.
  expect(screen.queryByText(/503 from the source/)).not.toBeInTheDocument()
  // But the label says so.
  expect(screen.getByText('error')).toBeInTheDocument()
})

/** Opened, the failure's own text is there -- the fold hid detail, not
 *  evidence. */
it('shows the failing result once the run is opened', () => {
  render(<AnOpenRun />)
  expect(screen.getByText(/8 passages, 3 above threshold/)).toBeInTheDocument()
})

/** "1 tool calls" is the kind of thing that ships and stays. */
it('gets the singular right', () => {
  render(<OneCall />)
  expect(screen.getByText(/\b1 tool call\b/)).toBeInTheDocument()
})

/** A replay starting mid-turn has results and no calls. Counting the calls
 *  would print "0 tool calls" over a fold containing two messages. */
it('counts messages when a run has results but no calls', () => {
  render(<ResultsWithoutCalls />)
  expect(screen.getByText(/2 tool calls/)).toBeInTheDocument()
  expect(screen.queryByText(/0 tool calls/)).not.toBeInTheDocument()
})
