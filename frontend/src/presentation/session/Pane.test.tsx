import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { ComponentProps } from 'react'
import { describe, expect, it } from 'vitest'

import type { Container } from '@app/container.ts'
import { ContainerProvider } from '@app/container-context.tsx'
import { InMemoryPreferenceStore } from '@infrastructure/storage/preference-store.ts'

import { Pane } from './Pane.tsx'
import { usePanes } from './use-panes.ts'

/** Characterization tests: what the session panes do today, written so a
 *  replacement has something to fail against rather than something to agree
 *  with. Nothing here is a statement that the current behaviour is right —
 *  `announces its toggle as a glyph` asserts a defect on purpose, and says so.
 *
 *  **The boundary these tests cannot cross.** `vitest.setup.ts` stubs
 *  `matchMedia`, `ResizeObserver` and `getBoundingClientRect` because "real
 *  layout is Playwright's job, not jsdom's", and there is no Playwright in this
 *  repository. So every assertion below is about *markup* — which class names,
 *  attributes and DOM structure a pane produces. None of it observes a width, a
 *  height, a track, or whether anything is actually visible. What that buys is
 *  still real: `panes.css` and `responsive.css` select on exactly these class
 *  names, so a change that stops emitting `collapsed` or `pane-timeline`
 *  silently disables a stylesheet rule, and these tests catch that. What it
 *  does not buy is any evidence the rules themselves still work.
 */

/** Only the port these components reach for, the way `use-panes.test.tsx` and
 *  `RailPane.test.tsx` both do it: a fake that implemented everything would
 *  hide which dependency this really has. */
const containerWith = (preferences: InMemoryPreferenceStore): Container =>
  ({ preferences }) as unknown as Container

/** One pane, driven by the real `usePanes` rather than a stub of it, because
 *  the collapse path runs through the hook and half of what is being
 *  characterized is the two of them together. */
/** Spread rather than forwarded one by one: `exactOptionalPropertyTypes` makes
 *  `bodyClassName={undefined}` a different thing from omitting it, and the
 *  omission is what each case here is actually testing. */
type Extras = Pick<ComponentProps<typeof Pane>, 'footer' | 'raw' | 'bodyClassName'>

const OnePane = (extras: Extras) => {
  const panes = usePanes()
  return (
    <Pane
      name="timeline"
      title="Event log"
      label="Event timeline"
      meta="12 events"
      panes={panes}
      {...extras}
    >
      <p>the log</p>
    </Pane>
  )
}

const show = (extras: Extras = {}) =>
  render(
    <ContainerProvider container={containerWith(new InMemoryPreferenceStore())}>
      <OnePane {...extras} />
    </ContainerProvider>,
  )

const toggle = () => screen.getByRole('button')

describe('Pane', () => {
  it('carries the class names the stylesheets fold and reflow on', () => {
    const { container } = show()
    const pane = container.querySelector('section')

    // `.pane` is `panes.css`'s handle for the whole flex column; `.pane-timeline`
    // is what `responsive.css:28`'s `.panes:has(.pane-timeline.collapsed)` needs
    // in order to shrink the right track in the two-column layout. Dropping
    // either is invisible in the DOM and silently disables a stylesheet rule.
    expect(pane).toHaveClass('pane', 'pane-timeline')
    expect(pane).toHaveAttribute('data-pane', 'timeline')
    expect(pane).toHaveAccessibleName('Event timeline')
  })

  it('adds the collapsed class, and keeps the head reachable', async () => {
    const { container } = show()
    const pane = container.querySelector('section')
    expect(pane).not.toHaveClass('collapsed')

    await userEvent.click(toggle())

    // The other half of the `:has()` selector above, and the whole of
    // `.pane.collapsed > *:not(.pane-head) { display: none }`.
    expect(pane).toHaveClass('collapsed')
    expect(toggle()).toHaveAttribute('aria-expanded', 'false')
    // The head survives the fold, which is the only way back.
    expect(screen.getByRole('heading', { name: 'Event log' })).toBeInTheDocument()
  })

  it('keeps a collapsed pane’s contents mounted', async () => {
    show()
    await userEvent.click(toggle())

    // The session pane hides its body in CSS; `RailPane` unmounts its body
    // instead, and says why -- a virtualizer measuring a zero-height scroller.
    // Two fold semantics under one `.pane` class name. This asserts the session
    // arm so a replacement that unmounts everywhere has to choose that
    // deliberately: `ActivityFeed` and `Timeline` are still subscribed and still
    // rendering here, which is the cost of the current behaviour and is also
    // what stops a folded log from losing its scroll position.
    expect(screen.getByText('the log')).toBeInTheDocument()
  })

  it('renders a footer beside the body rather than inside it', () => {
    const { container } = show({ footer: <p>the composer</p> })
    const body = container.querySelector('.pane-body')
    const footer = screen.getByText('the composer')

    // Load-bearing, and only in the stylesheet: `.pane.collapsed >
    // *:not(.pane-head)` reaches direct children, so a footer nested inside
    // `.pane-body` would still be folded away with it -- but a footer moved
    // *into* the body would also start scrolling with the conversation instead
    // of staying pinned under it. The structure is the whole contract.
    expect(body).not.toContainElement(footer)
    expect(footer.parentElement).toHaveClass('pane')
  })

  it('leaves a child that owns its own scroll container unwrapped', () => {
    const { container } = show({ raw: true })

    // `raw` is how the conversation avoids a scroll container inside a scroll
    // container: it renders its own `.pane-body` so it can stick to the bottom.
    // A second one here would leave the sticky-bottom behaviour measuring the
    // wrong box.
    expect(container.querySelector('.pane-body')).toBeNull()
    expect(screen.getByText('the log')).toBeInTheDocument()
  })

  it('passes a body class through to the body', () => {
    const { container } = show({ bodyClassName: 'pane-body-split' })

    // The workspace pane's file list and file view are two stacked regions, and
    // `.pane-body-split` is what makes the body a flex column instead of one
    // scroller. Reverting this prop makes the file view scroll with the list.
    expect(container.querySelector('.pane-body')).toHaveClass('pane-body', 'pane-body-split')
  })

  it('announces its toggle as a glyph', async () => {
    show()

    // **This asserts a defect on purpose.** S-D2: the button's only child is
    // `◂`/`▸`, so that is its accessible name; the sentence a screen-reader user
    // needs is in `title`, which is not reliably announced.
    // `AgentWidget.tsx:136-138` names this bug and declines to spread it, and
    // `RailPane.tsx:64-67` fixes the same bug in the research rail with an
    // `aria-label` -- so the console currently answers this question two
    // different ways under one class name.
    //
    // It is characterized rather than fixed because this branch is the net, not
    // the migration. When the fix lands, **update this test to assert the
    // sentence** rather than deleting it: a `VisuallyHidden` label that is
    // silently dropped later would leave nothing failing.
    expect(toggle()).toHaveAccessibleName('◂')
    expect(toggle()).toHaveAttribute('title', 'Collapse this pane')

    await userEvent.click(toggle())
    expect(toggle()).toHaveAccessibleName('▸')
    expect(toggle()).toHaveAttribute('title', 'Expand this pane')
  })
})
