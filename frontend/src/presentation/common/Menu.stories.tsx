import type { Meta, StoryObj } from '@storybook/react-vite'
import { useState } from 'react'

import { Shell } from '../layout/Shell.tsx'
import { Menu, MenuItem } from './Menu.tsx'

/** A menu, shown where the two things jsdom cannot judge are visible.
 *
 * `Menu.test.tsx` settles the keyboard contract — arrow keys between items,
 * Enter to run one, Escape to close and return focus. What it cannot settle is
 * where the panel lands and what it looks like doing it:
 *
 * - `InARow` — the menu must escape its row. The version this replaces was
 *   `position: absolute; right: 0` inside the row at `z-index: var(--z-sticky)`,
 *   so a menu on the last row of a scrolling list was clipped by whatever the
 *   row was inside. Scroll the list with a menu open and watch it track its
 *   trigger.
 * - `AgainstTheEdge` — the bottom-most trigger's menu must open upwards.
 * - The highlight — move through the items with the arrow keys and with the
 *   pointer in turn. Both must draw the same highlight, because
 *   `data-[highlighted]` is what a menu selects with and `:hover` alone would
 *   leave a keyboard reader looking at a menu with nothing selected.
 *
 * `Shell` mounts the `OverlayHost`; without one the menu opens onto nothing.
 */
const meta: Meta = {
  title: 'common/Menu',
  parameters: { layout: 'fullscreen' },
}

export default meta

type Story = StoryObj

const Row = ({ name }: { name: string }) => {
  const [open, setOpen] = useState(false)
  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 'var(--space-3)',
        padding: 'var(--space-2) var(--space-3)',
        borderBottom: '1px solid var(--line-soft)',
      }}
    >
      <span style={{ flex: '1 1 auto' }}>{name}</span>
      <Menu
        open={open}
        onOpenChange={setOpen}
        label={`More actions for ${name}`}
        trigger={
          <button type="button" className="menu-trigger" aria-label={`More actions for ${name}`}>
            ⋯
          </button>
        }
      >
        <MenuItem onSelect={() => {}}>Rename</MenuItem>
        <MenuItem onSelect={() => {}}>Duplicate</MenuItem>
        <MenuItem disabled onSelect={() => {}}>
          Archive
        </MenuItem>
        <MenuItem tone="danger" onSelect={() => {}}>
          Delete
        </MenuItem>
      </Menu>
    </div>
  )
}

/** The row menu as it actually appears, in a list that scrolls. */
export const InARow: Story = {
  render: () => (
    <Shell chrome={<strong>research-team</strong>}>
      <div style={{ maxHeight: '18rem', overflowY: 'auto', margin: 'var(--space-6)' }}>
        {['atlas', 'borealis', 'cinder', 'delta', 'ember', 'fathom', 'gantry'].map((name) => (
          <Row key={name} name={name} />
        ))}
      </div>
    </Shell>
  ),
}

/** The trigger is at the bottom of the viewport, so the menu has to open
 *  upwards. The `position: absolute; top: calc(100% + …)` rule this replaces
 *  could only ever open downwards, off the bottom of the screen. */
export const AgainstTheEdge: Story = {
  render: () => (
    <Shell chrome={<strong>research-team</strong>}>
      <div style={{ position: 'relative', height: '100%' }}>
        <div style={{ position: 'absolute', bottom: 0, right: 0, padding: 'var(--space-4)' }}>
          <Row name="the last row" />
        </div>
      </div>
    </Shell>
  ),
}
