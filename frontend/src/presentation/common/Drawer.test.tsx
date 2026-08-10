import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import { expect, it, vi } from 'vitest'

import { Drawer } from './Drawer.tsx'

/** The keyboard contract `Drawer` exists to own, asserted before anything
 *  re-implements it.
 *
 *  `presentation/common/` had no tests at all when this file was written, and
 *  `Drawer` is the first thing the Radix migration replaces — so this is the
 *  net for that swap rather than coverage for its own sake. Every assertion
 *  here was proved red first against a deliberately broken `Drawer`: the focus
 *  effect removed, the DOM-membership check removed, the Escape branch
 *  removed, the Tab branch removed, and `stopPropagation` removed. Each failed
 *  for the reason it names and no other, which is the only thing separating
 *  these from reassurance.
 *
 *  What is deliberately *not* asserted: appearance. The class names are here
 *  as selectors because the drawer's backdrop is not reachable by role, not
 *  because the styling is part of the contract. */

/** A drawer with a page behind it, so "focus returns to where it was" and
 *  "Tab cannot walk out into the page" are answerable at all — both need
 *  something focusable outside the drawer to be wrong about. */
const Page = ({ onClose = () => {} }: { onClose?: () => void }) => (
  <>
    <button type="button">behind the drawer</button>
    <Drawer title="Worker" label="Worker detail" onClose={onClose}>
      <button type="button">first in body</button>
      <button type="button">last in body</button>
    </Drawer>
  </>
)

it('moves focus onto the close button when it opens', async () => {
  render(<Page />)

  // The close button rather than the heading: a heading would need a
  // `tabIndex={-1}` to receive focus at all, which puts a fake control in the
  // tab order. Fails with the mount effect removed — focus stays on `<body>`.
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

  // Fails with the effect's cleanup removed: focus is left on `<body>`, so a
  // screen-reader user is returned to the top of the document rather than to
  // the row they were reading.
  expect(screen.getByRole('button', { name: 'open' })).toHaveFocus()
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
  expect(focus).not.toHaveBeenCalled()
  expect(document.body).toHaveFocus()
})

it('closes on Escape', async () => {
  const user = userEvent.setup()
  const onClose = vi.fn()
  render(<Page onClose={onClose} />)

  await user.keyboard('{Escape}')

  expect(onClose).toHaveBeenCalledTimes(1)
})

/** The cycle is DOM order, and the close button sits in the header — so it is
 *  the *first* focusable in the drawer, not the last. Written down because the
 *  first draft of this file assumed the body came first and these three tests
 *  failed; the header-first order is a property of the markup that a
 *  re-implementation could silently change. */
it('wraps Tab from the last focusable element back to the close button', async () => {
  const user = userEvent.setup()
  render(<Page />)

  screen.getByRole('button', { name: 'last in body' }).focus()
  await user.tab()

  // Without the trap, Tab walks out to "behind the drawer" — the page is still
  // rendered and still focusable, so a keyboard user leaves a modal dialog
  // without closing it. Fails with the Tab branch removed.
  expect(screen.getByRole('button', { name: 'Close' })).toHaveFocus()
})

it('wraps Shift+Tab from the close button round to the last', async () => {
  const user = userEvent.setup()
  render(<Page />)

  screen.getByRole('button', { name: 'Close' }).focus()
  await user.tab({ shift: true })

  expect(screen.getByRole('button', { name: 'last in body' })).toHaveFocus()
})

it('pulls focus back in when Tab is pressed from outside it', async () => {
  const user = userEvent.setup()
  render(<Page />)

  // The page behind is inert to the reader but not to the browser: focus can
  // still be put there programmatically, and the trap has to recover rather
  // than assume focus is already inside.
  screen.getByRole('button', { name: 'behind the drawer' }).focus()
  await user.tab()

  expect(screen.getByRole('button', { name: 'Close' })).toHaveFocus()
})

it('finds focusable elements that arrived after it opened', async () => {
  const user = userEvent.setup()

  /** Why `FOCUSABLE_SELECTOR` is queried per keypress rather than cached at
   *  mount: a drawer's body can be a live transcript. This test is the one
   *  that would fail if anybody "optimised" that query into a mount-time
   *  `useMemo`. */
  const Growing = () => {
    const [grown, setGrown] = useState(false)
    return (
      <Drawer title="Transcript" label="Transcript" onClose={() => {}}>
        <button type="button" onClick={() => setGrown(true)}>
          grow
        </button>
        {grown ? (
          <button type="button" data-testid="arrived">
            arrived later
          </button>
        ) : null}
      </Drawer>
    )
  }

  render(<Growing />)
  await user.click(screen.getByRole('button', { name: 'grow' }))
  screen.getByTestId('arrived').focus()
  await user.tab()

  expect(screen.getByRole('button', { name: 'Close' })).toHaveFocus()
})

it('closes when the backdrop is clicked and stays open when its own body is', async () => {
  const user = userEvent.setup()
  const onClose = vi.fn()
  const { container } = render(<Page onClose={onClose} />)

  const backdrop = container.querySelector('.drawer-backdrop')
  expect(backdrop).not.toBeNull()

  await user.click(screen.getByRole('dialog'))
  // Fails with `stopPropagation` removed: a click anywhere in the drawer
  // bubbles to the backdrop and closes the thing being read.
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
  // two are separate props rather than one.
  const dialog = screen.getByRole('dialog', { name: 'Document: report.md' })
  expect(dialog).toHaveAttribute('aria-modal', 'true')
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
