import type { Meta, StoryObj } from '@storybook/react-vite'

import { AskComposer } from './AskComposer.tsx'

/** The question box.
 *
 * `Typed` is the story with something to say: the draft is the component's own
 * state, so the only way to see the enabled button is to type into it. That is
 * why there is a play-free `render` rather than an arg -- the component takes
 * no `draft` prop, and adding one to make a story easier would be the story
 * changing the component.
 */
const meta = {
  component: AskComposer,
  title: 'ask/AskComposer',
  parameters: { layout: 'fullscreen' },
  args: { asking: false, onAsk: () => {} },
} satisfies Meta<typeof AskComposer>

export default meta

type Story = StoryObj<typeof meta>

/** Empty, and the button disabled with it -- and it stays disabled for a box
 *  holding only spaces, which is the rule the trim enforces. */
export const Empty: Story = {}

/** Asking. The box is disabled for the length of the turn, because the server
 *  refuses a second question on a busy chat with a 409 and not sending it is
 *  the same answer without the round trip. */
export const Asking: Story = { args: { asking: true } }
