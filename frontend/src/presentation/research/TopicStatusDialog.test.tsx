import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState, type ReactElement, type ReactNode } from 'react'
import { expect, it, vi } from 'vitest'

import type { Container as AppContainer } from '@app/container.ts'
import { ContainerProvider } from '@app/container-context.tsx'
import type { EventStream } from '@application/ports/event-stream.ts'
import type { TopicRepository } from '@application/ports/repositories.ts'
import type { TopicDetail } from '@domain/research/topic.ts'
import { ScrubPoint } from '@domain/session/scrub-point.ts'
import { ProjectId, TopicId } from '@domain/shared/identifier.ts'

import { OverlayHost } from '../layout/OverlayHost.tsx'
import { StreamProvider } from '../shell/StreamProvider.tsx'
import { TopicStatusDialog } from './TopicStatusDialog.tsx'

const PROJECT = ProjectId('11111111-1111-1111-1111-111111111111')

const aTopic = (over: Partial<TopicDetail> = {}): TopicDetail => ({
  topicId: TopicId('22222222-2222-2222-2222-222222222222'),
  question: 'Who funded the study?',
  status: 'open',
  sources: 0,
  findings: 0,
  openSubQuestions: 0,
  triggers: [],
  needsAttention: false,
  isBlocked: false,
  rationale: 'because it matters',
  scope: 'the whole project',
  subQuestions: [],
  sourceIds: [],
  findingNotes: [],
  contested: false,
  ...over,
})

/** This suite never exercises `list`/`read`/`addSubQuestion`/`resolveSubQuestion`
 *  -- only `setStatus` -- so the rest are stubs that fail loudly if that
 *  assumption stops holding, the same convention `TopicList.test.tsx` uses. */
const fakeTopics = (over: Partial<TopicRepository> = {}): TopicRepository => ({
  list: vi.fn(() => {
    throw new Error('TopicStatusDialog should never call list()')
  }),
  read: vi.fn(() => {
    throw new Error('TopicStatusDialog should never call read()')
  }),
  setStatus: vi.fn(() => {
    throw new Error('setStatus was not stubbed for this test')
  }),
  addSubQuestion: vi.fn(() => {
    throw new Error('TopicStatusDialog should never call addSubQuestion()')
  }),
  resolveSubQuestion: vi.fn(() => {
    throw new Error('TopicStatusDialog should never call resolveSubQuestion()')
  }),
  startSeed: vi.fn(() => {
    throw new Error('TopicStatusDialog should never call startSeed()')
  }),
  seedStatus: vi.fn(() => {
    throw new Error('TopicStatusDialog should never call seedStatus()')
  }),
  dispatch: vi.fn(() => {
    throw new Error('TopicStatusDialog should never call dispatch()')
  }),
  dispatchStatus: vi.fn(() => {
    throw new Error('TopicStatusDialog should never call dispatchStatus()')
  }),
  cancelDispatch: vi.fn(() => {
    throw new Error('TopicStatusDialog should never call cancelDispatch()')
  }),
  // Resolves rather than throwing: the dialog now renders `TopicDocuments`,
  // which reads this unconditionally. An empty listing keeps these tests
  // about the status form, which is what they are for.
  documents: vi.fn().mockResolvedValue({
    directory: '/topics/00-a-topic',
    sessionId: null,
    at: ScrubPoint.head(),
    documents: [],
  }),
  ...over,
})

/** A stream that connects and never delivers anything.
 *
 * Not decoration: the dialog now renders `TopicDocuments`, which subscribes to
 * dispatch frames for its own topic, and `useStream` throws outside a
 * provider. A harness without one would be testing a component the
 * application never renders. */
const quietStream: EventStream = { connect: () => {}, disconnect: () => {} }

const renderDialog = (ui: ReactElement, parts: Partial<AppContainer> = {}) => {
  const container = {
    topics: fakeTopics(),
    stream: quietStream,
    ...parts,
  } as unknown as AppContainer
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } })
  // `OverlayHost` is a precondition rather than scenery: the dialog is a
  // `Drawer` now, `Drawer` is an `Overlay`, and `Overlay` renders `null`
  // without a host in scope -- so every assertion below would fail on an empty
  // document without it. That the *application* mounts one is a separate claim
  // and is asserted where it belongs, in `App.test.tsx`, which deliberately
  // supplies no host of its own.
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>
      <ContainerProvider container={container}>
        <StreamProvider>
          <OverlayHost>{children}</OverlayHost>
        </StreamProvider>
      </ContainerProvider>
    </QueryClientProvider>
  )
  return render(ui, { wrapper })
}

it('will not submit without a justification', async () => {
  renderDialog(<TopicStatusDialog projectId={PROJECT} topic={aTopic()} onClose={vi.fn()} />)

  await userEvent.click(screen.getByRole('button', { name: /answered/i }))

  expect(screen.getByRole('button', { name: /save/i })).toBeDisabled()
})

it('will not submit a whitespace-only justification', async () => {
  renderDialog(<TopicStatusDialog projectId={PROJECT} topic={aTopic()} onClose={vi.fn()} />)

  await userEvent.click(screen.getByRole('button', { name: /answered/i }))
  await userEvent.type(screen.getByLabelText(/justification/i), '   ')

  expect(screen.getByRole('button', { name: /save/i })).toBeDisabled()
})

/** **`traps focus while it is open` was deleted rather than repaired**, and the
 *  deletion is the substance of this change. It tabbed once and asserted
 *  `activeElement !== document.body` -- which passed, and which is a claim
 *  about where focus went rather than about what is out of reach. The console
 *  shipped with the agent dock painting on top of this dialog and clickable
 *  throughout, and that assertion could not see it, because nothing about "the
 *  first Tab landed somewhere" is falsified by a reachable page behind.
 *
 *  Confinement is `inert` on `.lay-app-root` now, and the assertion that
 *  replaces it is `OverlayHost.test.tsx`'s enumeration of everything reachable
 *  in the whole document -- a negative over the page rather than a positive
 *  about one keypress, which is the shape that could have caught the defect.
 *  jsdom does not implement `inert`, so the browser half is checked in
 *  Storybook and recorded in the pull request.
 *
 *  What is kept here is only what is this dialog's own: that it takes focus,
 *  gives it back, and closes on Escape -- promises a reader is owed regardless
 *  of which file holds the listener. */
it('moves focus into itself when it opens, and back out when it closes', async () => {
  const user = userEvent.setup()

  /** The opener sits inside the tree rather than being appended to
   *  `document.body`, and close runs through the Close button rather than
   *  `unmount()`. Both changes are forced by the host owning the restore: it
   *  performs it in an effect after re-rendering without `inert`, so a test
   *  that unmounts the host has removed the thing that was going to do the
   *  restoring, and an assertion straight after `unmount()` would pass or fail
   *  for reasons unrelated to this dialog. */
  const Opener = () => {
    // Starts closed and is opened by the click below, which is not incidental:
    // `Drawer` captures where focus was at the moment its close button
    // attaches, so a dialog that is already open on the first paint captures
    // `<body>` and has nothing to give back. That is a true fact about the
    // component and a bad test setup -- this assertion is about the round
    // trip, so the round trip has to start somewhere real.
    const [open, setOpen] = useState(false)
    return (
      <>
        <button type="button" onClick={() => setOpen(true)}>
          manage
        </button>
        {open ? (
          <TopicStatusDialog projectId={PROJECT} topic={aTopic()} onClose={() => setOpen(false)} />
        ) : null}
      </>
    )
  }

  renderDialog(<Opener />)
  await user.click(screen.getByRole('button', { name: 'manage' }))

  // Fails if `Drawer` stops moving focus in: a reader would be confined to a
  // dialog with their focus still on the row behind it, which `inert` has just
  // made unreachable -- strictly worse than the trap it replaced.
  const close = screen.getByRole('button', { name: 'Close' })
  expect(close).toHaveFocus()

  await user.click(close)

  // `waitFor` because the restore lands a render later than the close, for the
  // reason `Drawer.test.tsx` sets out. Fails if `Drawer` drops `returnFocus`:
  // focus is left on `<body>`, so a screen-reader user is returned to the top
  // of the document rather than to the control they came from.
  await waitFor(() => expect(screen.getByRole('button', { name: 'manage' })).toHaveFocus())
})

it('closes on escape', async () => {
  const onClose = vi.fn()
  renderDialog(<TopicStatusDialog projectId={PROJECT} topic={aTopic()} onClose={onClose} />)

  await userEvent.keyboard('{Escape}')

  expect(onClose).toHaveBeenCalled()
})

it('does not offer the topic’s current status as a choice', () => {
  renderDialog(
    <TopicStatusDialog
      projectId={PROJECT}
      topic={aTopic({ status: 'investigating' })}
      onClose={vi.fn()}
    />,
  )

  expect(screen.queryByRole('button', { name: /^investigating$/i })).toBeNull()
  expect(screen.getByRole('button', { name: /^answered$/i })).toBeInTheDocument()
})

it('saves the chosen status with its justification, then closes', async () => {
  const onClose = vi.fn()
  const setStatus = vi
    .fn<TopicRepository['setStatus']>()
    .mockResolvedValue(aTopic({ status: 'answered' }))

  renderDialog(<TopicStatusDialog projectId={PROJECT} topic={aTopic()} onClose={onClose} />, {
    topics: fakeTopics({ setStatus }),
  })

  await userEvent.click(screen.getByRole('button', { name: /^answered$/i }))
  await userEvent.type(screen.getByLabelText(/justification/i), 'confirmed in the filing')
  await userEvent.click(screen.getByRole('button', { name: /save/i }))

  expect(setStatus).toHaveBeenCalledWith(
    PROJECT,
    aTopic().topicId,
    'answered',
    'confirmed in the filing',
  )
  await vi.waitFor(() => expect(onClose).toHaveBeenCalled())
})

it('reopens an answered topic back to investigating', async () => {
  const setStatus = vi
    .fn<TopicRepository['setStatus']>()
    .mockResolvedValue(aTopic({ status: 'investigating' }))

  renderDialog(
    <TopicStatusDialog
      projectId={PROJECT}
      topic={aTopic({ status: 'answered' })}
      onClose={vi.fn()}
    />,
    { topics: fakeTopics({ setStatus }) },
  )

  await userEvent.click(screen.getByRole('button', { name: /^investigating$/i }))
  await userEvent.type(screen.getByLabelText(/justification/i), 'new evidence surfaced')
  await userEvent.click(screen.getByRole('button', { name: /save/i }))

  expect(setStatus).toHaveBeenCalledWith(
    PROJECT,
    aTopic().topicId,
    'investigating',
    'new evidence surfaced',
  )
})
