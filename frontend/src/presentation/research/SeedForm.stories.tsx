import type { Meta, StoryObj } from '@storybook/react-vite'

import type { SeedingRun } from '@domain/research/seeding.ts'

import { SeedForm } from './SeedForm.tsx'

/** Seeding, in the four states a run passes through.
 *
 * The one that matters is `FailedLastRun`. A failed seed and a hung seed
 * looked identical until the panel learned to keep the last run on screen, and
 * "looked identical" was discovered by watching a real run rather than by
 * reading the code — so it is worth being able to look at deliberately.
 */
const meta = {
  title: 'research/SeedForm',
  component: SeedForm,
  parameters: { layout: 'fullscreen' },
  decorators: [
    (Story) => (
      <div
        style={{
          width: '340px',
          border: '1px solid var(--line)',
          borderRadius: 'var(--radius)',
          background: 'var(--bg-panel)',
          padding: '10px 12px 12px',
        }}
      >
        <Story />
      </div>
    ),
  ],
} satisfies Meta<typeof SeedForm>

export default meta

type Story = StoryObj<typeof meta>

const run = (over: Partial<SeedingRun> = {}): SeedingRun => ({
  runId: 'r1',
  status: 'running',
  subject: 'spaced repetition and memory consolidation',
  reply: null,
  detail: null,
  ...over,
})

const base = {
  subject: '',
  current: null,
  last: null,
  askedSubject: null,
  active: false,
  onSubjectChange: () => {},
  onSubmit: () => {},
}

/** Nothing has run. The button is disabled because the box is empty — and
 *  stays disabled for a box holding only spaces, which is the rule the trim
 *  enforces. */
export const Fresh: Story = { args: base }

/** A subject typed, ready to go. */
export const Ready: Story = {
  args: { ...base, subject: 'spaced repetition and memory consolidation' },
}

/** A run this tab started. The subject comes from `askedSubject` because the
 *  running frame the server mints carries none — it exists before the model
 *  call that would name one. */
export const Running: Story = {
  args: {
    ...base,
    active: true,
    current: run({ subject: null }),
    askedSubject: 'spaced repetition and memory consolidation',
  },
}

/** The same run, seen by a tab that did not start it. Neither the frame nor
 *  this tab knows the subject, so the panel says what it knows rather than
 *  inventing a name — which is the honest state of the data, not a gap. */
export const RunningFromAnotherTab: Story = {
  args: { ...base, active: true, current: run({ subject: null }) },
}

/** A run that failed, with the model's reason. Kept on screen after the run
 *  ends: a panel that cleared itself is how a failed seed came to look exactly
 *  like a hung one. */
export const FailedLastRun: Story = {
  args: {
    ...base,
    last: run({ status: 'failed', detail: 'the model returned no topics for that subject' }),
  },
}

/** A run that finished. */
export const DoneLastRun: Story = {
  args: { ...base, last: run({ status: 'done' }) },
}
