import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import { expect, it } from 'vitest'

import { OverlayHost } from '../layout/OverlayHost.tsx'
import { Drawer } from './Drawer.tsx'
import { Tooltip } from './Tooltip.tsx'

/** Whether Radix's floating layer can live *under* this repository's overlay
 *  stack, rather than beside it.
 *
 * The question these tests answer is not "does a tooltip appear". It is
 * whether two dismissal stacks — Radix's `DismissableLayer` registry and
 * `OverlayHost`'s — can be reduced to one authority. Both listen for Escape,
 * Radix on `document` at capture and the host on `window` at bubble, so with
 * no bridge the Radix layer always wins the race and always answers from a
 * stack that has never heard of a `Drawer`.
 *
 * **What jsdom can and cannot show here**, since the honest boundary matters
 * more than usual with a positioning library involved. It can show *which*
 * component closed on a keypress, which is the whole question, and it can show
 * where in the DOM the content landed and whether `inert` was applied. It
 * cannot show that the tooltip is positioned anywhere near its trigger, that
 * it paints above anything, or that `--z-overlay` resolves — jsdom runs no
 * layout and resolves no stacking context. Positioning is Radix's to be
 * correct about and `Tooltip.stories.tsx` is where a person checks it.
 */

const EXPLANATION = 'Runs the gate unattended.'

/** A trigger with an explanation, and a drawer that can be put in front of it.
 *
 * **The drawer is opened by a prop rather than by a button, and that is not
 * test convenience.** A tooltip opened by *focus* cannot survive a modal
 * drawer opening at all: `Drawer` moves focus to its Close button, the trigger
 * blurs, and Radix closes on blur — correctly, and before Escape is ever
 * pressed. The first version of this test clicked a button to open the drawer
 * and failed for exactly that reason, having proved nothing about Escape.
 *
 * So the arrangement under test is the one that actually occurs: a tooltip
 * held open by the *pointer*, over which something else opens. That is not
 * hypothetical in this console — a live run pushes a worker drawer up while
 * the reader's pointer is somewhere else on the page. Driving it by prop keeps
 * the pointer where the test put it. */
const Fixture = ({ drawerOpen = false }: { drawerOpen?: boolean }) => {
  const [closed, setClosed] = useState(false)
  return (
    <OverlayHost>
      <Tooltip explanation={EXPLANATION}>why</Tooltip>
      <button type="button">something else</button>
      {drawerOpen && !closed ? (
        <Drawer title="Worker" label="Worker detail" onClose={() => setClosed(true)}>
          <p>drawer body</p>
        </Drawer>
      ) : null}
    </OverlayHost>
  )
}

it('opens the explanation when the trigger takes focus', async () => {
  const user = userEvent.setup()
  render(
    <OverlayHost>
      <Tooltip explanation={EXPLANATION}>why</Tooltip>
    </OverlayHost>,
  )

  // The point of the whole exercise: ~20 explanations in this console exist
  // only as `title`, which is announced on hover and on nothing else. Tabbing
  // to the trigger has to produce the sentence.
  expect(screen.queryByText(EXPLANATION)).toBeNull()
  await user.tab()
  expect(screen.getByRole('button', { name: 'why' })).toHaveFocus()
  expect(await screen.findByText(EXPLANATION)).toBeInTheDocument()
})

it('names the trigger with the explanation, so it is announced and not merely rendered', async () => {
  const user = userEvent.setup()
  render(
    <OverlayHost>
      <Tooltip explanation={EXPLANATION}>why</Tooltip>
    </OverlayHost>,
  )
  await user.tab()

  // Rendering the text somewhere in the document is not reaching the reader.
  // `aria-describedby` from the trigger to the content is what a screen reader
  // follows, and it is Radix's half of the bargain — asserted here because it
  // is the half that would break silently if the content stopped being
  // portalled through Radix's own `Portal`.
  const description = await screen.findByText(EXPLANATION)
  expect(screen.getByRole('button', { name: 'why' })).toHaveAttribute(
    'aria-describedby',
    description.id,
  )
})

it('does not make the page inert — a tooltip is not modal', async () => {
  const user = userEvent.setup()
  render(<Fixture />)
  await user.tab()
  await screen.findByText(EXPLANATION)

  // Registering with the host is what bridges Escape; it must not also cost
  // the reader the page. `modal: false` is the whole of the difference, and
  // this is what notices if it is ever passed as `true` to get the layer
  // "properly on top".
  expect(document.querySelector('.lay-app-root')).not.toHaveAttribute('inert')
  expect(screen.getByRole('button', { name: 'something else' })).toBeInTheDocument()
})

it('gives Escape to the drawer in front, and leaves the tooltip open', async () => {
  const user = userEvent.setup()
  const { rerender } = render(<Fixture />)

  // Hover rather than focus, for the reason argued on `Fixture`: a modal
  // drawer takes focus, and a focus-opened tooltip is already gone by then.
  await user.hover(screen.getByRole('button', { name: 'why' }))
  await screen.findByText(EXPLANATION, undefined, { timeout: 3000 })

  rerender(<Fixture drawerOpen />)
  expect(await screen.findByRole('dialog', { name: 'Worker detail' })).toBeInTheDocument()

  await user.keyboard('{Escape}')

  // One keypress, one layer. This is the assertion the bridge exists for:
  // without it Radix's `DismissableLayer` handles Escape on `document` at
  // capture, from a stack in which the drawer does not appear, and closes the
  // tooltip as well.
  expect(screen.queryByRole('dialog', { name: 'Worker detail' })).toBeNull()
  expect(screen.getByText(EXPLANATION)).toBeInTheDocument()
})

/** **This one would pass with the bridge reverted, and is kept anyway.**
 *
 * Radix's own `DismissableLayer` closes a tooltip on Escape all by itself, so
 * a green here says nothing about `useLayer`. What it does say is that the
 * bridge did not *cost* the behaviour — the obvious wrong fix for the test
 * above is to decline Escape at Radix's seam and never route it anywhere, and
 * that leaves a tooltip nothing can dismiss from the keyboard. This is the
 * assertion that fails on that fix and on no other, which is a narrow job but
 * a real one. Read it as a guard against the repair, not against the defect.
 */
it('gives Escape to the tooltip when nothing is in front of it', async () => {
  const user = userEvent.setup()
  render(<Fixture />)

  await user.tab()
  await screen.findByText(EXPLANATION)

  await user.keyboard('{Escape}')

  expect(screen.queryByText(EXPLANATION)).toBeNull()
})

it('renders the explanation inside the overlay host, not loose in the body', async () => {
  const user = userEvent.setup()
  render(<Fixture />)
  await user.tab()
  const content = await screen.findByText(EXPLANATION)

  // Portalling to the host's container is what puts the tooltip at
  // `--z-overlay` with every other layer. Radix's default is `document.body`,
  // where the only way to get it above a drawer is a `z-index` of its own —
  // which `scripts/check-deleted.mjs` fails the build over. jsdom cannot check
  // the paint order that follows from this; it can check that the content is
  // in the right box, which is the part under our control.
  expect(content.closest('.lay-overlay-host')).not.toBeNull()
})
