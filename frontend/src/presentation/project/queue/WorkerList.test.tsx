import { composeStories } from '@storybook/react-vite'
import { render, screen } from '@testing-library/react'
import { expect, it } from 'vitest'

import * as stories from './WorkerList.stories.tsx'

const { Busy, Idle, AfterAFailedPoll } = composeStories(stories)

/** The rule the panel exists for, asserted against the states directly.
 *
 * `Workers.test.tsx` covers the same ground through the poll -- a repository
 * that answers once and then throws, plus an invalidation to make it try
 * again. That test is still worth having, because wiring the failure to the
 * stale marker is the container's job. What it could not do is put the two
 * empty readings side by side, because reaching both in one file meant two
 * different fake repositories.
 */

it('never says nothing is running when it only knows what it last saw', () => {
  render(<AfterAFailedPoll />)

  // Present tense exactly once: the story renders three panels, and only the
  // one with a live roster behind it is entitled to make a claim about now.
  expect(
    screen.getAllByText(/As of the last roster that arrived, nothing was running/),
  ).toHaveLength(1)
  expect(screen.queryByText(/^Nothing is running on this project\./)).not.toBeInTheDocument()
})

it('keeps the last roster on screen when the poll fails', () => {
  render(<AfterAFailedPoll />)

  expect(screen.getByText('answering “does spacing help?”')).toBeInTheDocument()
  expect(screen.getAllByText('stale')).toHaveLength(2)
})

it('gives a worker with no session of its own text rather than a dead button', () => {
  render(<Busy />)

  // Extraction's detail view is the extraction pane, not a transcript, so
  // there is nothing for a button here to open.
  expect(screen.getByText('reading syllabus.pdf').tagName).toBe('SPAN')
  expect(screen.getByRole('button', { name: 'round 3 of 10' })).toBeInTheDocument()
})

it('says idle when it knows the project is idle', () => {
  render(<Idle />)

  expect(screen.getByText('idle')).toBeInTheDocument()
  expect(screen.getByText(/1 session\(s\) attached and quiet/)).toBeInTheDocument()
})
