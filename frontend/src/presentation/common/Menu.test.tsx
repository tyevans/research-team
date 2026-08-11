import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import { expect, it, vi } from 'vitest'

import { OverlayHost } from '../layout/OverlayHost.tsx'
import { Drawer } from './Drawer.tsx'
import { Menu, MenuItem } from './Menu.tsx'

/** The keyboard contract a `Disclosure` wearing menu chrome did not have.
 *
 * The row menu on a project was a disclosure until this commit: it announced
 * `aria-expanded` over a region and offered none of what a menu owes -- no
 * `role="menu"`, no arrow-key movement, no Escape, no focus return. So most of
 * these tests are not guards against a regression in `Menu`; they are the
 * statement of what the conversion bought, and every one of them fails against
 * the thing being replaced.
 *
 * jsdom is a fair judge of all of it. Roles, focus and keyboard routing are
 * exactly what it models; what it cannot show is where the panel lands on
 * screen, which is `Menu.stories.tsx`.
 */

/** A menu, and a drawer that can be put in front of it by prop.
 *
 * By prop for the reason `Popover.test.tsx` and `Tooltip.test.tsx` both give:
 * anything that opens the drawer from inside the page moves focus first, and a
 * floating layer that has already lost focus is a different arrangement from
 * the one under test.
 */
const Fixture = ({
  onDelete,
  drawerOpen = false,
}: {
  onDelete: () => void
  drawerOpen?: boolean
}) => {
  const [open, setOpen] = useState(false)
  const [closed, setClosed] = useState(false)
  return (
    <OverlayHost>
      <Menu
        open={open}
        onOpenChange={setOpen}
        label="More actions for atlas"
        trigger={
          <button type="button" aria-label="More actions for atlas">
            ⋯
          </button>
        }
      >
        <MenuItem onSelect={() => {}}>Rename</MenuItem>
        <MenuItem tone="danger" onSelect={onDelete}>
          Delete
        </MenuItem>
      </Menu>
      {drawerOpen && !closed ? (
        <Drawer heading="Worker" label="Worker detail" onClose={() => setClosed(true)}>
          <p>drawer body</p>
        </Drawer>
      ) : null}
    </OverlayHost>
  )
}

const openMenu = async (user: ReturnType<typeof userEvent.setup>) => {
  await user.click(screen.getByRole('button', { name: 'More actions for atlas' }))
  await screen.findByRole('menu')
}

it('moves between items with the arrow keys, not with Tab', async () => {
  const user = userEvent.setup()
  render(<Fixture onDelete={() => {}} />)
  await openMenu(user)

  // Opened by a click, Radix leaves focus on the menu itself rather than on an
  // item -- measured, not assumed: the first version of this test asserted the
  // first item was focused on open and was red. So the first Down is what
  // enters the list. The disclosure this replaces put both verbs in the tab
  // order and moved between them with Tab, which means Tab also walked
  // straight out of the menu into the rest of the row with no way back.
  const [rename, remove] = screen.getAllByRole('menuitem')
  await user.keyboard('{ArrowDown}')
  expect(rename).toHaveFocus()
  await user.keyboard('{ArrowDown}')
  expect(remove).toHaveFocus()
  await user.keyboard('{ArrowUp}')
  expect(rename).toHaveFocus()
})

it('runs an item on Enter, not only on a click', async () => {
  const onDelete = vi.fn()
  const user = userEvent.setup()
  render(<Fixture onDelete={onDelete} />)
  await openMenu(user)

  await user.keyboard('{ArrowDown}{ArrowDown}{Enter}')

  // What this holds is the menu's keyboard contract, not `onSelect` over
  // `onClick`: swapping the two leaves this green, because Radix synthesises a
  // click for Enter. It goes red against a plain `<button>` in place of
  // `MenuPrimitive.Item` -- checked -- which is the disclosure this replaces,
  // where the verbs were reached by Tab and never highlighted at all.
  expect(onDelete).toHaveBeenCalledOnce()
  expect(screen.queryByRole('menu')).toBeNull()
})

it('closes on Escape and gives focus back to the trigger', async () => {
  const user = userEvent.setup()
  render(<Fixture onDelete={() => {}} />)
  await openMenu(user)

  await user.keyboard('{Escape}')

  expect(screen.queryByRole('menu')).toBeNull()
  // The close runs through the host rather than through Radix's own dismissal
  // — Escape is declined at Radix's seam — so nothing here asked for a focus
  // restore. Radix's focus scope restores on unmount whatever caused it. The
  // disclosure this replaces left focus wherever it happened to be.
  expect(screen.getByRole('button', { name: 'More actions for atlas' })).toHaveFocus()
})

it('gives Escape to the drawer in front, and leaves the menu open', async () => {
  const user = userEvent.setup()
  const { rerender } = render(<Fixture onDelete={() => {}} />)
  await openMenu(user)

  rerender(<Fixture onDelete={() => {}} drawerOpen />)
  expect(await screen.findByRole('dialog', { name: 'Worker detail' })).toBeInTheDocument()

  await user.keyboard('{Escape}')

  // The bridge, for the third primitive. Without `onEscapeKeyDown`'s
  // `preventDefault`, Radix answers this from a stack in which the drawer does
  // not appear and closes the menu as well.
  expect(screen.queryByRole('dialog', { name: 'Worker detail' })).toBeNull()
  expect(screen.getByRole('menu', { hidden: true })).toBeInTheDocument()
})

it('does not make the page inert — a menu is not modal', async () => {
  const user = userEvent.setup()
  render(<Fixture onDelete={() => {}} />)
  await openMenu(user)

  // Radix's `DropdownMenu` defaults to `modal: true`, which hides everything
  // outside the menu from assistive technology by putting `aria-hidden` on its
  // siblings, and blocks pointer events on them. `Menu` passes `modal={false}`
  // for exactly that reason: it is a second implementation of what the host
  // does with `inert`, deciding from a stack that has never heard of a
  // `Drawer`.
  //
  // **The `aria-hidden` assertion is the one that does the work.** The first
  // version of this test checked only `inert`, and it stayed green with
  // `modal={false}` deleted -- Radix's modality does not use `inert` at all, so
  // the guard was unobservable through the assertion meant to hold it. Both
  // lines are kept: `inert` catches `useLayer({modal: true})` here, and
  // `aria-hidden` catches Radix's own modality.
  const page = document.querySelector('.lay-app-root')
  expect(page).not.toHaveAttribute('inert')
  expect(page).not.toHaveAttribute('aria-hidden')
})

it('renders the menu inside the overlay host, not loose in the body', async () => {
  const user = userEvent.setup()
  render(<Fixture onDelete={() => {}} />)
  await openMenu(user)

  // What the row menu could not do before: it was `position: absolute` inside
  // its own row at `z-index: var(--z-sticky)`, so it could not leave the row
  // and tied with the modal drawer backdrop when both were open.
  expect(screen.getByRole('menu').closest('.lay-overlay-host')).not.toBeNull()
})
