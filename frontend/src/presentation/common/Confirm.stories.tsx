import type { Meta, StoryObj } from '@storybook/react-vite'

import { Confirm } from './Confirm.tsx'

/** The first story in the project, and it exists to prove the workbench runs
 *  against a real component rather than to document `Confirm` exhaustively.
 *
 *  `Confirm` was chosen because it satisfies §6's rule for what earns a story
 *  — it renders from props alone, fetching nothing — and because its variants
 *  are a genuine question rather than a demonstration: the difference between
 *  a take-over and a delete is entirely in the wording and the tone, and
 *  putting them side by side is the only way to see whether they read as
 *  differently as they behave.
 *
 *  Phase 1 re-implements this on Radix. When it does, these stories are the
 *  before-and-after picture, and `Confirm.test.tsx` is the net. */
const meta = {
  title: 'common/Confirm',
  component: Confirm,
  parameters: { layout: 'fullscreen' },
  args: { onConfirm: () => {}, onCancel: () => {} },
} satisfies Meta<typeof Confirm>

export default meta

type Story = StoryObj<typeof meta>

/** The wording that made `Confirm` worth building: a take-over says what
 *  survives it. */
export const TakeOver: Story = {
  args: {
    title: 'Take over this session?',
    lines: [
      'The agent stops where it is.',
      'Everything written so far survives, and you continue from the last event.',
    ],
    confirmLabel: 'Take over',
  },
}

/** The destructive tone, and the counterpart rule: a delete says what a delete
 *  does *not* take with it. Two paragraphs rather than one, which is the thing
 *  `window.confirm` could not do legibly and the reason this component exists. */
export const Delete: Story = {
  args: {
    title: 'Delete this session?',
    lines: [
      'The session and its event log are removed.',
      'Files it wrote into the workspace are left where they are.',
    ],
    confirmLabel: 'Delete',
    tone: 'danger',
  },
}
