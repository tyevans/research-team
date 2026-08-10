import { render as renderBare, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState, type ReactElement } from 'react'
import { expect, it, vi } from 'vitest'

import { OverlayHost } from '../layout/OverlayHost.tsx'
import { Drawer } from './Drawer.tsx'

/** The keyboard contract `Drawer` still owns, after the host took the rest.
 *
 *  `presentation/common/` had no tests at all when this file was written, and
 *  every assertion that remains was proved red against a deliberately broken
 *  `Drawer`: the focus effect removed, and the DOM-membership check removed.
 *  Each failed for the reason it names and no other.
 *
 *  **Four tests were deleted from this file rather than repaired, and that is
 *  the substance of the change.** They asserted the hand-rolled Tab trap —
 *  wrapping forwards from the last element, wrapping backwards from the close
 *  button, pulling focus back in from outside, and re-querying so elements
 *  that arrived later were included. All four passed, and all four were
 *  testing a *simulation* of confinement: they proved the drawer cycled the
 *  Tab key among its own children, which is not the same claim as "nothing
 *  outside this dialog is reachable". The console shipped with a dock popover
 *  painting on top of this dialog and fully clickable throughout, and not one
 *  of these tests could see it.
 *
 *  Confinement is `inert` on `.lay-app-root` now, so the assertion that
 *  replaces all four is `OverlayHost.test.tsx`'s "confines the keyboard to the
 *  modal — the page, not just the other layers", which enumerates everything
 *  reachable in the whole document and requires it to be inside the dialog.
 *  That is a negative over the document rather than a positive about one
 *  element, and it is the shape that could have caught the defect. jsdom still
 *  cannot run `inert`, so the browser half is checked in Storybook and
 *  recorded in the pull request.
 *
 *  Escape moved too: it is the host's, given to the topmost layer only, and
 *  tested there. The test here is kept because `Drawer` passes `onDismiss` and
 *  a drawer that stopped closing on Escape would be a real regression whoever
 *  owned the listener.
 *
 *  What is deliberately *not* asserted: appearance. */

/** Every drawer needs a host, because `Overlay` renders nothing without one —
 *  deliberately, so a layer whose host is missing is invisible rather than
 *  silently escaping to `document.body` outside every stacking guarantee. That
 *  makes the host a precondition of these tests rather than scenery, which is
 *  why it is in the render helper rather than in each case. */
const render = (ui: ReactElement) => renderBare(<OverlayHost>{ui}</OverlayHost>)

/** A drawer with a page behind it, so "focus returns to where it was" is
 *  answerable at all — it needs something focusable outside the drawer to be
 *  wrong about. */
const Page = ({ onClose = () => {} }: { onClose?: () => void }) => (
  <>
    <button type="button">behind the drawer</button>
    <Drawer title="Worker" label="Worker detail" onClose={onClose}>
      <button type="button">first in body</button>
      <button type="button">last in body</button>
    </Drawer>
  </>
)

it('moves focus onto the close button when it opens', () => {
  render(<Page />)

  // The close button rather than the heading: a heading would need a
  // `tabIndex={-1}` to receive focus at all, which puts a fake control in the
  // tab order. Fails with the mount effect removed — focus stays on `<body>`.
  //
  // This matters *more* under the host than it did under the trap, not less.
  // `inert` makes everything outside the dialog unreachable but moves nothing,
  // so without this effect a reader is confined to a dialog while their focus
  // sits on a row they can no longer reach or leave.
  expect(screen.getByRole('button', { name: 'Close' })).toHaveFocus()
})

it('gives focus back to the element that opened it', async () => {
  const user = userEvent.setup()

  /** The realistic shape: a row opens the drawer, and the row is still on the
   *  page underneath it. */
  const Opener = () => {
    const [open, setOpen] = useState(false)
    return (
      <>
        <button type="button" onClick={() => setOpen(true)}>
          open
        </button>
        {open ? (
          <Drawer title="Worker" label="Worker detail" onClose={() => setOpen(false)}>
            body
          </Drawer>
        ) : null}
      </>
    )
  }

  render(<Opener />)
  await user.click(screen.getByRole('button', { name: 'open' }))
  await user.click(screen.getByRole('button', { name: 'Close' }))

  // `waitFor` because the restore happens a render later than the close: the
  // host performs it, in an effect that runs once it has re-rendered without
  // `inert`. That indirection is the fix for a browser-only defect and is
  // argued in `OverlayHost`; here it just means the assertion cannot be
  // synchronous.
  //
  // Fails with the host's restore effect removed, and with `returnFocus`
  // dropped from `Drawer`'s `Overlay`: focus is left on `<body>`, so a
  // screen-reader user is returned to the top of the document rather than to
  // the row they were reading.
  await waitFor(() => expect(screen.getByRole('button', { name: 'open' })).toHaveFocus())
})

it('does not try to focus a row that was removed while it was open', async () => {
  const user = userEvent.setup()
  const opener = vi.fn<(element: HTMLButtonElement | null) => void>()

  /** The case the comment in `Drawer` names: the opener is gone by the time
   *  the drawer closes — a list refetched underneath it, say.
   *
   *  The row has to survive *into* the drawer's mount and disappear after it,
   *  which is fiddlier than it looks and is why this component has two pieces
   *  of state. An earlier version unmounted the row in the same commit that
   *  mounted the drawer; the effect runs after that commit, so
   *  `document.activeElement` was already `body`, the captured value was never
   *  the row, and the guard under test was not reached at all. That version
   *  passed with the `document.contains` check deleted. */
  const Vanishing = () => {
    const [open, setOpen] = useState(false)
    const [rowGone, setRowGone] = useState(false)
    return (
      <>
        {rowGone ? null : (
          <button type="button" ref={opener} onClick={() => setOpen(true)}>
            open
          </button>
        )}
        {open ? (
          <Drawer title="Worker" label="Worker detail" onClose={() => setOpen(false)}>
            <button type="button" onClick={() => setRowGone(true)}>
              refetch the list
            </button>
          </Drawer>
        ) : null}
      </>
    )
  }

  render(<Vanishing />)
  const row = opener.mock.calls[0]?.[0]
  expect(row).toBeInstanceOf(HTMLButtonElement)

  await user.click(screen.getByRole('button', { name: 'open' }))
  await user.click(screen.getByRole('button', { name: 'refetch the list' }))
  expect(document.contains(row!)).toBe(false)

  // Spied on *after* the row detaches, not at render: clicking a button
  // focuses it, so a spy installed earlier records that call and the assertion
  // below could never pass.
  const focus = vi.spyOn(row!, 'focus')
  await user.click(screen.getByRole('button', { name: 'Close' }))

  /** Spying on `focus` rather than asserting where focus ended up, and this is
   *  the interesting part of the file. The observable outcome is identical
   *  either way in jsdom: focusing a detached node there silently no-ops, so
   *  `document.body` keeps focus whether the guard is present or not, and the
   *  first draft of this test **passed with the `document.contains` check
   *  deleted**. It was reassurance, not a test.
   *
   *  What the guard actually buys is stated in `Drawer`'s own comment — the
   *  call "throws in some environments and silently no-ops in others" — so the
   *  behaviour under test is *that the call is not made*, and that is what is
   *  asserted. jsdom cannot show us the environment where it throws; it can
   *  show us that we never ask. */
  // A frame has to actually elapse before this means anything: the restore now
  // happens a render later, so an immediate assertion would pass even with the
  // membership guard deleted, simply because the call had not happened yet.
  await new Promise((resolve) => requestAnimationFrame(resolve))
  expect(focus).not.toHaveBeenCalled()
  expect(document.body).toHaveFocus()
})

it('closes on Escape', async () => {
  const user = userEvent.setup()
  const onClose = vi.fn()
  render(<Page onClose={onClose} />)

  await user.keyboard('{Escape}')

  // The listener is the host's now, not this component's. Kept anyway: what a
  // reader is owed is "Escape closes the drawer", and that promise should not
  // depend on which file happens to hold the listener this month. Fails if
  // `Drawer` stops passing `onDismiss`.
  expect(onClose).toHaveBeenCalledTimes(1)
})

it('closes when the backdrop is clicked and stays open when its own body is', async () => {
  const user = userEvent.setup()
  const onClose = vi.fn()
  const { container } = render(<Page onClose={onClose} />)

  // `.lay-layer-backdrop`, the layer's, not `.drawer-backdrop`, which this
  // component used to render at `z-index: 20` and no longer exists anywhere —
  // `scripts/check-deleted.mjs` fails if it returns.
  const backdrop = container.querySelector('.lay-layer-backdrop')
  expect(backdrop).not.toBeNull()

  await user.click(screen.getByRole('dialog'))
  // The `stopPropagation` this used to need is gone with the nesting that
  // required it: the backdrop is the drawer's *sibling* inside the layer
  // rather than its parent, so a click in the drawer has no backdrop to bubble
  // to. Fails if anyone reintroduces a wrapping backdrop.
  expect(onClose).not.toHaveBeenCalled()

  await user.click(backdrop!)
  expect(onClose).toHaveBeenCalledTimes(1)
})

it('names itself for a screen reader without borrowing the heading markup', () => {
  render(
    <Drawer title={<em>report.md</em>} label="Document: report.md" onClose={() => {}}>
      body
    </Drawer>,
  )

  // `title` may carry markup and `aria-label` takes a string, which is why the
  // two are separate props rather than one. The role and the name are on the
  // layer's content element now rather than on this component's `aside`; that
  // they are reachable by exactly this query is the point of asserting it
  // here, because a second `role="dialog"` nested inside the layer's would
  // announce two dialogs and this query would find the wrong one.
  const dialog = screen.getByRole('dialog', { name: 'Document: report.md' })
  expect(dialog).toHaveAttribute('aria-modal', 'true')
  expect(screen.getAllByRole('dialog')).toHaveLength(1)
  expect(screen.getByRole('heading', { name: 'report.md' })).toBeInTheDocument()
})

it('renders the caller’s actions beside the close button', () => {
  render(
    <Drawer
      title="Worker"
      label="Worker detail"
      actions={<a href="/session/1">open session</a>}
      onClose={() => {}}
    >
      body
    </Drawer>,
  )

  expect(screen.getByRole('link', { name: 'open session' })).toBeInTheDocument()
})
