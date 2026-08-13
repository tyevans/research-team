import type { Meta, StoryObj } from '@storybook/react-vite'
import type { ReactNode } from 'react'

import { TruncatedText } from './TruncatedText.tsx'

/** Text that clips, beside the same text that does not.
 *
 * This component's own docstring says why it needs a browser more plainly than
 * anything else in this directory: "under jsdom this renders plain text and
 * never a tooltip, because `scrollWidth` and `clientWidth` are both 0 there
 * and nothing is ever clipped". Every claim it makes is a measurement.
 * `TruncatedText.browser.test.tsx` takes the ones that can be asserted -- that
 * a tooltip appears at 423px against 200px and not at 100px -- and the two
 * this story exists for cannot be asserted at all:
 *
 * - **The focus ring is only there while the text is clipped.** It is spelled
 *   as three Tailwind utilities on the span rather than as a class in a
 *   stylesheet, precisely because the stylesheet that would own it belongs to
 *   the caller. A focus stop nobody can see is not a focus stop, and whether
 *   this one is visible against `--bg` is a contrast judgement.
 * - **Which of two adjacent labels is focusable.** Tab through the row below:
 *   focus lands on the clipped label and skips the short one. That asymmetry
 *   is the whole design -- the tab order gains a stop only where there is
 *   something to reveal -- and it reads as a bug until you see the two
 *   together.
 *
 * The narrow column is a plain `width` rather than a `Pane`, deliberately: the
 * component measures its own box and does not care what sized it, and putting
 * a layout primitive in the way would make this a story about two components.
 */
const meta: Meta = {
  title: 'common/TruncatedText',
  parameters: { layout: 'padded' },
}

export default meta

type Story = StoryObj

const LONG =
  'Did the funder see the manuscript before it was submitted, and if so is that disclosed anywhere other than the acknowledgements?'

/** A flex row of a fixed width, because that is the only arrangement in which
 *  `.ent-status-detail` truncates at all: it is `flex: 0 1 auto; min-width: 0`,
 *  and its own comment in `entity.css` records that the `min-width` was a real
 *  bug when it was missing. A story that wrapped the text in a `display: block`
 *  box would show no ellipsis and no tooltip and look like the component was
 *  broken. */
const Row = ({ width, children }: { width: number; children: ReactNode }) => (
  <div style={{ display: 'flex', width: `${String(width)}px`, gap: 'var(--space-2)' }}>
    {children}
  </div>
)

/** Both cases, which is the comparison. Hover the first for the explanation;
 *  tab through both and only the first takes focus. */
export const ClippedAndNot: Story = {
  render: () => (
    <div style={{ display: 'grid', gap: 'var(--space-3)' }}>
      <Row width={320}>
        <TruncatedText text={LONG} className="ent-status-detail" />
      </Row>
      <Row width={320}>
        <TruncatedText text="Held at seed" className="ent-status-detail" />
      </Row>
    </div>
  ),
}

/** The same text at three widths, which is where the threshold is visible.
 *
 * Drag the preview pane narrower and the middle column crosses over while you
 * watch. That crossing remounts the span -- the cost the component's docstring
 * names and accepts -- so a reader focused on the label loses focus to the
 * body as it un-clips. There is no test for that anywhere; this is where
 * anyone would see it. */
export const AcrossWidths: Story = {
  render: () => (
    <div style={{ display: 'flex', gap: 'var(--space-4)', alignItems: 'start' }}>
      {[160, 320, 640].map((width) => (
        <div key={width}>
          <div style={{ color: 'var(--fg-faint)' }}>{width}px</div>
          <Row width={width}>
            <TruncatedText text={LONG} className="ent-status-detail" />
          </Row>
        </div>
      ))}
    </div>
  ),
}
