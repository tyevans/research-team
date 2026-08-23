import { useState } from 'react'
import type { Meta, StoryObj } from '@storybook/react-vite'

import type { AttemptsApi } from '@application/lesson/use-attempts.ts'
import type { AttemptState, Verdict } from '@domain/lesson/attempt.ts'
import { freshAttempt, mcqResponse } from '@domain/lesson/attempt.ts'
import type { ComponentBlock } from '@domain/lesson/document.ts'
import { ComponentId } from '@domain/shared/identifier.ts'

import { Mcq } from './Mcq.tsx'

/** A graded question, in the five states a learner actually meets.
 *
 * `presentation/lesson` had fourteen components and no stories, which made it
 * the largest uncovered area in the console and — more to the point — the one
 * whose components a reader *works through* rather than reads. A verdict panel
 * that is wrong is wrong at the moment somebody is being told whether they
 * were right.
 *
 * **This page also closes a loop.** The commit that merged `CmpButton` into
 * `Button` changed what a lesson's submit button looks like: it is the
 * console's accent **fill** now, where `.cmp-btn.primary` drew an accent
 * outline. That was a deliberate change with a stated cost and no picture
 * attached to it. `Unanswered` and `Answered` are the picture.
 *
 * The `AttemptsApi` stub is local and holds real state, which matters: a stub
 * whose `update` is a no-op renders a question no option can be chosen in, and
 * every story would show the same untouched widget while looking fine.
 */
const meta: Meta = {
  title: 'lesson/Mcq',
}

export default meta

type Story = StoryObj

const block = (data: Record<string, unknown>): ComponentBlock => ({
  kind: 'component',
  id: ComponentId('mcq-1'),
  type: 'mcq',
  data,
  raw: '',
  lang: 'mcq',
  unknown: false,
  errors: [],
  withheld: ['answer'],
  resolved: false,
})

const QUESTION = block({
  prompt: 'Which reform is Diocletian best known for?',
  options: [
    { text: 'Dividing the empire into a tetrarchy' },
    { text: 'Moving the capital to Byzantium' },
    { text: 'Abolishing the Senate' },
    { text: 'Adopting Christianity as the state religion' },
  ],
})

const verdict = (over: Partial<Verdict> = {}): Verdict => ({
  correct: true,
  score: 1,
  feedback: ['The tetrarchy split rule between two Augusti and two Caesars.'],
  rationale: null,
  correctOptions: [0],
  blanks: [],
  progress: null,
  ...over,
})

/** A stub that keeps state, so the widget is actually operable in the gallery.
 *
 *  `submit` resolves to whatever the story wants the server to have said, and
 *  is deliberately not instant: `busy` is a state the learner sees and it
 *  cannot be looked at if it never lasts a frame. */
const useStubAttempts = (initial: Partial<AttemptState>, answer?: Verdict): AttemptsApi => {
  const [state, setState] = useState<AttemptState>({ ...freshAttempt(), ...initial })
  return {
    stateFor: () => state,
    update: (_block, change) => {
      setState((current) => ({ ...current, ...change }))
    },
    submit: async () => {
      setState((current) => ({ ...current, busy: true }))
      await new Promise((resolve) => setTimeout(resolve, 600))
      setState((current) => ({ ...current, busy: false, verdict: answer ?? verdict() }))
    },
    reset: () => {
      setState(freshAttempt())
    },
    mcqResponse,
  }
}

const Frame = ({ children }: { children: React.ReactNode }) => (
  <div style={{ padding: 'var(--space-3)', maxWidth: 640 }}>{children}</div>
)

/** Nothing chosen. Submit is present and the verdict slot is empty.
 *
 *  Live: pick an option and press submit. The 600ms in the stub is there so
 *  `busy` can be seen; in the application it is a round trip. */
export const Unanswered: Story = {
  render: function Render() {
    const attempts = useStubAttempts({})
    return (
      <Frame>
        <Mcq block={QUESTION} attempts={attempts} />
      </Frame>
    )
  },
}

/** An option chosen, nothing submitted.
 *
 *  **Nothing is marked right or wrong here, and that is the rule to check.**
 *  `Verdict.correctOptions` is documented as "present only after a
 *  submission, which is why marking never appears before one" — the answer key
 *  is withheld from the learner projection and graded on the server. A build
 *  that marked the chosen option before submission would be leaking the key. */
export const Answered: Story = {
  render: function Render() {
    const attempts = useStubAttempts({ picked: [1] })
    return (
      <Frame>
        <Mcq block={QUESTION} attempts={attempts} />
      </Frame>
    )
  },
}

/** Right, with the server's feedback. */
export const Correct: Story = {
  render: function Render() {
    const attempts = useStubAttempts({ picked: [0], verdict: verdict() })
    return (
      <Frame>
        <Mcq block={QUESTION} attempts={attempts} />
      </Frame>
    )
  },
}

/** Wrong, with the correct option marked and a way back.
 *
 *  **The accent is on `try again` here, and that is the rule.** Once a verdict
 *  is in, submit is disabled and the retry is the only thing a learner can do,
 *  so the accent follows the live action rather than staying on whichever
 *  button is conceptually primary. Exactly one filled button per decision, and
 *  it is never a disabled one.
 *
 *  This story is the reason the rule exists. An earlier draft of the button
 *  merge left `primary` on submit unconditionally, and screenshotting this
 *  page showed a 45%-opacity amber block outweighing the live control beside
 *  it. `.cmp-btn.primary` had drawn an accent *outline*, so a disabled one was
 *  already quiet; `.btn-accent` fills, and the merge carried that difference
 *  in without anyone looking. */
export const Incorrect: Story = {
  render: function Render() {
    const attempts = useStubAttempts({
      picked: [2],
      verdict: verdict({
        correct: false,
        score: 0,
        feedback: ['The Senate survived Diocletian; it was the tetrarchy that was new.'],
      }),
    })
    return (
      <Frame>
        <Mcq block={QUESTION} attempts={attempts} />
      </Frame>
    )
  },
}

/** The server refused.
 *
 *  An error is not a wrong answer and must not read as one: a learner told
 *  "incorrect" when the grader was down has been told something false about
 *  themselves. `VerdictPanel` renders this through `role="alert"` and its own
 *  `.cmp-error`, not through the verdict path. */
export const GraderFailed: Story = {
  render: function Render() {
    const attempts = useStubAttempts({ picked: [0], error: 'the grader did not answer' })
    return (
      <Frame>
        <Mcq block={QUESTION} attempts={attempts} />
      </Frame>
    )
  },
}

/** More than one answer wanted. The controls are checkboxes in behaviour —
 *  picking a second keeps the first — and the prompt is the only thing that
 *  says so. */
export const MultipleChoice: Story = {
  render: function Render() {
    const attempts = useStubAttempts({ picked: [0] })
    return (
      <Frame>
        <Mcq
          block={block({
            prompt: 'Which of these were Diocletian’s reforms? (choose all that apply)',
            multiple: true,
            options: [
              { text: 'The tetrarchy' },
              { text: 'Price edicts' },
              { text: 'Moving the capital to Byzantium' },
            ],
          })}
          attempts={attempts}
        />
      </Frame>
    )
  },
}
