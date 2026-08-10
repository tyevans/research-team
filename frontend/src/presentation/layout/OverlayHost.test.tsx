import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import { expect, it, vi } from 'vitest'

import { Overlay, OverlayHost } from './OverlayHost.tsx'

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
