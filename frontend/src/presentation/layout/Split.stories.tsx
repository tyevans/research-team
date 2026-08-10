import type { Meta, StoryObj } from '@storybook/react-vite'
import { useState } from 'react'

import { Pane } from './Pane.tsx'
import { Split } from './Split.tsx'
import type { Track } from './split-tracks.ts'

/** The session view's three panes, as data.
 *
 * These are the numbers from `use-panes.ts:67-74` rather than the ones from
 * `panes.css:73`, which describe the same three columns and disagree — 280 vs
 * 300 on two minima, and 1.05 vs 1.15 on the third weight. The hook's are kept
 * because the hook's are what a reader sees above 1181px today, so adopting
 * them changes nothing anybody has looked at. That the choice had to be made
 * at all is the argument for one declaration. */
const SESSION_TRACKS: readonly Track[] = [
  { id: 'timeline', min: 280, weight: 1.05 },
  { id: 'workspace', min: 320, weight: 1.5 },
  { id: 'conversation', min: 280, weight: 1.05 },
]

/** Stories are the primary artifact for this phase, not an extra, and the
 *  reason is in `split-tracks.test.ts`: jsdom lays nothing out, so the unit
 *  tests constrain which template string is emitted and nothing about the grid
 *  it describes. **Storybook runs in a real browser, so these are the only
 *  place the layout is actually exercised.** Resize the preview pane across
 *  1181px and the handoff either works or it does not.
 *
 *  Every story is stateful, because a collapsed pane you cannot expand tells
 *  you nothing about collapsing. */
/** Typed as a bare `Meta` rather than `satisfies Meta<typeof Component>`.
 *
 * The bound form makes `args` mandatory on every story, and every story in
 * this file supplies its whole tree through `render` because the interesting
 * states are stateful — a collapsed pane you cannot expand, or an overlay
 * nothing opens, demonstrates nothing. Declaring `args` as well would mean
 * writing the props twice and letting the two copies disagree. The cost is
 * that Storybook cannot infer an args table for the controls panel; there is
 * no docs addon installed to show one, and these compositions have no single
 * component whose props a table would describe. */
const meta: Meta = {
  title: 'layout/Split',
  parameters: { layout: 'fullscreen' },
}

export default meta

type Story = StoryObj

const Workbench = ({
  initial = [],
  unmountConversation = false,
}: {
  initial?: readonly string[]
  unmountConversation?: boolean
}) => {
  const [collapsed, setCollapsed] = useState<ReadonlySet<string>>(new Set(initial))
  const [refused, setRefused] = useState(false)

  return (
    <div style={{ height: '80vh', display: 'flex', flexDirection: 'column' }}>
      <Split
        id="session"
        label="Session panes"
        tracks={SESSION_TRACKS}
        collapsed={collapsed}
        onCollapsedChange={(next) => {
          setRefused(false)
          setCollapsed(next)
        }}
        onRefuse={() => setRefused(true)}
      >
        <Pane id="timeline" label="Timeline" meta="128 events" collapseTo="rail" minContent={240}>
          <p style={{ padding: 'var(--space-3)' }}>the event log</p>
        </Pane>
        <Pane id="workspace" label="Workspace" meta="6 files" collapseTo="rail" minContent={240}>
          <p style={{ padding: 'var(--space-3)' }}>files and diffs</p>
        </Pane>
        <Pane
          id="conversation"
          label="Conversation"
          collapseTo="strip"
          unmountWhenCollapsed={unmountConversation}
        >
          <p style={{ padding: 'var(--space-3)' }}>the transcript</p>
        </Pane>
      </Split>
      {/* The view's answer to a refusal, shown here because the primitive
          deliberately does not have one — `onRefuse` exists so the toast stays
          the view's business. */}
      <p role="status" style={{ padding: 'var(--space-3)', color: 'var(--k-failure)' }}>
        {refused ? 'At least one pane has to stay open.' : ' '}
      </p>
    </div>
  )
}

/** Three open panes, sized from one declaration. */
export const ThreePanes: Story = { render: () => <Workbench /> }

/** One collapsed to a rail. The space it gives up goes to the other two, which
 *  is the entire point of collapsing and is why the track is fixed rather than
 *  a reduced minimum. */
export const OneCollapsed: Story = { render: () => <Workbench initial={['timeline']} /> }

/** Two collapsed. Try to collapse the third: the split refuses, and says so
 *  through the view. The research rail permits this today and its own report
 *  records the cost — a folded seeding pane leaves a reader looking at
 *  "nothing has been seeded" with no seeding control on screen. */
export const LastOpenRefuses: Story = {
  render: () => <Workbench initial={['timeline', 'workspace']} />,
}

/** The conversation set to drop its body rather than hide it. Visually
 *  identical to `OneCollapsed`; the difference is in the DOM, and it is the
 *  difference between a virtualizer that comes back with rows and one that
 *  measured a zero-height container while it was hidden and came back
 *  empty. */
export const UnmountOnCollapse: Story = {
  render: () => <Workbench initial={['conversation']} unmountConversation />,
}

/** Above the breakpoint: `Split` writes `grid-template-columns` and owns the
 *  shape. */
export const AboveTheBreakpoint: Story = {
  render: () => <Workbench />,
  parameters: {
    viewport: { value: 'wide' },
  },
}

/** Below it: `Split` writes **no** template, and the stylesheet reflows the
 *  panes into a column.
 *
 *  This is the handoff the session report calls "genuinely subtle and worth
 *  preserving", and it is the one story worth opening in a real browser before
 *  believing any of this: an inline `grid-template-columns` outranks a media
 *  query, so a `Split` that emitted one here would silently defeat every
 *  responsive rule beneath it — at a window width nobody developing it is
 *  likely to use. The unit test asserts `undefined` is returned; only this
 *  shows the reflow that depends on it. */
export const BelowTheBreakpoint: Story = {
  render: () => <Workbench />,
  parameters: {
    viewport: { value: 'narrow' },
  },
}
