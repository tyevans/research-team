import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, it, vi } from 'vitest'

import { useAttemptMachine, type AttemptsApi } from '@application/lesson/use-attempts.ts'
import type { Verdict } from '@domain/lesson/attempt.ts'
import type { ComponentBlock, LessonDocument } from '@domain/lesson/document.ts'
import { componentBlock } from '@presentation/ask/ask-fixtures.ts'

import { OverlayHost } from '../layout/OverlayHost.tsx'
import { Deck } from './Deck.tsx'

/** A quiz on a slide is a quiz, not a picture of one.
 *
 * **This is the assertion the whole deck turns on and the one most likely to
 * be missed.** A widget that renders and cannot be operated looks identical to
 * a working one in a snapshot, in a story, and to `Deck.test.tsx`'s role
 * queries -- the options are on screen either way. So this file does the only
 * thing that separates them: it navigates to the component slide, picks an
 * answer, submits, and requires the graded verdict to come back through the
 * same `submit` the document view calls.
 *
 * It also drives the *real* attempt machine rather than a stub, because a stub
 * is the shape CLAUDE.md's port-with-one-adapter entry warns about: the widget
 * would be verified against a fake and the attempt machine against nothing,
 * and the question "does a submission from a slide reach the server call" would
 * be asked by nothing.
 *
 * **Proved red** by rendering `slide.block.raw` in a `<pre>` instead of
 * `<Component>` -- the shape a "just show the source on the slide" deck would
 * have: every assertion below fails, and `Deck.test.tsx` stays entirely green.
 */

const QUIZ: ComponentBlock = componentBlock({
  type: 'mcq',
  id: 'q1',
  data: {
    prompt: 'Fold or projection?',
    options: [{ text: 'A fold is recomputed' }, { text: 'A fold is stored' }],
  },
  withheld: ['options[].correct'],
})

const DOC: LessonDocument = {
  blocks: [{ kind: 'markdown', text: '# Lesson\n\nProse.\n\n## Check for understanding' }, QUIZ],
}

const VERDICT: Verdict = {
  correct: true,
  score: 1,
  feedback: ['A fold is recomputed on every read.'],
  rationale: null,
  correctOptions: [0],
  blanks: [],
  progress: null,
}

/** The deck, mounted the way `CourseFile` mounts it: the real attempt machine
 *  over a stubbed submit, which is the one call that would reach the server. */
const Presented = ({ submit }: { submit: (block: ComponentBlock) => Promise<Verdict> }) => {
  const attempts: AttemptsApi = useLessonAttempts(submit)
  return (
    <OverlayHost>
      <Deck
        doc={DOC}
        attempts={attempts}
        label="lesson-01.md"
        withheldExplanation="graded on the server"
        slide={1}
        onSlide={vi.fn()}
        onClose={vi.fn()}
      />
    </OverlayHost>
  )
}

/** `useAttemptMachine`, which is what `useAttempts` is on the other side of a
 *  query and an HTTP call. The machine is the part a slide exercises -- picking,
 *  submitting, holding the verdict -- and standing up a container and a query
 *  client to reach it would be testing the container. `stored: null` is the ask
 *  surface's own answer for "nothing recorded". */
const useLessonAttempts = (submit: (block: ComponentBlock) => Promise<Verdict>): AttemptsApi =>
  useAttemptMachine('lesson-01.md', { stored: null, submit })

it('answers a multiple-choice question from a slide', async () => {
  const user = userEvent.setup()
  const submit = vi.fn().mockResolvedValue(VERDICT)
  render(<Presented submit={submit} />)

  await user.click(screen.getByText('A fold is recomputed'))
  await user.click(screen.getByRole('button', { name: /check answer/ }))

  await waitFor(() => {
    expect(submit).toHaveBeenCalledTimes(1)
  })
  // Not merely that something was submitted: the graded verdict has to reach
  // the slide. A deck that posted and then dropped the answer would satisfy
  // the call count and tell the learner nothing.
  expect(await screen.findByText(/recomputed on every read/)).toBeInTheDocument()
})

it('carries the answers-withheld note onto the slide', () => {
  // The one thing a component slide must not quietly lose: the reader is told
  // the key is on the server. It comes from `Component`, which is why the deck
  // renders through that and not a copy of it.
  render(<Presented submit={vi.fn().mockResolvedValue(VERDICT)} />)
  expect(screen.getByText('answers withheld')).toBeInTheDocument()
})
