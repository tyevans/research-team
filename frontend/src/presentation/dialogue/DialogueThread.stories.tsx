import type { Meta, StoryObj } from '@storybook/react-vite'

import { ContainerProvider } from '@app/container-context.tsx'

import { buildContainer } from '../../test/container.ts'

import { exchange, PROJECT } from './dialogue-fixtures.ts'
import { DialogueThread } from './DialogueThread.tsx'

/** A socratic dialogue, read the way a learner meets it.
 *
 * This surface runs the opposite way round from the ask: the system asks and
 * the reader answers. That inversion is the reason for most of what is odd
 * about the component, and the reason these stories are arranged around
 * *which question is outstanding* rather than around content.
 *
 * Three claims that live in the code as prose and had no picture:
 *
 * - **The outstanding question is the last thing the dialogue said**, not a
 *   special kind of turn. `.dlg-pending` survives only as a modifier marking
 *   it. `Outstanding` and `Concluded` are the pair — a concluded dialogue has
 *   nothing outstanding, so the glow must go even though the last turn is
 *   still the last turn.
 * - **The opening question is on the row, not on any turn**, which is also why
 *   it is the one question nothing can be graded against.
 * - **Progress is keyed by the turn's `position`, never by its array index.**
 *   They agree on a transcript loaded whole and diverge the moment one does
 *   not start at turn 0 — and `DialogueThread.tsx` records that the failure is
 *   silent, drawing one exchange's verdicts against another's questions.
 *   `PartialTranscript` is that case, and it is the story to keep.
 *
 * **The container is a stub and must be present.** `DialogueExchange` calls
 * `useContainer` unconditionally, and `DialoguePage.test.tsx` argues why the
 * guard was not added: a guard for a fixture's benefit would hide a missing
 * provider until the first question that happened to carry a widget, which is
 * production. Nothing here submits, so the stub only has to exist.
 */
const meta: Meta = {
  title: 'dialogue/DialogueThread',
}

export default meta

type Story = StoryObj

/** Nothing in these stories submits an attempt, so the container only has to be
 *  present -- building a real one would be building the application to draw a
 *  thread. `buildContainer` is what makes "only the parts I need" a checked
 *  claim rather than `as unknown as Container`, which deleted the check
 *  (B90). */
const container = buildContainer({
  // Never settles, rather than resolving `null`. `null` is not a `Verdict` and
  // the old cast was accepting it -- the first thing `buildContainer` caught
  // when it went in. A story that does not submit does not need an answer, and
  // inventing a plausible verdict here would put a second, undocumented one
  // beside the fixtures.
  dialogues: { submitDialogueAttempt: () => new Promise<never>(() => {}) },
})

const Frame = ({ heading, children }: { heading: string; children: React.ReactNode }) => (
  <ContainerProvider container={container}>
    <section style={{ padding: 'var(--space-3)', maxWidth: 760 }}>
      <h3 style={{ font: 'inherit', color: 'var(--fg-faint)', margin: '0 0 var(--space-2)' }}>
        {heading}
      </h3>
      {children}
    </section>
  </ContainerProvider>
)

const OPENING = [
  {
    kind: 'markdown' as const,
    text: 'You said the Council of Nicaea settled the Arian controversy. Did it?',
  },
]

const TRANSCRIPT = [
  exchange({
    position: 0,
    blocks: [{ kind: 'markdown', text: 'What makes you say it settled anything?' }],
    reply: 'It produced a creed that the bishops signed.',
  }),
  exchange({
    position: 1,
    blocks: [
      {
        kind: 'markdown',
        text: 'A signed creed and a settled controversy are different claims. Which did Nicaea produce?',
      },
    ],
    reply: 'The creed, I suppose. Arianism carried on afterwards.',
  }),
  exchange({
    position: 2,
    blocks: [{ kind: 'markdown', text: 'So what would "settled" have required?' }],
    reply: '',
    settled: false,
  }),
]

/** A dialogue mid-flight. The last question is outstanding and glows; the two
 *  above it are answered and do not. */
export const Outstanding: Story = {
  render: () => (
    <Frame heading="waiting on the reader">
      <DialogueThread
        projectId={PROJECT}
        transcript={TRANSCRIPT}
        openingBlocks={OPENING}
        dialogueId="d-1"
        progress={{}}
        concluded={false}
      />
    </Frame>
  ),
}

/** **The pair that makes the rule checkable.** The same transcript, concluded.
 *
 *  Nothing is outstanding once a dialogue reaches its goal, so the glow must
 *  go even though the last turn is still the last turn. A build that keyed the
 *  marker off position alone would look identical to `Outstanding` here, and
 *  would tell a reader they are being waited on when the conversation is
 *  over. */
export const Concluded: Story = {
  render: () => (
    <Frame heading="finished — nothing is outstanding">
      <DialogueThread
        projectId={PROJECT}
        transcript={TRANSCRIPT.map((turn, index) =>
          index === TRANSCRIPT.length - 1
            ? { ...turn, settled: true, concluded: true, reply: 'That it stopped being argued.' }
            : turn,
        )}
        openingBlocks={OPENING}
        dialogueId="d-1"
        progress={{}}
        concluded
      />
    </Frame>
  ),
}

/** The first question, before anything has been answered.
 *
 *  The opening lives on the row rather than on a turn, so this is a thread
 *  with an empty transcript that is nonetheless not empty on screen. A build
 *  that rendered the opening from `transcript[0]` would draw nothing here. */
export const JustOpened: Story = {
  render: () => (
    <Frame heading="opened, nothing answered">
      <DialogueThread
        projectId={PROJECT}
        transcript={[]}
        openingBlocks={OPENING}
        dialogueId="d-1"
        progress={{}}
        concluded={false}
      />
    </Frame>
  ),
}

/** The dialogue is composing its next question. */
export const Composing: Story = {
  render: () => (
    <Frame heading="thinking">
      <DialogueThread
        projectId={PROJECT}
        transcript={[
          TRANSCRIPT[0]!,
          exchange({ position: 1, blocks: [], reply: '', settled: false, composing: true }),
        ]}
        openingBlocks={OPENING}
        dialogueId="d-1"
        progress={{}}
        concluded={false}
      />
    </Frame>
  ),
}

/** **The `position`-not-index case.** A transcript that does not start at
 *  turn 0.
 *
 *  `DialogueThread.tsx` states the hazard: progress is keyed `turn/{position}`
 *  and indexing by the array position instead "would be silent, drawing one
 *  exchange's verdicts against another's questions". Here the two turns are at
 *  positions 4 and 5, so any build that reached for index 0 and 1 would read
 *  the wrong keys — and would look entirely normal doing it.
 *
 *  This story is the one to keep if any are dropped. The others show states;
 *  this one shows a defect that has no appearance of its own. */
export const PartialTranscript: Story = {
  render: () => (
    <Frame heading="a transcript that does not start at turn 0">
      <DialogueThread
        projectId={PROJECT}
        transcript={[
          exchange({
            position: 4,
            blocks: [{ kind: 'markdown', text: 'Where does that leave Constantine’s role?' }],
            reply: 'He convened it, and he wanted agreement more than a doctrine.',
          }),
          exchange({
            position: 5,
            blocks: [{ kind: 'markdown', text: 'Does that change what the creed was for?' }],
            reply: '',
            settled: false,
          }),
        ]}
        openingBlocks={OPENING}
        dialogueId="d-1"
        progress={{}}
        concluded={false}
      />
    </Frame>
  ),
}

/** A turn that failed. An error is not an answer and must not read as one. */
export const Failed: Story = {
  render: () => (
    <Frame heading="a turn that failed">
      <DialogueThread
        projectId={PROJECT}
        transcript={[
          TRANSCRIPT[0]!,
          exchange({
            position: 1,
            blocks: [],
            reply: '',
            settled: true,
            error: 'the model did not answer',
          }),
        ]}
        openingBlocks={OPENING}
        dialogueId="d-1"
        progress={{}}
        concluded={false}
      />
    </Frame>
  ),
}
