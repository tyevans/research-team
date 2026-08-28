import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { ReactNode } from 'react'
import { expect, it, vi } from 'vitest'

import type { Container as AppContainer } from '@app/container.ts'
import { ContainerProvider } from '@app/container-context.tsx'
import type { EventStream, EventStreamListener } from '@application/ports/event-stream.ts'
import { ProjectId } from '@domain/shared/identifier.ts'

import { OverlayHost } from '../../layout/OverlayHost.tsx'
import { StreamProvider } from '../../shell/StreamProvider.tsx'
import { QueueHeader } from './QueueHeader.tsx'

const PROJECT = ProjectId('11111111-1111-1111-1111-111111111111')

/** Delivers nothing. `SeedPanel` subscribes for seeding frames and only has to
 *  subscribe and unsubscribe without throwing; nothing here drives one. */
const fakeStream = (): EventStream => ({
  connect(_listener: EventStreamListener) {},
  disconnect() {},
})

/** `OverlayHost` innermost, matching the real tree. Without it `Overlay`
 *  renders `null` and the drawer assertions would fail for a reason that has
 *  nothing to do with this component -- the trap `AutonomyLock.test.tsx`
 *  records in the same words. */
const renderHeader = (parts: Partial<AppContainer> = {}) => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } })
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>
      <ContainerProvider
        container={
          {
            stream: fakeStream(),
            topics: { seedStatus: vi.fn().mockResolvedValue({ current: null, last: null }) },
            ...parts,
          } as unknown as AppContainer
        }
      >
        <StreamProvider>
          <OverlayHost>{children}</OverlayHost>
        </StreamProvider>
      </ContainerProvider>
    </QueryClientProvider>
  )
  return render(<QueueHeader projectId={PROJECT} shownTopicIds={[]} />, { wrapper })
}

/** Both ask routes keep a door, and this file is where that is held.
 *
 * The pane has lost one twice: deleting `CourseView` and `ResearchView` took
 * the last link to `#/p/<id>/ask`, and one plan later `facet: 'dialogue'`
 * shipped with zero `projectHref` call sites. Neither failed anything, because
 * a route that renders correctly and cannot be reached looks exactly like a
 * route that works. `App.test.tsx` asserts the same pair from the routed page;
 * this asserts it against the component, so a refactor that keeps the page
 * green by accident cannot also lose one of these.
 *
 * The `href`s are asserted rather than the presence of two links, because two
 * links to the same facet is the shape the failure would actually take when
 * the two glyphs are one mirrored component.
 *
 * **Proved red** by pointing both anchors at `facet: 'ask'`: `expected
 * '#/p/1111.../ask' to be '#/p/1111.../dialogue'`.
 */
it('keeps a door to both ask routes', () => {
  renderHeader()

  expect(screen.getByRole('link', { name: 'Ask this project' })).toHaveAttribute(
    'href',
    `#/p/${PROJECT}/ask`,
  )
  expect(screen.getByRole('link', { name: 'Be asked about this project' })).toHaveAttribute(
    'href',
    `#/p/${PROJECT}/dialogue`,
  )
})

/** S-D2: an icon with no accessible name is a control only a sighted mouse
 *  user can identify, and a tooltip is a hover affordance rather than a name.
 *
 * All three controls in one assertion because the defect is per-control and
 * the toolbar's whole content is icons -- a fourth added without a name should
 * fail here rather than pass three tests it was not added to.
 *
 * **Proved red** by dropping `aria-label` from the toolbar's button: `Unable to
 * find an accessible element with the role "button"`.
 */
it('names every glyph, and hides the glyph from the name', () => {
  renderHeader()

  const controls = [
    screen.getByRole('button', { name: 'Seed and manage this project’s topics' }),
    screen.getByRole('link', { name: 'Be asked about this project' }),
    screen.getByRole('link', { name: 'Ask this project' }),
  ]
  for (const control of controls) {
    expect(control.querySelector('svg')).toHaveAttribute('aria-hidden', 'true')
  }
})

/** The tooltip says what the name says, on the control the tab order reaches.
 *
 * Asserted by *focusing* rather than by reading `aria-describedby`, which is
 * absent until the tooltip opens -- `Tooltip` mounts its content only while
 * open, deliberately, so that "registered as a layer" and "visible" stay one
 * fact. Focus is also the interesting direction: a tooltip that opened on
 * hover and never on focus is the `title` attribute again, which is the whole
 * defect `Tooltip` was written to end.
 *
 * The three are tabbed to in order, so this also holds the toolbar's tab order
 * against its reading order -- settings, then the two ask routes.
 *
 * **Proved red** by removing the `Tooltip` around the toolbar's button:
 * `Unable to find an element with the text: Seed and manage this project’s
 * topics` (the `aria-label` is an attribute, so a name with no tooltip leaves
 * nothing to find by text).
 */
it('says the same sentence on focus as it does to a screen reader', async () => {
  const user = userEvent.setup()
  renderHeader()

  for (const name of [
    'Seed and manage this project’s topics',
    'Be asked about this project',
    'Ask this project',
  ]) {
    await user.tab()
    expect(await screen.findByText(name)).toBeInTheDocument()
  }
})

/** Seeding is behind the door rather than beside the queue, which is the
 *  change §4.3 argues for: a control touched once per project held permanent
 *  height on a rail whose job is a list.
 *
 * The `queryBy` before the click is the load-bearing half. Asserting only that
 * the form appears after the click would pass against a header that still
 * rendered the form inline and also opened a drawer over it.
 */
it('keeps seeding behind the toolbar button rather than on the rail', async () => {
  renderHeader()

  expect(screen.queryByRole('textbox', { name: /subject/i })).not.toBeInTheDocument()

  await userEvent.click(screen.getByRole('button', { name: /seed and manage/i }))

  expect(await screen.findByRole('dialog', { name: /seed and manage/i })).toBeInTheDocument()
  expect(screen.getByRole('heading', { name: 'Seeding' })).toBeInTheDocument()
  expect(screen.getByRole('textbox', { name: /subject/i })).toBeInTheDocument()
})

it('closes, and seeding goes with it', async () => {
  renderHeader()

  await userEvent.click(screen.getByRole('button', { name: /seed and manage/i }))
  await screen.findByRole('dialog', { name: /seed and manage/i })
  await userEvent.click(screen.getByRole('button', { name: 'Close' }))

  expect(screen.queryByRole('textbox', { name: /subject/i })).not.toBeInTheDocument()
})
