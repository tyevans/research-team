import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, it, vi } from 'vitest'

import { createSessionStore } from '@application/session/session-store.ts'
import { ContainerProvider } from '@app/container-context.tsx'
import type { Container } from '@app/container.ts'
import { ScrubPoint } from '@domain/session/scrub-point.ts'
import type { SessionId } from '@domain/shared/identifier.ts'
import { InMemoryPreferenceStore } from '@infrastructure/storage/preference-store.ts'
import { OverlayHost } from '@presentation/layout/OverlayHost.tsx'
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
  }) as unknown as Container

const show = (over: Partial<Container> = {}) => {
  const deps: Container = { ...container(), ...over }
  const store = createSessionStore({
    sessions: deps.sessions,
    turns: deps.turns,
    now: deps.now,
    notify: () => {},
  })
  // `OverlayHost` because the end-session confirmation is a `Drawer`, and
  // `Overlay` renders `null` without a host in scope. That the application
  // mounts one is `App.test.tsx`'s claim, not this file's.
  return {
    deps,
    ...render(
      <ContainerProvider container={deps}>
        <QueryClientProvider
          client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
        >
          <StreamProvider>
            <OverlayHost>
              <SessionView store={store} sessionId={SESSION} at={ScrubPoint.head()} path={null} />
            </OverlayHost>
          </StreamProvider>
        </QueryClientProvider>
      </ContainerProvider>,
    ),
  }
}

/** A session that holds a project, which is the only state in which the
 *  end-session control is rendered at all.
 *
 *  Hands `release` back beside the port rather than leaving the caller to
 *  reach in for `sessions.release`: plucking a method off an object to assert
 *  on it is `@typescript-eslint/unbound-method`, and the rule is right here
 *  for once -- the spy is the thing under test, so it should be named. */
const holdingAProject = () => {
  const release = vi.fn().mockResolvedValue(true)
  const sessions = {
    read: vi.fn().mockResolvedValue({
      files: [],
      messages: [],
      compactedThrough: null,
      ...head,
      projectId: 'ffffffff-1111-2222-3333-444444444444',
      holdsProject: true,
    }),
    log: vi.fn().mockResolvedValue([]),
    release,
  } as unknown as Container['sessions']
  return { sessions, release }
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

/** The two facts S-D1's replacement has to carry: the question is asked, and
 *  answering "no" does nothing.
 *
 *  The second is the one worth a test. `window.confirm` returns a boolean and
 *  the call site read it inline, so "cancel does not release the session" was
 *  structurally true and untestable in the same breath -- jsdom's `confirm`
 *  throws "not implemented", which is why no test in this directory ever went
 *  near the control. Moving the question into a component splits it into two
 *  events, and a wrong wiring (confirming on dismiss, or releasing before the
 *  answer) is now a thing that can be observed rather than a thing the browser
 *  made impossible to get wrong. */
it('asks before ending a session, and does not end it if the answer is no', async () => {
  const user = userEvent.setup()
  const { sessions, release } = holdingAProject()
  show({ sessions })

  await user.click(await screen.findByRole('button', { name: 'End session' }))

  // The wording, not just the presence of a dialog: these two sentences are
  // what make an irreversible-sounding action legible, and they were the part
  // `window.confirm` could only render as one run-on paragraph.
  const dialog = screen.getByRole('dialog')
  expect(dialog).toHaveTextContent('The log stays readable and forkable.')
  expect(dialog).toHaveTextContent(/next session in it starts from this one's files/)

  await user.click(screen.getByRole('button', { name: 'Cancel' }))

  // Fails if `onConfirm` and `onCancel` are transposed, which is the whole
  // failure mode a boolean return value did not have.
  expect(release).not.toHaveBeenCalled()
})

it('ends the session once the question is answered yes', async () => {
  const user = userEvent.setup()
  const { sessions, release } = holdingAProject()
  show({ sessions })

  await user.click(await screen.findByRole('button', { name: 'End session' }))
  await user.click(screen.getByRole('button', { name: 'End the session' }))

  await waitFor(() => expect(release).toHaveBeenCalledWith(SESSION))

  // **This test survives both ways of wiring the dialog wrongly**, and saying
  // so is the point of the note. Confirming on dismiss, and releasing on the
  // control with the dialog as decoration in front of it, were each tried
  // deliberately: this stayed green through both, because both still reach
  // `release` on a path that goes through the confirm button. It is the
  // *cancel* test above that fails, and it failed on both.
  //
  // Kept anyway, because the pair is the claim -- one asserts the release
  // happens, the other that nothing else makes it happen -- and an ending that
  // no test performs end to end is an ending nobody has run.
})
