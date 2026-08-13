import type { Meta, StoryObj } from '@storybook/react-vite'

import { AskHead } from './AskHead.tsx'
import { PROJECT } from './ask-fixtures.ts'

/** The heading and the facet control.
 *
 * The whole point of the story is the third link: Ask is drawn as current
 * rather than omitted, which is the difference between a control that says
 * where you are and one that only says where you are not.
 */
const meta = {
  component: AskHead,
  title: 'ask/AskHead',
  parameters: { layout: 'fullscreen' },
  args: { projectId: PROJECT, onReset: () => {} },
} satisfies Meta<typeof AskHead>

export default meta

type Story = StoryObj<typeof meta>

export const Default: Story = {}
