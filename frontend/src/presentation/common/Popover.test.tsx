import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import { expect, it } from 'vitest'

import { OverlayHost } from '../layout/OverlayHost.tsx'
import { Drawer } from './Drawer.tsx'
import { Popover } from './Popover.tsx'

/** Whether the bridge `Tooltip` established holds for a primitive that takes
 *  focus.
 *
 * A tooltip never moves focus; a popover does, through Radix's `FocusScope`.
 * So the open question here is not "does the bridge exist" -- it is copied
 * verbatim -- but whether the focus scope and the host's layer stack interact.
 * They are two mechanisms that both have opinions about where the reader is,
 * arriving from different libraries.
 *
 * **What jsdom can and cannot show.** It can show which component closed on a
 * keypress, where the content landed in the DOM, whether `inert` was applied,
 * and where focus is. It cannot show that the panel is anywhere near its
 * trigger, that it flips off a viewport edge, or that it paints above a
 * drawer: jsdom runs no layout and resolves no stacking context. Those are
 * `Popover.stories.tsx`.
 */

const PANEL = 'what is running'

/** A popover, and a drawer that can be put in front of it.
 *
 * **The drawer is opened by a prop rather than by a button, and that is not
 * test convenience.** Anything that opens the drawer from inside the page
 * moves focus -- `Drawer` focuses its Close button -- and a popover whose
 * focus scope has been left behind is a different arrangement from the one
 * under test. Driving it by prop keeps the popover exactly as the reader left
 * it, which is also what really happens: a live run pushes a worker drawer up
 * while the reader is reading the dock.
 *
 * `Tooltip.test.tsx` documents the sharper version of the same problem -- a
 * hover-opened tooltip is closed by the drawer's focus move before Escape is
 * ever pressed, so the first version of that test proved nothing.
 */
const Fixture = ({ drawerOpen = false }: { drawerOpen?: boolean }) => {
  const [open, setOpen] = useState(false)
  const [closed, setClosed] = useState(false)
  return (
    <OverlayHost>
      <Popover
        open={open}
        onOpenChange={setOpen}
        label="Agents running now"
        trigger={<button type="button">3 running</button>}
      >
        <p>{PANEL}</p>
        <button type="button">open a feed</button>
      </Popover>
      <button type="button">something else</button>
      {drawerOpen && !closed ? (
        <Drawer heading="Worker" label="Worker detail" onClose={() => setClosed(true)}>
          <p>drawer body</p>
        </Drawer>
      ) : null}
    </OverlayHost>
  )
}

const openPopover = async (user: ReturnType<typeof userEvent.setup>) => {
  await user.click(screen.getByRole('button', { name: '3 running' }))
  await screen.findByText(PANEL)
}

it('gives Escape to the drawer in front, and leaves the popover open', async () => {
  const user = userEvent.setup()
  const { rerender } = render(<Fixture />)
  await openPopover(user)

  rerender(<Fixture drawerOpen />)
  expect(await screen.findByRole('dialog', { name: 'Worker detail' })).toBeInTheDocument()

  await user.keyboard('{Escape}')

  // Task #11's defect, which was a popover at `z-index: 40` over a modal
  // backdrop at 20. The stacking half is gone; this is the dismissal half, and
  // it is the assertion the whole bridge exists for. Without
  // `onEscapeKeyDown`'s `preventDefault`, Radix's `DismissableLayer` answers
  // this keypress on `document` at capture from a stack in which the drawer
  // does not appear, and closes the popover as well.
  expect(screen.queryByRole('dialog', { name: 'Worker detail' })).toBeNull()
  expect(screen.getByText(PANEL)).toBeInTheDocument()
})

it('goes inert under a modal drawer', async () => {
  const user = userEvent.setup()
  const { rerender } = render(<Fixture />)
  await openPopover(user)

  const panel = screen.getByRole('dialog', { name: 'Agents running now' })
  expect(panel).not.toHaveAttribute('inert')

  rerender(<Fixture drawerOpen />)

  // The host's central guarantee, and the one a Radix layer does not get for
  // free: `Overlay` applies `inert` to `.lay-layer`, and Radix content is
  // portalled into the container with no `.lay-layer` around it. Without the
  // `blocked` computation in `PopoverLayer` this panel stays clickable and
  // stays in the accessibility tree underneath an `aria-modal` dialog -- which
  // is task #11's defect, arriving through the fix for task #11's defect.
  //
  // Found by an *existing* test rather than this one: the dock's `opens the
  // agent's feed when its row is clicked` began matching two dialogs.
  expect(panel).toHaveAttribute('inert')
  expect(panel).toHaveAttribute('aria-hidden', 'true')
})

it('gives Escape to the popover when nothing is in front of it', async () => {
  const user = userEvent.setup()
  render(<Fixture />)
  await openPopover(user)

  await user.keyboard('{Escape}')

  expect(screen.queryByText(PANEL)).toBeNull()
})

it('gives Escape back to the trigger', async () => {
  const user = userEvent.setup()
  render(<Fixture />)
  await openPopover(user)

  await user.keyboard('{Escape}')

  // The close runs through the host -- `onDismiss` sets `open` to false --
  // rather than through Radix's own dismissal, so nothing here asked Radix to
  // restore focus. It restores on unmount whatever caused the unmount, which
  // is the property this depends on and the one a Radix upgrade could move.
  // The dock deleted a `close()` helper that did this by hand; if this ever
  // goes red the answer is not to write that helper again but to close through
  // Radix.
  expect(screen.getByRole('button', { name: '3 running' })).toHaveFocus()
})

it('does not make the page inert — a popover is not modal', async () => {
  const user = userEvent.setup()
  render(<Fixture />)
  await openPopover(user)

  // `Popover` has no `modal` prop, and Radix's own modal mode is left off. Two
  // things could make this fail: passing `modal: true` to `useLayer` to get
  // the layer "properly on top", or turning Radix's modality on, which would
  // `aria-hidden` the page from a stack that has never heard of the host.
  // Two attributes, because the two failure modes use different ones:
  // `useLayer({modal: true})` here would set `inert`, and Radix's own modal
  // mode would set `aria-hidden` and would leave `inert` untouched. `Menu`'s
  // equivalent test was green against a reverted guard until it checked both.
  const page = document.querySelector('.lay-app-root')
  expect(page).not.toHaveAttribute('inert')
  expect(page).not.toHaveAttribute('aria-hidden')
  expect(screen.getByRole('button', { name: 'something else' })).toBeInTheDocument()
})

it('renders the panel inside the overlay host, not loose in the body', async () => {
  const user = userEvent.setup()
  render(<Fixture />)
  await openPopover(user)

  // Portalling to the host's container is what puts the panel at
  // `--z-overlay`. Radix's default is `document.body`, where the only way to
  // get above a drawer is a `z-index` of its own -- which
  // `scripts/check-deleted.mjs` fails the build over.
  expect(screen.getByText(PANEL).closest('.lay-overlay-host')).not.toBeNull()
})
