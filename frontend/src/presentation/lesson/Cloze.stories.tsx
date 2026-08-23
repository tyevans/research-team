import { useState } from 'react'
import type { Meta, StoryObj } from '@storybook/react-vite'

import type { AttemptsApi } from '@application/lesson/use-attempts.ts'
import type { AttemptState, Verdict } from '@domain/lesson/attempt.ts'
import { freshAttempt, mcqResponse } from '@domain/lesson/attempt.ts'
import type { ComponentBlock } from '@domain/lesson/document.ts'
import { ComponentId } from '@domain/shared/identifier.ts'

import { Cloze } from './Cloze.tsx'

/** A passage with gaps, and the one mode that makes the widget mean anything.
 *
 * **`oneAtATime` is the whole design.** `widgets.ts` puts it plainly: it "is
 * what makes the mode mean anything: the learner reads forward instead of
 * scanning the passage for the easy gaps first." `OneAtATime` and
 * `AllAtOnce` are the same passage under both, and they are the pair to look
 * at — under `all-at-once` a learner fills the gaps they already know and
 * infers the rest from what is left, which is a different exercise from the
 * one the author wrote.
 *
 * **This page also completes something left half-done.** The commit that
 * merged `CmpButton` into `Button` changed `Mcq` and `Cloze` together, and the
 * follow-up that moved the accent onto the live action changed both too — but
 * only `Mcq` got a story. `Graded` is `Cloze`'s half of that picture: after
 * submission the accent is on `try again`, never on the disabled submit.
 *
 * The `AttemptsApi` stub holds real state, for `Mcq.stories.tsx`'s stated
 * reason: a stub whose `update` is a no-op renders a passage nothing can be
 * typed into, and every story would look the same while looking fine.
 */
const meta: Meta = {
  title: 'lesson/Cloze',
}

export default meta

type Story = StoryObj

const block = (mode: 'one-at-a-time' | 'all-at-once'): ComponentBlock => ({
  kind: 'component',
  id: ComponentId('cloze-1'),
  type: 'cloze',
  data: {
    mode,
    segments: [
      { text: 'Diocletian divided rule between two ' },
      { blank: 0, hint: 'senior title' },
      { text: ' and two ' },
      { blank: 1, hint: 'junior title' },
      { text: ', an arrangement later called the ' },
      { blank: 2, hint: null },
      { text: '.' },
    ],
  },
  raw: '',
  lang: 'cloze',
  unknown: false,
  errors: [],
  withheld: ['answers'],
  resolved: false,
})

const verdict = (over: Partial<Verdict> = {}): Verdict => ({
  correct: false,
  score: 2 / 3,
  feedback: ['Two of three. The third is the name the arrangement is known by.'],
  rationale: null,
  correctOptions: [],
  blanks: [
    { blank: 0, correct: true, answer: 'Augusti' },
    { blank: 1, correct: true, answer: 'Caesars' },
    { blank: 2, correct: false, answer: 'tetrarchy' },
  ],
  progress: null,
  ...over,
})

const useStub = (initial: Partial<AttemptState>): AttemptsApi => {
  const [state, setState] = useState<AttemptState>({ ...freshAttempt(), ...initial })
  return {
    stateFor: () => state,
    update: (_block, change) => {
      setState((current) => ({ ...current, ...change }))
    },
    submit: async () => {
      setState((current) => ({ ...current, busy: true }))
      await new Promise((resolve) => setTimeout(resolve, 600))
      setState((current) => ({ ...current, busy: false, verdict: verdict() }))
    },
    reset: () => {
      setState(freshAttempt())
    },
    mcqResponse,
  }
}

const Frame = ({ heading, children }: { heading: string; children: React.ReactNode }) => (
  <section style={{ padding: 'var(--space-3)', maxWidth: 660 }}>
    <h3 style={{ font: 'inherit', color: 'var(--fg-faint)', margin: '0 0 var(--space-2)' }}>
      {heading}
    </h3>
    {children}
  </section>
)

/** **The mode the widget is for.** Only the first unfilled gap is live; the
 *  rest wait.
 *
 *  Live: type into the open gap and the next one opens. That forward march is
 *  the exercise — a learner cannot survey the passage and start with whichever
 *  gap they happen to know. */
export const OneAtATime: Story = {
  render: function Render() {
    const attempts = useStub({})
    return (
      <Frame heading="one at a time — the learner reads forward">
        <Cloze block={block('one-at-a-time')} attempts={attempts} />
      </Frame>
    )
  },
}

/** **The same passage, every gap open.**
 *
 *  Read against `OneAtATime`. This is a different exercise: fill the two you
 *  know, then infer the third from what is left. Both are legitimate — the
 *  author chooses — and the point of the pair is that the choice is visible at
 *  all, since the two render identically apart from which inputs accept
 *  typing. */
export const AllAtOnce: Story = {
  render: function Render() {
    const attempts = useStub({})
    return (
      <Frame heading="all at once — the learner may start anywhere">
        <Cloze block={block('all-at-once')} attempts={attempts} />
      </Frame>
    )
  },
}

/** Part-way through, with the earlier gaps filled. */
export const PartlyFilled: Story = {
  render: function Render() {
    const attempts = useStub({ typed: { 0: 'Augusti' } })
    return (
      <Frame heading="one gap answered">
        <Cloze block={block('one-at-a-time')} attempts={attempts} />
      </Frame>
    )
  },
}

/** **Graded — and this is `Cloze`'s half of the button picture.**
 *
 *  Two right, one wrong, each gap marked in place rather than in a summary: a
 *  cloze's whole advantage is that the answer sits where the question was.
 *
 *  The rule to check is the one `Mcq.stories.tsx` records: **the accent is on
 *  `try again`, never on the disabled submit.** After grading, submit does
 *  nothing and the retry is the only live control; an accent-filled disabled
 *  button would be the loudest thing on the row. */
export const Graded: Story = {
  render: function Render() {
    const attempts = useStub({
      typed: { 0: 'Augusti', 1: 'Caesars', 2: 'diarchy' },
      verdict: verdict(),
    })
    return (
      <Frame heading="graded — two right, one wrong">
        <Cloze block={block('one-at-a-time')} attempts={attempts} />
      </Frame>
    )
  },
}

/** Everything right. */
export const AllCorrect: Story = {
  render: function Render() {
    const attempts = useStub({
      typed: { 0: 'Augusti', 1: 'Caesars', 2: 'tetrarchy' },
      verdict: verdict({
        correct: true,
        score: 1,
        feedback: ['All three.'],
        blanks: [
          { blank: 0, correct: true, answer: 'Augusti' },
          { blank: 1, correct: true, answer: 'Caesars' },
          { blank: 2, correct: true, answer: 'tetrarchy' },
        ],
      }),
    })
    return (
      <Frame heading="graded — all correct">
        <Cloze block={block('one-at-a-time')} attempts={attempts} />
      </Frame>
    )
  },
}

/** The grader failed.
 *
 *  An error is not a wrong answer. A learner told their gaps were wrong when
 *  the grader was down has been told something false about themselves, so this
 *  goes through the alert path and leaves the gaps unmarked. */
export const GraderFailed: Story = {
  render: function Render() {
    const attempts = useStub({
      typed: { 0: 'Augusti', 1: 'Caesars', 2: 'tetrarchy' },
      error: 'the grader did not answer',
    })
    return (
      <Frame heading="the grader failed — nothing is marked">
        <Cloze block={block('one-at-a-time')} attempts={attempts} />
      </Frame>
    )
  },
}
