import type { Meta, StoryObj } from '@storybook/react-vite'

import type { ConnectionState } from '@application/ports/event-stream.ts'

import { ConnectionBadge } from './ConnectionBadge.tsx'

/** Whether the console is live, in the three states it can be in.
 *
 * This badge is on every route and is the only thing on screen that says
 * whether what you are reading is current. A console showing stale rows and a
 * console showing live ones are the same picture apart from this pill, which
 * is the whole argument for enumerating its states on one page.
 *
 * **The mapping is not one-to-one and that is the thing to see here.**
 * `ConnectionState` has three values and the stylesheet keys off `data-state`,
 * which the component computes as `open` / `down` / `init` — `connecting`
 * becomes `init`. So there are three states, three labels and three
 * appearances, but the component and the stylesheet name them differently, and
 * the two vocabularies only meet in one ternary.
 *
 * What each should read as:
 *
 * - **live** — settled and good. Green, with a glow on the dot.
 * - **reconnecting** — settled and bad. Red, dot pulsing.
 * - **connecting** — not settled yet. Neutral grey, dot pulsing.
 *
 * The last is the one worth checking against the other two. It is
 * deliberately *not* coloured: `shell.css` gives `init` the pulse and nothing
 * else, so it inherits `--fg-faint` from `.conn`. A first paint that flashed
 * red before the stream opened would report an outage on every page load, and
 * a first paint that flashed green would claim a stream that is not there
 * yet. Grey-and-pulsing is the only honest answer while the question is open.
 */
const meta: Meta = {
  title: 'shell/ConnectionBadge',
}

export default meta

type Story = StoryObj

const STATES: readonly ConnectionState[] = ['open', 'down', 'connecting']

/** All three, together, which is the only arrangement that makes the
 *  comparison above possible. Separately each one looks reasonable. */
export const EveryState: Story = {
  render: () => (
    <div
      style={{
        display: 'flex',
        gap: 'var(--space-3)',
        alignItems: 'center',
        padding: 'var(--space-3)',
      }}
    >
      {STATES.map((state) => (
        <ConnectionBadge key={state} state={state} />
      ))}
    </div>
  ),
}

/** The badge where it actually sits — in a header row, against the chrome
 *  rather than against an empty canvas.
 *
 *  A pill judged on a blank page is judged on nothing: the border is
 *  `--line` and the label is `--fg-faint`, so both are chosen to be quiet
 *  *beside other things*. This is the story to look at before changing either. */
export const InAHeader: Story = {
  render: () => (
    <header
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 'var(--space-3)',
        padding: 'var(--space-2) var(--space-3)',
        borderBottom: '1px solid var(--line)',
        background: 'var(--bg-panel)',
      }}
    >
      <strong style={{ color: 'var(--fg)' }}>research-team</strong>
      <nav style={{ color: 'var(--fg-faint)' }}>projects / ancient-rome / graph</nav>
      <span style={{ flex: 'auto' }} />
      <ConnectionBadge state="open" />
    </header>
  ),
}
