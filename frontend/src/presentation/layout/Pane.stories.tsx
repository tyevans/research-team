import type { Meta, StoryObj } from '@storybook/react-vite'
import { useState } from 'react'

import { Pane } from './Pane.tsx'

/** A pane on its own, which is the point: it renders from props alone, so it
 *  has a story, so it is a component.
 *
 *  The two states the migration will lean on hardest are `CollapsedToRail` and
 *  `CollapsedToStrip`, because they are the two class names and two
 *  stylesheets this replaces — `panes.css`'s `.pane.collapsed` and
 *  `research.css`'s `is-folded`, which exists only because the first one's
 *  rules "would rotate the title". Side by side here, they are one parameter. */
const meta = {
  title: 'layout/Pane',
  component: Pane,
  parameters: { layout: 'fullscreen' },
  args: { id: 'timeline', label: 'Timeline', meta: '128 events' },
  decorators: [
    (Story) => (
      <div style={{ height: '60vh', display: 'flex', width: '420px' }}>
        <Story />
      </div>
    ),
  ],
} satisfies Meta<typeof Pane>

export default meta

type Story = StoryObj<typeof meta>

const Rows = () => (
  <div style={{ padding: 'var(--space-3)' }}>
    {Array.from({ length: 20 }, (_, index) => (
      <p key={index}>event {index + 1}</p>
    ))}
  </div>
)

export const Open: Story = {
  render: (args) => <Pane {...args}>{<Rows />}</Pane>,
}

/** With a toggle, so the collapse can actually be exercised. A pane given no
 *  `onToggle` and no enclosing `Split` renders no toggle at all rather than a
 *  dead button. */
export const Toggleable: Story = {
  render: (args) => {
    const Toggling = () => {
      const [collapsed, setCollapsed] = useState(false)
      return (
        <Pane {...args} collapsed={collapsed} onToggle={() => setCollapsed((was) => !was)}>
          <Rows />
        </Pane>
      )
    }
    return <Toggling />
  },
}

/** 34px, title on its side. What the session view does above 1181px, and the
 *  reason the collapsed pane stays on screen at all: the title is how you know
 *  what you closed and the toggle is how you get it back. */
export const CollapsedToRail: Story = {
  render: (args) => (
    <Pane {...args} collapsed collapseTo="rail" onToggle={() => {}}>
      <Rows />
    </Pane>
  ),
}

/** The same pane as a row: title level, body gone. What the research rail
 *  needed a second class name for, and what the session panes become below
 *  820px. */
export const CollapsedToStrip: Story = {
  decorators: [
    (Story) => (
      <div style={{ height: '60vh', display: 'flex', flexDirection: 'column', width: '520px' }}>
        <Story />
      </div>
    ),
  ],
  render: (args) => (
    <Pane {...args} collapsed collapseTo="strip" onToggle={() => {}}>
      <Rows />
    </Pane>
  ),
}

/** A content floor. 240px is `research.css`'s existing fix — an even split of
 *  a laptop viewport across three regions left each list showing three or four
 *  rows, "which is a scrollbar rather than a list" — as a parameter that
 *  travels with the pane rather than a literal selecting two pane names in one
 *  stylesheet. */
export const WithContentFloor: Story = {
  render: (args) => (
    <Pane {...args} label="Topics" meta="18 open" minContent={240}>
      <p style={{ padding: 'var(--space-3)' }}>Never squashed below 240px.</p>
    </Pane>
  ),
}

/** Actions in the header, which a rail deliberately drops: a button 34px wide
 *  with its label turned on its side is worse than absent. */
export const WithActions: Story = {
  render: (args) => (
    <Pane {...args} actions={<button type="button">filter</button>}>
      <Rows />
    </Pane>
  ),
}
