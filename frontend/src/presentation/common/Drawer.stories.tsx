import { useState } from 'react'
import type { Meta, StoryObj } from '@storybook/react-vite'

import { Button, Chip, EmptyState } from './primitives.tsx'
import { Confirm } from './Confirm.tsx'
import { Drawer } from './Drawer.tsx'

/** The panel read over the page, and the four things about it that are only
 *  checkable by looking.
 *
 * `Drawer` has nine call sites and had no story. It is the console's only
 * shared dialog shell, so everything it gets wrong it gets wrong nine times.
 *
 * Its docstring argues the keyboard contract at length and that part is
 * already covered by `Drawer.test.tsx` and by `OverlayHost`'s tests. What no
 * test here can judge is the geometry, and the geometry is where this
 * component has shipped defects before: `.confirm` carries a comment in
 * `tree.css` because the drawer once put its paragraphs against the border
 * and its confirm button on the last pixel column.
 *
 * So these stories are about the box. The stories to look at first are
 * `Flush` — which is the trade the `flush` prop exists to make visible — and
 * `Stacked`, which is the one behavioural claim in the file that no unit test
 * states in a way a person can see.
 *
 * A page sits behind every story on purpose. A drawer rendered over nothing
 * shows neither the backdrop nor the left border, and both are the whole
 * reason it reads as *over* rather than *instead of*.
 */
const meta: Meta = {
  title: 'common/Drawer',
}

export default meta

type Story = StoryObj

/** Something for the drawer to be read over. Deliberately busy: a backdrop
 *  over a blank page is indistinguishable from no backdrop. */
const Page = () => (
  <div style={{ padding: 'var(--space-3)', display: 'grid', gap: 'var(--space-2)' }}>
    <h2 style={{ font: 'inherit', color: 'var(--fg)', margin: 0 }}>The page behind</h2>
    {Array.from({ length: 14 }, (_, i) => (
      <p key={i} style={{ color: 'var(--fg-dim)', margin: 0 }}>
        A row of the list the drawer was opened from. Row {i + 1}.
      </p>
    ))}
  </div>
)

const Paragraphs = ({ n = 3 }: { n?: number }) => (
  <>
    {Array.from({ length: n }, (_, i) => (
      <p key={i} style={{ color: 'var(--fg-dim)' }}>
        Body copy, paragraph {i + 1}. The drawer&apos;s own inset is what holds this off the border;
        a caller that brings its own gets it twice.
      </p>
    ))}
  </>
)

/** The default. The body pads itself, which is the fix rather than the flag —
 *  padding used to be every caller's job and two callers forgot. */
export const Padded: Story = {
  render: () => (
    <>
      <Page />
      <Drawer heading="A worker" label="A worker" onClose={() => undefined}>
        <Paragraphs />
      </Drawer>
    </>
  ),
}

/** **The trade, side by side with the default.** `flush` turns the body's
 *  inset off for a caller that brings its own — a scroller with its own inset,
 *  prose with its own measure.
 *
 *  What to check: the flush body's content reaches the drawer's left border.
 *  That is correct *only* when the caller pads it back. Left as it is here it
 *  is exactly the defect `.confirm` was written to end, which is why this
 *  story shows it undressed rather than showing a well-behaved caller — a
 *  story where the prop looks harmless teaches the wrong thing. Compare with
 *  `Padded`; the difference is `12px` horizontally and `12/16px` vertically. */
export const Flush: Story = {
  render: () => (
    <>
      <Page />
      <Drawer heading="Flush body" label="Flush body" flush onClose={() => undefined}>
        <Paragraphs n={2} />
      </Drawer>
    </>
  ),
}

/** The `actions` slot, which sits beside Close rather than replacing it.
 *
 *  Close is always last and always present. A drawer whose only exit is a
 *  caller-supplied control is a drawer that can ship without one. */
export const WithActions: Story = {
  render: () => (
    <>
      <Page />
      <Drawer
        heading="A document"
        label="A document"
        actions={
          <>
            <Chip tone="ok">indexed</Chip>
            <Button small tone="quiet">
              Open source
            </Button>
          </>
        }
        onClose={() => undefined}
      >
        <Paragraphs />
      </Drawer>
    </>
  ),
}

/** A heading long enough to compete with the actions beside it.
 *
 *  The header is `flex` with a `flex-auto` spacer, so a long heading pushes
 *  rather than wraps. What to check: Close stays on the row and stays
 *  reachable. If it has been pushed off the right edge, the spacer or the
 *  heading's shrink behaviour has changed. */
export const LongHeading: Story = {
  render: () => (
    <>
      <Page />
      <Drawer
        heading="A heading long enough that it has to give way to the controls beside it"
        label="A long heading"
        actions={
          <Button small tone="quiet">
            Open source
          </Button>
        }
        onClose={() => undefined}
      >
        <Paragraphs n={2} />
      </Drawer>
    </>
  ),
}

/** More body than fits.
 *
 *  The header and footer are `flex-none` and the body is `flex-auto
 *  overflow-auto`, so the head must stay put while the body scrolls. A drawer
 *  whose header scrolls away takes its Close button with it. */
export const Scrolling: Story = {
  render: () => (
    <>
      <Page />
      <Drawer heading="A long document" label="A long document" onClose={() => undefined}>
        <Paragraphs n={40} />
      </Drawer>
    </>
  ),
}

/** Nothing to show, inside something that is nonetheless open.
 *
 *  Worth a story because the two components were reasoned about separately:
 *  `EmptyState` centres nothing and the drawer pads it, so an empty drawer
 *  should read as deliberate rather than as a failed load. */
export const Empty: Story = {
  render: () => (
    <>
      <Page />
      <Drawer heading="Citations" label="Citations" onClose={() => undefined}>
        <EmptyState heading="No citations" detail="This answer cited nothing." />
      </Drawer>
    </>
  ),
}

/** **`Confirm` over `Drawer`, which is the claim worth seeing.**
 *
 *  `Drawer.tsx` states that this works "without either knowing about it" —
 *  the host marks the page `inert` and gives Escape to the topmost layer
 *  only, where the deleted hand-rolled trap would have closed both dialogs on
 *  one keypress and let Tab walk between them.
 *
 *  `Confirm` is itself a `Drawer`, so this is a drawer over a drawer over a
 *  page. What to check by eye: two backdrops, the confirm on top, and the
 *  drawer under it dimmed rather than merely covered. What to check by
 *  keyboard: Escape closes the confirm and leaves the drawer open, and Tab
 *  from the confirm never reaches the drawer's Close button.
 *
 *  Interactive rather than static because the claim is about what a *second*
 *  layer does to the first, and a story that renders both already-open cannot
 *  show the Escape half of it. */
export const Stacked: Story = {
  render: function Render() {
    const [confirming, setConfirming] = useState(false)
    return (
      <>
        <Page />
        <Drawer heading="A worker" label="A worker" onClose={() => undefined}>
          <Paragraphs n={2} />
          <div>
            <Button tone="danger" onClick={() => setConfirming(true)}>
              Cancel this run
            </Button>
          </div>
        </Drawer>
        {confirming ? (
          <Confirm
            heading="Cancel this run?"
            lines={[
              'The run stops after the dispatch in flight finishes.',
              'Everything already written is kept.',
            ]}
            confirmLabel="Cancel the run"
            tone="danger"
            onConfirm={() => setConfirming(false)}
            onCancel={() => setConfirming(false)}
          />
        ) : null}
      </>
    )
  },
}
