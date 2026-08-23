import { composeStories } from '@storybook/react-vite'
import { render, screen } from '@testing-library/react'
import { expect, it } from 'vitest'

import * as stories from './Compaction.stories.tsx'

/** The pane says the messages are kept, and can show them.
 *
 * `Compaction.tsx`: "Nothing was deleted -- the log still holds every message,
 * and so does this pane. What changed is what the *model* is shown."
 *
 * The whole feature is wording, so the assertions are wording -- and the pair
 * that matters is **the claim and the proof**. A pane that says the messages
 * are still in the log and then has nothing to show would be worse than one
 * that admitted they were gone, so asserting the sentence alone is not enough.
 * `Superseded` opens the fold and the second test counts what is inside it.
 *
 * The plural is asserted at 1, because "the first 1 messages" is the kind of
 * thing that ships and stays.
 *
 * **Proved red** two ways. Changing the fold's label from "still in the log,
 * not sent to the model" to "removed from the context" fails the first test
 * alone -- the messages are still rendered, which is the point: the defect
 * would be a *lie*, not a missing feature. And passing `hidden={[]}` while
 * leaving `through` alone fails the second alone, which is the same lie
 * arriving from the other direction.
 *
 * Not asserted: that the summary fold is open by default. It is, and its key
 * is inverted (`compaction:summary:closed`) so an empty set means open -- but
 * `Disclosure` renders its body only when open, so "the summary text is
 * present" already covers it, and a separate assertion on the attribute would
 * be testing `Disclosure` rather than this pane.
 */
const { AsItArrives, Superseded, NoSummaryText, OneMessage } = composeStories(stories)

it('says the superseded messages are kept rather than removed', () => {
  render(<AsItArrives />)
  expect(screen.getByText(/still in the log, not sent to the model/)).toBeInTheDocument()
  expect(screen.getByText(/everything below is sent verbatim/)).toBeInTheDocument()
  expect(document.body.textContent ?? '').not.toMatch(/removed|deleted|discarded/i)
})

/** The proof, without which the sentence above is only a claim. */
it('can actually show the messages it says are kept', () => {
  render(<Superseded />)
  expect(screen.getByText(/Start from the tetrarchy/)).toBeInTheDocument()
  expect(screen.getByText(/three of the eight documents/i)).toBeInTheDocument()
})

/** The summary the model was given is shown, open, by default. */
it('shows the summary the model is seeing', () => {
  render(<AsItArrives />)
  expect(screen.getByText(/rule was divided in 293/)).toBeInTheDocument()
})

/** "No summary text was returned" is a fact about the record. An empty fold
 *  would read as a summary that failed to render, and a reader could not tell
 *  the two apart. */
it('says when no summary text came back, rather than showing an empty fold', () => {
  render(<NoSummaryText />)
  expect(screen.getByText(/no summary text was returned/i)).toBeInTheDocument()
  expect(screen.queryByText(/summary shown to the model/)).not.toBeInTheDocument()
})

/** "the first 1 messages" is the kind of thing that ships and stays. */
it('gets the singular right', () => {
  render(<OneMessage />)
  expect(screen.getByText(/the model sees a summary of the first 1 message\b/)).toBeInTheDocument()
  expect(screen.getByText(/1 superseded message\b/)).toBeInTheDocument()
})
