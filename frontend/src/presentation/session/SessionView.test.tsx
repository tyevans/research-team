import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { expect, it, vi } from 'vitest'

import { createSessionStore } from '@application/session/session-store.ts'
import { ContainerProvider } from '@app/container-context.tsx'
import type { Container } from '@app/container.ts'
import { ScrubPoint } from '@domain/session/scrub-point.ts'
import type { SessionId } from '@domain/shared/identifier.ts'
import { InMemoryPreferenceStore } from '@infrastructure/storage/preference-store.ts'
import { StreamProvider } from '@presentation/shell/StreamProvider.tsx'

import { SessionView } from './SessionView.tsx'

/** That the session view wires its panes to the layout system the way the
 *  stylesheets expect.
 *
 * **This file exists because of a specific hole, and the hole is worth
 * naming.** Before this migration, `SessionView.tsx` carried
 * `style={{ gridTemplateColumns: panes.gridTemplateColumns }}` on its pane
 * container, and deleting that one prop left the entire suite green: the hook
 * that computed the value was tested thoroughly and nothing checked that the
 * value reached the DOM. The migration replaces that line with half a dozen
 * props on `Split` and `Pane`, so the same hole would have been six times
 * wider. Composing `Split` and `Pane` in a test harness would not have closed
 * it -- that asserts the harness.
 *
 * So this mounts the real view. It costs a fake container of five ports and a
 * query client, which is more setup than any other test in this directory, and
 * that cost is the reason the hole existed. It buys the four facts below,
 * each of which is silent when wrong:
 *
 *   - the split's `id`, because `responsive.css` keys the entire middle
 *     arrangement on `[data-split='session']`;
 *   - each pane's `id`, because the `:has()` rules that shrink a collapsed
 *     track name them;
 *   - which panes hold their own scrollers;
 *   - which panes have a footer, because a composer inside a scrolling body
 *     leaves the screen as the conversation grows.
 *
 * **What it does not constrain:** anything about layout, as everywhere else in
 * this directory. jsdom computes no geometry and `vitest.setup.ts` says so.
 * The stub answers `false` to every media query, so the split renders in its
 * below-the-breakpoint state and writes no inline template here at all -- the
 * template and the crossing are held by `split-tracks.test.ts` and
 * `breakpoints.test.tsx`.
 */

const SESSION = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee' as SessionId

const head = {
  id: SESSION,
  projectId: null,
  startedAt: '2026-08-10T00:00:00Z',
  forkedFrom: null,
  forkedAt: null,
}

/** Only the ports the view and its store actually reach for, the way every
 *  other test in this tree does it: a fake that implemented everything would
 *  hide which dependencies this really has. */
const container = () =>
  ({
    preferences: new InMemoryPreferenceStore(),
    now: () => new Date('2026-08-10T00:00:00Z'),
    stream: { connect: vi.fn(), disconnect: vi.fn() },
    sessions: {
      read: vi.fn().mockResolvedValue({ files: [], messages: [], compactedThrough: null, ...head }),
      log: vi.fn().mockResolvedValue([]),
    },
    turns: {
      current: vi.fn().mockResolvedValue({
        running: false,
        turnIndex: null,
        startedAt: null,
        elapsedSeconds: null,
      }),
      activity: vi.fn().mockResolvedValue(null),
    },
    approvals: { pending: vi.fn().mockResolvedValue([]) },
  }) as unknown as Container

const show = () => {
  const deps = container()
  const store = createSessionStore({
    sessions: deps.sessions,
    turns: deps.turns,
    approvals: deps.approvals,
    now: deps.now,
    notify: () => {},
  })
  return render(
    <ContainerProvider container={deps}>
      <QueryClientProvider
        client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
      >
        <StreamProvider>
          <SessionView store={store} sessionId={SESSION} at={ScrubPoint.head()} path={null} />
        </StreamProvider>
      </QueryClientProvider>
    </ContainerProvider>,
  )
}

it('mounts its three panes into a split the stylesheet can find', () => {
  const { container: dom } = show()

  const split = dom.querySelector('.lay-split')
  // `data-split="session"` is not decoration. Every rule in the middle
  // arrangement -- two columns, the conversation wrapped to its own row, the
  // two `:has()` rules that shrink a collapsed track -- is scoped to it. Rename
  // it and the session view silently loses its 821-1180px layout, which is a
  // band nobody developing at 1440px ever sees.
  expect(split).toHaveAttribute('data-split', 'session')

  expect(
    [...dom.querySelectorAll('.lay-pane')].map((pane) => pane.getAttribute('data-pane')),
  ).toEqual(['timeline', 'workspace', 'conversation'])
})

it('gives the panes that hold their own scrollers a body that does not scroll', () => {
  const { container: dom } = show()

  const scrollOf = (id: string) =>
    dom.querySelector(`[data-pane='${id}'] .lay-pane-body`)?.getAttribute('data-scroll')

  // The workspace stacks a file list over a file viewer, and `Conversation`
  // renders its own scroll container because it holds a ref on it to stick to
  // the bottom. Either one inside a scrolling body is a box scrolling inside a
  // box: the outer one absorbs the wheel and the inner one is reachable only by
  // dragging its bar. These were `bodyClassName="pane-body-split"` and `raw`
  // before the migration -- two props for one shape.
  expect(scrollOf('timeline')).toBe('body')
  expect(scrollOf('workspace')).toBe('regions')
  expect(scrollOf('conversation')).toBe('regions')
})

it('pins the composer and the activity feed outside the scrolling bodies', () => {
  const { container: dom } = show()

  const footerOf = (id: string) => dom.querySelector(`[data-pane='${id}'] .lay-pane-footer`)

  // The timeline's live feed and the conversation's approvals-and-composer sit
  // below their bodies rather than at the end of them. Inside, they scroll away
  // -- for the composer that means a text box that leaves the screen as the
  // conversation grows, which is the whole reason `footer` is a slot.
  expect(footerOf('timeline')).toBeInTheDocument()
  expect(footerOf('conversation')).toBeInTheDocument()
  expect(footerOf('workspace')).toBeNull()

  expect(dom.querySelector('[data-pane="conversation"] .lay-pane-body')).not.toContainElement(
    screen.getByRole('textbox'),
  )
})
