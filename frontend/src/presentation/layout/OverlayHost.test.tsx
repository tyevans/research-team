import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useRef, useState } from 'react'
import { expect, it, vi } from 'vitest'

import { Overlay, OverlayHost, useEscape } from './OverlayHost.tsx'

/** The stacking contract, and the specific inversion it exists to make
 *  unrepresentable.
 *
 * **What these tests constrain.** DOM order, the `inert` and `aria-hidden`
 * attributes, and which layer receives Escape. All three are structure, which
 * is the one part of layout jsdom can see honestly.
 *
 * **What they do not, and it is the important half.** They cannot show that a
 * later layer *paints* above an earlier one — that is `z-index` and stacking
 * contexts, and jsdom resolves neither. They cannot show that `inert` actually
 * blocks a click or a Tab, because jsdom does not implement the attribute's
 * behaviour, only its presence. So these tests prove the host *asks* for the
 * right arrangement and cannot prove the browser delivers it. The paint order
 * and the inertness need a person with a browser; they are listed as such in
 * the pull request rather than implied to be covered.
 *
 * Proved red by: rendering layers in reverse registration order, dropping the
 * `index > mine` condition so a modal made itself inert, removing the
 * `inert` attribute, and dismissing every layer on Escape instead of the top
 * one.
 */

/** Everything in the document a keyboard could actually land on.
 *
 * Written out rather than taken from a library, and it has to compute
 * reachability itself: jsdom implements the *presence* of `inert` and none of
 * its behaviour, so `querySelectorAll` over a tabbable selector cheerfully
 * returns elements no browser would let you reach. Walking the ancestor chain
 * for `inert`, `aria-hidden` and `hidden` is what a browser does, modelled
 * here because the alternative is asserting nothing.
 *
 * This is the assertion that was missing. The previous tests asked whether a
 * particular layer *had* `inert` — a positive, about one element, which was
 * true while a modal left the entire shell tabbable. The negative over the
 * whole document is the only shape that could have caught it: a modal's
 * promise is about everything it is not.
 */
const CAN_FOCUS = 'a[href], button, input, select, textarea, [tabindex]:not([tabindex="-1"])'

const reachable = () =>
  Array.from(document.querySelectorAll<HTMLElement>(CAN_FOCUS)).filter((element) => {
    if (element.hasAttribute('disabled')) return false
    for (let node: HTMLElement | null = element; node; node = node.parentElement) {
      if (node.hasAttribute('inert')) return false
      if (node.getAttribute('aria-hidden') === 'true') return false
      if (node.hasAttribute('hidden')) return false
    }
    return true
  })

const Dock = ({ children }: { children?: React.ReactNode }) => (
  <Overlay label="Agents">
    <button type="button">watch a session</button>
    {children}
  </Overlay>
)

it('paints later layers after earlier ones, in the DOM', () => {
  render(
    <OverlayHost>
      <Overlay label="first">
        <p>first</p>
      </Overlay>
      <Overlay label="second">
        <p>second</p>
      </Overlay>
    </OverlayHost>,
  )

  // Order in the host is mount order, and every layer shares one z-index, so
  // this ordering *is* the paint order in a browser. There is no number for a
  // second overlay to get wrong, which is the entire mechanism.
  //
  // **This assertion survived every deliberate break tried against this file,
  // including reversing the registration order**, and it is kept anyway with
  // that stated. It holds because `createPortal` appends in React's render
  // order rather than because `OverlayHost` arranges anything — so it is a
  // characterization of the property the whole design rests on, not a test of
  // code in this repository. It would go red if someone rendered layers from
  // the registry array instead of in place, which is a plausible refactor and
  // the reason to keep it. Read it as documentation with an assertion
  // attached.
  const names = screen.getAllByRole('dialog').map((node) => node.getAttribute('aria-label'))
  expect(names).toEqual(['first', 'second'])
})

it('makes the dock inert while a modal drawer is open, and not before', async () => {
  const user = userEvent.setup()

  /** The exact arrangement that is broken on `main`: a dock popover, and a
   *  drawer opened from it. Today the popover is `z-index: 40` and the
   *  drawer's `aria-modal` backdrop is `z-index: 20`, so the popover paints
   *  on top of the modal, stays clickable, and has switched off its own
   *  Escape handling because its comment asserts the drawer is in front. */
  const DockAndDrawer = () => {
    const [watching, setWatching] = useState(false)
    return (
      <OverlayHost>
        <Dock>
          <button type="button" onClick={() => setWatching(true)}>
            open the feed
          </button>
        </Dock>
        {watching ? (
          <Overlay label="Watching" modal onDismiss={() => setWatching(false)}>
            <p>the feed</p>
          </Overlay>
        ) : null}
      </OverlayHost>
    )
  }

  render(<DockAndDrawer />)
  const dock = screen.getByRole('dialog', { name: 'Agents' }).closest('.lay-layer')
  expect(dock).not.toHaveAttribute('inert')

  await user.click(screen.getByRole('button', { name: 'open the feed' }))

  // The dock is beneath a modal, so it is inert and hidden from assistive
  // technology. On `main` it is neither, which is what makes a modal dialog
  // there not actually modal.
  expect(dock).toHaveAttribute('inert')
  expect(dock).toHaveAttribute('aria-hidden', 'true')

  // And the modal does not disable itself, which is what `index > mine`
  // rather than `some(modal)` buys.
  const drawer = screen.getByRole('dialog', { name: 'Watching' }).closest('.lay-layer')
  expect(drawer).not.toHaveAttribute('inert')
})

it('leaves a layer stacked on top of a modal usable', () => {
  // A confirm opened from a drawer. If a modal made everything else inert
  // rather than everything *below* it, this is the case that would break, and
  // it is a real one — `Confirm` is built on `Drawer`.
  render(
    <OverlayHost>
      <Overlay label="Drawer" modal>
        <p>drawer</p>
      </Overlay>
      <Overlay label="Confirm" modal>
        <p>are you sure</p>
      </Overlay>
    </OverlayHost>,
  )

  expect(screen.getByRole('dialog', { name: 'Confirm' }).closest('.lay-layer')).not.toHaveAttribute(
    'inert',
  )

  // `hidden: true` is required to find the drawer at all, and that is the
  // assertion rather than an inconvenience: testing-library excludes
  // `aria-hidden` subtrees from role queries exactly as a screen reader
  // excludes them from its tree. The first version of this test used a plain
  // `getByRole` and failed with "unable to find" — which was the host working.
  expect(screen.queryByRole('dialog', { name: 'Drawer' })).toBeNull()
  expect(
    screen.getByRole('dialog', { name: 'Drawer', hidden: true }).closest('.lay-layer'),
  ).toHaveAttribute('inert')
})

it('confines the keyboard to the modal — the page, not just the other layers', async () => {
  const user = userEvent.setup()

  /** The story this reproduces is `DockThenDrawer`, and this is the defect a
   *  browser found and jsdom's earlier assertions did not: with the modal
   *  open, the pointer was blocked by the backdrop and Tab was not. The
   *  chrome's button had no `inert` and no `aria-hidden` anywhere in its
   *  ancestor chain, so a keyboard user tabbed out of an `aria-modal` dialog
   *  into page chrome, and a screen-reader user was never confined. */
  const Page = () => {
    const [watching, setWatching] = useState(false)
    return (
      <OverlayHost>
        <header>
          <button type="button">agents</button>
        </header>
        <main>
          <button type="button">a row on the page</button>
        </main>
        <Overlay label="Agents">
          <button type="button" onClick={() => setWatching(true)}>
            open the feed
          </button>
        </Overlay>
        {watching ? (
          <Overlay label="Watching" modal onDismiss={() => setWatching(false)}>
            <button type="button">Close</button>
          </Overlay>
        ) : null}
      </OverlayHost>
    )
  }

  render(<Page />)

  // Before the modal: everything is reachable, including both layers. A host
  // that confined the keyboard all the time would be a worse bug than the one
  // being fixed, so the negative is bounded from both ends.
  expect(reachable().map((node) => node.textContent)).toEqual([
    'agents',
    'a row on the page',
    'open the feed',
  ])

  await user.click(screen.getByRole('button', { name: 'open the feed' }))

  // With it: exactly the modal's own controls, and nothing else in the entire
  // document. `agents` was the element that proved this wrong in a browser.
  expect(reachable().map((node) => node.textContent)).toEqual(['Close'])

  const modal = screen.getByRole('dialog', { name: 'Watching' })
  for (const node of reachable()) expect(modal.contains(node)).toBe(true)

  // `aria-hidden` asserted separately, because `reachable()` stops at the
  // first `inert` it finds and so cannot tell the two apart — dropping
  // `aria-hidden` left every assertion above green. In a browser `inert`
  // already removes the subtree from the accessibility tree, so this is
  // belt-and-braces for anything that implements one and not the other; it is
  // claimed in the component, so it is checked here rather than trusted.
  expect(document.querySelector('.lay-app-root')).toHaveAttribute('aria-hidden', 'true')
})

it('confines the keyboard to the topmost modal when modals are nested', async () => {
  /** `TwoDeep`, checked for the same class of gap rather than assumed to
   *  inherit the fix. It does not inherit it for free: the page wrapper is
   *  marked by "is any layer modal", while a layer is marked by "is a *later*
   *  layer modal" — two different rules, and the nested case is where they
   *  could disagree. */
  render(
    <OverlayHost>
      <main>
        <button type="button">a row on the page</button>
      </main>
      <Overlay label="Session detail" modal>
        <button type="button">a control in the drawer</button>
      </Overlay>
      <Overlay label="Delete this session?" modal>
        <button type="button">Cancel</button>
      </Overlay>
    </OverlayHost>,
  )

  expect(reachable().map((node) => node.textContent)).toEqual(['Cancel'])

  const confirm = screen.getByRole('dialog', { name: 'Delete this session?' })
  for (const node of reachable()) expect(confirm.contains(node)).toBe(true)
})

it('leaves the page reachable when the only open layers are not modal', () => {
  // The bound on the other side. A popover takes nothing away from the page,
  // and a host that disabled the shell for every layer would break the dock,
  // the row menu and every tooltip at once.
  render(
    <OverlayHost>
      <main>
        <button type="button">a row on the page</button>
      </main>
      <Overlay label="Row actions">
        <button type="button">fork from here</button>
      </Overlay>
    </OverlayHost>,
  )

  expect(reachable().map((node) => node.textContent)).toEqual([
    'a row on the page',
    'fork from here',
  ])
})

it('decides the menu-against-modal tie that nothing decides today', () => {
  // Measured in the running console: `.menu > .disc-body` and
  // `.drawer-backdrop` are both `z-index: 20`, so a row menu against an open
  // dialog is settled by DOM order with nothing anywhere stating which should
  // win. It is benign only because one is fixed and one is absolute inside a
  // row -- a property nobody wrote down and nothing enforces.
  //
  // Here the answer is stated: the menu opened first, so it is beneath the
  // modal and inert. There is no tie because there is no number.
  render(
    <OverlayHost>
      <Overlay label="Row actions">
        <button type="button">fork from here</button>
      </Overlay>
      <Overlay label="Delete this session?" modal>
        <p>are you sure</p>
      </Overlay>
    </OverlayHost>,
  )

  expect(
    screen.getByRole('dialog', { name: 'Row actions', hidden: true }).closest('.lay-layer'),
  ).toHaveAttribute('inert')
})

it('gives Escape to the topmost layer only', async () => {
  const user = userEvent.setup()
  const dismissDock = vi.fn()
  const dismissDrawer = vi.fn()

  render(
    <OverlayHost>
      <Overlay label="Agents" onDismiss={dismissDock}>
        <p>dock</p>
      </Overlay>
      <Overlay label="Watching" modal onDismiss={dismissDrawer}>
        <p>feed</p>
      </Overlay>
    </OverlayHost>,
  )

  await user.keyboard('{Escape}')

  // One keypress, one dismissal. Two overlays both listening on `window` is
  // why the session timeline has to call `stopPropagation` "so one Escape does
  // not fold twice", and why the dock had to reason about whether a drawer was
  // in front. Neither is necessary when a single owner decides.
  expect(dismissDrawer).toHaveBeenCalledTimes(1)
  expect(dismissDock).not.toHaveBeenCalled()
})

it('gives focus back only once the last modal has gone', async () => {
  const user = userEvent.setup()

  /** A confirm opened from a drawer, closed one at a time — a stack unwinding
   *  one step per close, which is the case a "restore when the last modal
   *  leaves" rule gets wrong.
   *
   *  The middle assertion is the interesting one: closing the confirm returns
   *  focus to the control *inside the drawer* that opened it, not to the row
   *  on the page. The drawer is still up, so the page is still inert and the
   *  row is unreachable — handing focus there would strand the reader
   *  somewhere no key could leave.
   *
   *  jsdom cannot show the browser half of this, that focusing into an inert
   *  subtree is refused; that is exactly why the restore lives in the host at
   *  all, and it is checked in a browser through `FocusReturnsToTheRow`. What
   *  this asserts is the ordering the fix depends on.
   *
   *  Proved red by removing the host's restore effect, and by dropping
   *  `returnFocus` from either `Overlay`. */
  const Page = () => {
    const [drawer, setDrawer] = useState(false)
    const [confirm, setConfirm] = useState(false)
    const row = useRef<Element | null>(null)
    const inDrawer = useRef<Element | null>(null)
    return (
      <OverlayHost>
        <button
          type="button"
          onClick={(event) => {
            row.current = event.currentTarget
            setDrawer(true)
          }}
        >
          the row
        </button>
        {drawer ? (
          <Overlay label="Drawer" modal onDismiss={() => setDrawer(false)} returnFocus={row}>
            <button
              type="button"
              onClick={(event) => {
                inDrawer.current = event.currentTarget
                setConfirm(true)
              }}
            >
              delete
            </button>
          </Overlay>
        ) : null}
        {confirm ? (
          <Overlay label="Confirm" modal onDismiss={() => setConfirm(false)} returnFocus={inDrawer}>
            <button type="button">Cancel</button>
          </Overlay>
        ) : null}
      </OverlayHost>
    )
  }

  render(<Page />)
  // Held as a node rather than re-queried, because while a modal is open the
  // page carries `aria-hidden` and `getByRole` correctly refuses to see it —
  // which is the host working, and is asserted elsewhere in this file.
  const theRow = screen.getByRole('button', { name: 'the row' })
  await user.click(theRow)
  const theDeleteButton = screen.getByRole('button', { name: 'delete' })
  await user.click(theDeleteButton)

  // Close the confirm: focus goes back one level, into the drawer, which is
  // live. Not to the row, which is behind an inert page.
  await user.keyboard('{Escape}')
  await waitFor(() => expect(theDeleteButton).toHaveFocus())
  expect(theRow).not.toHaveFocus()

  // Close the drawer: now the page is live and focus goes back to the row.
  await user.keyboard('{Escape}')
  await waitFor(() => expect(theRow).toHaveFocus())
})

it('renders through a portal rather than in place', () => {
  // Worth asserting because it is the property everything above rests on and
  // nothing in this codebase does today: no module calls `createPortal`, so
  // every existing overlay escapes its parent only through `position: fixed`
  // and is at the mercy of any ancestor that creates a stacking context.
  const { container } = render(
    <OverlayHost>
      <div className="page">
        <Overlay label="Menu">
          <p>menu</p>
        </Overlay>
      </div>
    </OverlayHost>,
  )

  expect(container.querySelector('.page .lay-layer')).toBeNull()
  expect(container.querySelector('.lay-overlay-host .lay-layer')).not.toBeNull()
})

it('renders nothing when there is no host, instead of escaping to the body', () => {
  // The failure mode this avoids is a layer that silently portals to
  // `document.body` when its host is missing: it would look fine in a story
  // and would sit outside every stacking guarantee in production.
  render(
    <Overlay label="orphan">
      <p>orphan</p>
    </Overlay>,
  )

  expect(screen.queryByRole('dialog')).toBeNull()
})

/** A panel that closes on Escape without being an overlay: laid out in the
 *  page, not portalled, not floating, not confined. `GraphDetail` is the real
 *  one -- it sits beside the graph canvas so it can be read *while* the canvas
 *  is worked, which is the whole point of it. */
const Panel = ({ onClose }: { onClose: () => void }) => {
  useEscape(onClose)
  return <p>a panel beside the canvas</p>
}

it('gives Escape to the topmost layer even when something below is not an overlay', async () => {
  const user = userEvent.setup()
  const closePanel = vi.fn()
  const closePopover = vi.fn()

  /** The popover actually unmounts when dismissed. A spy alone leaves it
   *  registered and therefore still topmost, so the second Escape below would
   *  go to it again -- which says nothing about the stack and everything about
   *  the harness. */
  const Console = () => {
    const [dockOpen, setDockOpen] = useState(true)
    return (
      <OverlayHost>
        <Panel onClose={closePanel} />
        {dockOpen ? (
          <Overlay
            label="Agent dock"
            onDismiss={() => {
              closePopover()
              setDockOpen(false)
            }}
          >
            dock
          </Overlay>
        ) : null}
      </OverlayHost>
    )
  }

  render(<Console />)

  await user.keyboard('{Escape}')

  // **The defect this closes.** `GraphDetail` listened on `window`, which is
  // outside the host's arrangement entirely, so one Escape closed the popover
  // *and* the panel behind it -- and `inert` does not help, because it blocks
  // focus and pointers and says nothing about keydown listeners bound to
  // `window`. Fails if `useEscape` goes back to a `window` listener: both
  // spies are called.
  expect(closePopover).toHaveBeenCalledTimes(1)
  expect(closePanel).not.toHaveBeenCalled()

  // And the panel is still reachable once the thing in front of it has gone,
  // which is what makes it a stack rather than a mute.
  await user.keyboard('{Escape}')
  expect(closePanel).toHaveBeenCalledTimes(1)
})

it('does nothing on Escape when a bare participant has no host', async () => {
  const user = userEvent.setup()
  const onClose = vi.fn()

  render(<Panel onClose={onClose} />)
  await user.keyboard('{Escape}')

  // The same contract `Overlay` has -- "renders nothing when there is no host,
  // instead of escaping to the body" -- expressed for something that renders
  // no layer at all. A hostless participant declining to act is what makes a
  // missing host a visible failure in one place rather than a silent
  // free-for-all on `window`.
  expect(onClose).not.toHaveBeenCalled()
  expect(screen.getByText('a panel beside the canvas')).toBeInTheDocument()
})
