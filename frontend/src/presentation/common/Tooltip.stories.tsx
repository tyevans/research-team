import type { Meta, StoryObj } from '@storybook/react-vite'
import { useState } from 'react'

import { Shell } from '../layout/Shell.tsx'
import { Drawer } from './Drawer.tsx'
import { Chip } from './primitives.tsx'
import { Tooltip } from './Tooltip.tsx'

/** The first Radix primitive in this console, shown where its two halves can
 *  be checked separately.
 *
 * `Tooltip.test.tsx` settles the half that is structure — which component
 * closes on Escape, where the content lands in the DOM, whether the page went
 * `inert`. **Everything else about a floating element is only observable
 * here**, because jsdom runs no layout: whether the content is anywhere near
 * its trigger, whether it flips when the trigger is against an edge, and
 * whether it paints above a drawer rather than behind it.
 *
 * What to check, in order of how badly it would fail:
 *
 * - `AgainstTheEdges` — the tooltips must flip rather than run off the
 *   viewport. This is the entire reason a positioning library is worth 12 kB
 *   over a `title` attribute, and it is the one thing no test here can see.
 * - `OverADrawer` — with the pointer held on the trigger and the drawer open,
 *   the tooltip must paint **behind** the drawer, and one Escape must close
 *   the drawer and leave the tooltip. Both follow from the tooltip being
 *   portalled into `.lay-overlay-host` and registering with the host, and
 *   neither is checkable without a stacking context.
 * - `Keyboard` — Tab to each trigger. Every one must show its explanation on
 *   focus. This is the whole point of the migration: the same sentences are
 *   `title` attributes today, which a keyboard reaches never.
 *
 * `Shell` is what mounts the `OverlayHost`, and a `Tooltip` with no host in
 * scope deliberately renders no content at all — so a story that skipped the
 * `Shell` would show a trigger and nothing else, which is a real behaviour
 * argued in `Tooltip.tsx` rather than a broken story.
 */
const meta: Meta = {
  title: 'common/Tooltip',
  parameters: { layout: 'fullscreen' },
}

export default meta

type Story = StoryObj

/** Both trigger modes, side by side, because choosing wrongly between them is
 *  silent. The chip takes the default wrapper (a `<span>` is not focusable);
 *  the link takes `asChild` (an `<a href>` already is). Tab through: both must
 *  stop, and both must explain themselves. */
export const Keyboard: Story = {
  render: () => (
    <Shell chrome={<strong>research-team</strong>}>
      <div style={{ display: 'flex', gap: 'var(--space-4)', padding: 'var(--space-6)' }}>
        <Tooltip explanation="Some of this was reasoned rather than drawn from a source, and says so.">
          <Chip tone="inferred">inferred</Chip>
        </Tooltip>
        <Tooltip asChild explanation="Open this source at the offsets this artifact cites">
          <a className="prov-src" href="#nowhere">
            report.md 40–92
          </a>
        </Tooltip>
      </div>
    </Shell>
  ),
}

/** The positioning claim, which is the only reason this is a dependency.
 *
 * Four triggers pinned to the corners of the viewport. Each tooltip must stay
 * on screen — flipping to the other side of its trigger where it has to. A
 * `title` attribute does this too, which is worth remembering: what it cannot
 * do is any of the rest.
 */
export const AgainstTheEdges: Story = {
  render: () => (
    <Shell chrome={<strong>research-team</strong>}>
      <div style={{ position: 'relative', height: '100%' }}>
        {(
          [
            ['top', 'left'],
            ['top', 'right'],
            ['bottom', 'left'],
            ['bottom', 'right'],
          ] as const
        ).map(([vertical, horizontal]) => (
          <div
            key={`${vertical}-${horizontal}`}
            style={{ position: 'absolute', [vertical]: 0, [horizontal]: 0 }}
          >
            <Tooltip
              explanation={`Pinned to the ${vertical} ${horizontal}. This sentence is long enough that a tooltip which did not flip would leave the viewport.`}
            >
              <Chip>{`${vertical} ${horizontal}`}</Chip>
            </Tooltip>
          </div>
        ))}
      </div>
    </Shell>
  ),
}

/** The stacking claim, and the one that would have been a defect.
 *
 * Hold the pointer on the chip so the tooltip opens, then press *Show drawer*
 * — the drawer is later in the host's stack, so it must paint over the tooltip
 * and own Escape by itself. Radix's `DismissableLayer` would have answered
 * that keypress from its own stack, in which the drawer does not exist, and
 * closed both.
 *
 * Keep the pointer on the chip while pressing Escape: a tooltip opened by
 * *focus* closes when the drawer takes focus, so the interesting arrangement
 * is only reachable by hover.
 */
export const OverADrawer: Story = {
  render: function OverADrawerStory() {
    const [open, setOpen] = useState(false)
    return (
      <Shell chrome={<strong>research-team</strong>}>
        <div style={{ display: 'flex', gap: 'var(--space-4)', padding: 'var(--space-6)' }}>
          <Tooltip explanation="Entries that are neither a source span nor the inference flag.">
            <Chip tone="bad">3 unreadable</Chip>
          </Tooltip>
          <button type="button" className="btn btn-sm" onClick={() => setOpen(true)}>
            Show drawer
          </button>
        </div>

        {open ? (
          <Drawer heading="Worker" label="Worker detail" onClose={() => setOpen(false)}>
            <p>
              This must paint over the tooltip, and Escape must close this and leave the tooltip
              where it is.
            </p>
          </Drawer>
        ) : null}
      </Shell>
    )
  },
}
