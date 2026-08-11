import type { Meta, StoryObj } from '@storybook/react-vite'
import { useState } from 'react'

import { Shell } from '../layout/Shell.tsx'
import { Drawer } from './Drawer.tsx'
import { Popover } from './Popover.tsx'

/** The half of a popover that only a browser can settle.
 *
 * `Popover.test.tsx` holds the structure — which component closes on Escape,
 * where the content lands in the DOM, where focus is, whether `inert` was
 * applied. jsdom runs no layout and resolves no stacking context, so
 * everything below is invisible to it:
 *
 * - `AgainstTheEdges` — the panel must stay on screen, flipping to the other
 *   side of its trigger where it has to. This is the whole reason the agent
 *   dock stopped pinning itself with `position: fixed; top: var(--topbar-h)`,
 *   and the old rule needed a media query at 420px precisely because it could
 *   not do this.
 * - `UnderADrawer` — with the popover open, press *Show drawer*. The drawer
 *   must paint **over** the panel, the panel must be unclickable (it is
 *   `inert`), and one Escape must close the drawer and leave the popover. That
 *   is task #11's defect, which shipped as a popover at `z-index: 40` over a
 *   modal backdrop at 20.
 * - `Keyboard` — Tab to the trigger, press Enter. Focus must move into the
 *   panel. Escape must close it and put focus back on the trigger. Tab out of
 *   the last control leaves the panel open behind you, which is a stated cost
 *   argued in `Popover.tsx` rather than a bug.
 *
 * `Shell` mounts the `OverlayHost`, and a `Popover` with no host in scope
 * deliberately renders nothing at all — so a story without one would show a
 * trigger that opens onto empty space.
 */
const meta: Meta = {
  title: 'common/Popover',
  parameters: { layout: 'fullscreen' },
}

export default meta

type Story = StoryObj

const PANEL = 'rounded-md border border-solid border-line bg-bg-panel p-4 text-sm text-fg shadow-1'

export const Keyboard: Story = {
  render: function KeyboardStory() {
    const [open, setOpen] = useState(false)
    return (
      <Shell chrome={<strong>research-team</strong>}>
        <div style={{ padding: 'var(--space-6)' }}>
          <Popover
            open={open}
            onOpenChange={setOpen}
            label="What is running"
            className={PANEL}
            trigger={
              <button type="button" className="btn btn-sm">
                3 running
              </button>
            }
          >
            <p>Focus should be in here.</p>
            <button type="button" className="btn btn-sm">
              open a feed
            </button>
          </Popover>
        </div>
      </Shell>
    )
  },
}

/** The positioning claim, which is the only reason this is a dependency.
 *
 * Four triggers in the corners. Each panel must stay on screen — the one at
 * the bottom must open upwards, and the ones on the right must not run off the
 * edge. The rule this replaced could do neither: it hung the panel from
 * `top: var(--topbar-h); right: var(--space-4)` and was correct only for a
 * trigger at the right-hand end of the topbar.
 */
export const AgainstTheEdges: Story = {
  render: function EdgesStory() {
    const [open, setOpen] = useState<string | null>(null)
    return (
      <Shell chrome={<strong>research-team</strong>}>
        <div style={{ position: 'relative', height: '100%' }}>
          {(
            [
              ['top', 'left'],
              ['top', 'right'],
              ['bottom', 'left'],
              ['bottom', 'right'],
            ] as const
          ).map(([vertical, horizontal]) => {
            const key = `${vertical}-${horizontal}`
            return (
              <div key={key} style={{ position: 'absolute', [vertical]: 0, [horizontal]: 0 }}>
                <Popover
                  open={open === key}
                  onOpenChange={(next) => setOpen(next ? key : null)}
                  label={key}
                  className={PANEL}
                  align={horizontal === 'right' ? 'end' : 'start'}
                  trigger={
                    <button type="button" className="btn btn-sm">
                      {key}
                    </button>
                  }
                >
                  <p style={{ maxWidth: '24rem' }}>
                    Pinned to the {vertical} {horizontal}. This panel is wide enough and tall enough
                    that one which did not flip would leave the viewport.
                  </p>
                </Popover>
              </div>
            )
          })}
        </div>
      </Shell>
    )
  },
}

/** The stacking claim, and the one that was a defect in production.
 *
 * Open the popover, then press *Show drawer*. The drawer mounts later, so it
 * is later in the host's stack and must paint over the panel; the panel goes
 * `inert`, so nothing in it can be clicked or focused. One Escape closes the
 * drawer and leaves the popover exactly where it was — Radix would have
 * answered that keypress from its own stack, in which the drawer does not
 * exist, and closed both.
 */
export const UnderADrawer: Story = {
  render: function UnderADrawerStory() {
    const [open, setOpen] = useState(false)
    const [drawer, setDrawer] = useState(false)
    return (
      <Shell chrome={<strong>research-team</strong>}>
        <div style={{ display: 'flex', gap: 'var(--space-4)', padding: 'var(--space-6)' }}>
          <Popover
            open={open}
            onOpenChange={setOpen}
            label="What is running"
            className={PANEL}
            trigger={
              <button type="button" className="btn btn-sm">
                3 running
              </button>
            }
          >
            <p>This must go under the drawer, and must survive its Escape.</p>
            <button type="button" className="btn btn-sm">
              try to click me while the drawer is open
            </button>
          </Popover>
          <button type="button" className="btn btn-sm" onClick={() => setDrawer(true)}>
            Show drawer
          </button>
        </div>

        {drawer ? (
          <Drawer heading="Worker" label="Worker detail" onClose={() => setDrawer(false)}>
            <p>Escape must close this and leave the popover open behind it.</p>
          </Drawer>
        ) : null}
      </Shell>
    )
  },
}
