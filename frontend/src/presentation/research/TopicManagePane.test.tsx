import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
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
import { TopicManagePane } from './TopicManagePane.tsx'

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
    throw new Error('TopicManagePane should never call list()')
  }),
  read: vi.fn(() => {
    throw new Error('TopicManagePane should never call read()')
  }),
  setStatus: vi.fn(() => {
    throw new Error('setStatus was not stubbed for this test')
  }),
  addSubQuestion: vi.fn(() => {
    throw new Error('TopicManagePane should never call addSubQuestion()')
  }),
  resolveSubQuestion: vi.fn(() => {
    throw new Error('TopicManagePane should never call resolveSubQuestion()')
  }),
  startSeed: vi.fn(() => {
    throw new Error('TopicManagePane should never call startSeed()')
  }),
  seedStatus: vi.fn(() => {
    throw new Error('TopicManagePane should never call seedStatus()')
  }),
  dispatch: vi.fn(() => {
    throw new Error('TopicManagePane should never call dispatch()')
  }),
  dispatchStatus: vi.fn(() => {
    throw new Error('TopicManagePane should never call dispatchStatus()')
  }),
  cancelDispatch: vi.fn(() => {
    throw new Error('TopicManagePane should never call cancelDispatch()')
  }),
  // Resolves rather than throwing: the pane renders `TopicDocuments`, which
  // reads this unconditionally. An empty listing keeps these tests
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
 * Not decoration: the pane renders `TopicDocuments`, which subscribes to
 * dispatch frames for its own topic, and `useStream` throws outside a
 * provider. A harness without one would be testing a component the
 * application never renders. */
const quietStream: EventStream = { connect: () => {}, disconnect: () => {} }

const renderPane = (ui: ReactElement, parts: Partial<AppContainer> = {}) => {
  const container = {
    topics: fakeTopics(),
    stream: quietStream,
    ...parts,
  } as unknown as AppContainer
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } })
  // `OverlayHost` is still a precondition, and for a narrower reason than it
  // was: the panel itself is a plain region now and renders without one, but
  // the save confirmation is a `Confirm`, which is a `Drawer`, which is an
  // `Overlay` that renders `null` with no host in scope. So the two tests that
  // reach Save would fail on a document with no confirmation in it while every
  // other test here passed -- which is the arrangement most likely to be read
  // as a component bug. That the *application* mounts a host is a separate
  // claim and is asserted in `App.test.tsx`, which supplies none of its own.
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

/** A page with the panel on it, and two controls that only exist because the
 *  panel is no longer modal.
 *
 * It starts closed and is opened by a click, which is not incidental: the
 * panel captures where focus was at the moment its close button attaches, so
 * one that is already open on the first paint captures `<body>` and has
 * nothing to give back. That is a true fact about the component and a bad test
 * setup -- these assertions are about the round trip, so the round trip has to
 * start somewhere real.
 *
 * The close button restores focus through the panel's own `onClose`, which is
 * what the round trip is about. */
const Opener = () => {
  const [open, setOpen] = useState(false)
  return (
    <>
      <button type="button" onClick={() => setOpen(true)}>
        manage
      </button>
      {open ? (
        <TopicManagePane projectId={PROJECT} topic={aTopic()} onClose={() => setOpen(false)} />
      ) : null}
    </>
  )
}

/** The same page with the panel's presence controlled from outside, for the
 *  one assertion that must not send a pointer event to make its point. The
 *  second button is the reader working somewhere else on a page that is live
 *  now and was `inert` before. */
const Framed = ({ open }: { open: boolean }) => (
  <>
    <button type="button">opener</button>
    <button type="button">elsewhere</button>
    {open ? <TopicManagePane projectId={PROJECT} topic={aTopic()} onClose={vi.fn()} /> : null}
  </>
)

it('will not submit without a justification', async () => {
  renderPane(<TopicManagePane projectId={PROJECT} topic={aTopic()} onClose={vi.fn()} />)

  await userEvent.click(screen.getByRole('button', { name: /answered/i }))

  expect(screen.getByRole('button', { name: /save/i })).toBeDisabled()
})

it('will not submit a whitespace-only justification', async () => {
  renderPane(<TopicManagePane projectId={PROJECT} topic={aTopic()} onClose={vi.fn()} />)

  await userEvent.click(screen.getByRole('button', { name: /answered/i }))
  await userEvent.type(screen.getByLabelText(/justification/i), '   ')

  expect(screen.getByRole('button', { name: /save/i })).toBeDisabled()
})

it('is a region beside the queue rather than a dialog over it', async () => {
  renderPane(<TopicManagePane projectId={PROJECT} topic={aTopic()} onClose={vi.fn()} />)

  const region = await screen.findByRole('region', { name: /manage who funded the study/i })
  // The whole of the demodalisation, as assistive technology sees it. Fails
  // with the change reverted, where this markup was a `Drawer`: `role=dialog`,
  // `aria-modal=true`, and `.lay-app-root` marked `inert` behind it.
  expect(region).not.toHaveAttribute('aria-modal')
  expect(screen.queryByRole('dialog')).toBeNull()
})

/** **`traps focus while it is open` was deleted rather than repaired**, and the
 *  deletion is the substance of this change. It tabbed once and asserted
 *  `activeElement !== document.body` -- which passed, and which is a claim
 *  about where focus went rather than about what is out of reach. The console
 *  shipped with the agent dock painting on top of this dialog and clickable
 *  throughout, and that assertion could not see it, because nothing about "the
 *  first Tab landed somewhere" is falsified by a reachable page behind.
 *
 *  Confinement was then `inert` on `.lay-app-root`, and **there is no
 *  confinement at all now**: this is a region of the QUEUE pane and the page
 *  around it is live. So the claim that replaced the trap has moved on again
 *  rather than been dropped -- `OverlayHost.test.tsx`'s enumeration still
 *  covers the modal case for every `Drawer` in the console, including the save
 *  confirmation this panel opens.
 *
 *  What is kept here is what is this panel's own, with both halves rewritten
 *  for a region rather than a dialog: it takes focus on open, gives it back
 *  *if the reader has not moved it elsewhere*, and closes on an Escape pressed
 *  inside it. */
it('moves focus into itself when it opens, and back out when it closes', async () => {
  const user = userEvent.setup()

  renderPane(<Opener />)
  await user.click(screen.getByRole('button', { name: 'manage' }))

  // Fails if the panel stops moving focus in. It matters more now than it did
  // as a drawer, not less: the panel renders *below* a queue that can be
  // screens long, so a keyboard reader who picked Manage out of a row's menu
  // and was left where they were would have to find it by tabbing.
  const close = screen.getByRole('button', { name: 'Close' })
  expect(close).toHaveFocus()

  await user.click(close)

  // Fails if the restore is dropped: focus is left on `<body>`, so a
  // screen-reader user is returned to the top of the document rather than to
  // the control they came from. `waitFor` because the close is a state change
  // in the opener and the restore rides on the commit that removes the node.
  await waitFor(() => expect(screen.getByRole('button', { name: 'manage' })).toHaveFocus())
})

/** The half of the focus contract that only exists because the panel is not
 *  modal, and the one assertion in this file that would have been impossible
 *  to write against the drawer -- with the page `inert`, there was nowhere for
 *  focus to be at close time except inside.
 *
 *  Reverting the containment check (restoring unconditionally, as `Drawer`
 *  does) fails here: focus is yanked off the control the reader deliberately
 *  moved it to and back onto a row they left several actions ago. */
it('leaves focus alone when it closes with the reader working elsewhere', () => {
  const { rerender } = renderPane(<Framed open={false} />)

  /** Opened and closed by re-rendering rather than by clicking, and this is
   *  the second version of this test -- the first drove both through
   *  `user.click` on a control outside the panel and **passed with the
   *  containment check removed**, which is worth recording because it is not
   *  obvious why. The restore does run and does call `focus()` on the opener;
   *  the clicked button still reports focus afterwards, so every assertion
   *  about where focus ended up was true either way and the test measured
   *  nothing. A pointer event carries a focus change of its own, so the way to
   *  ask this question is not to send one. */
  const opener = screen.getByRole('button', { name: 'opener' })
  opener.focus()
  rerender(<Framed open />)

  expect(screen.getByRole('button', { name: 'Close' })).toHaveFocus()

  // The reader tabs out and carries on with the page -- which is the whole of
  // what demodalising changed, and was impossible under `inert`.
  const elsewhere = screen.getByRole('button', { name: 'elsewhere' })
  elsewhere.focus()

  rerender(<Framed open={false} />)

  // Fails with the restore made unconditional, as `Drawer`'s is: focus is
  // yanked off the control the reader deliberately moved it to and back onto
  // one they left several actions ago. Proved that way.
  expect(elsewhere).toHaveFocus()
})

it('closes on an escape pressed inside it', async () => {
  const onClose = vi.fn()
  renderPane(<TopicManagePane projectId={PROJECT} topic={aTopic()} onClose={onClose} />)

  // Focus is already inside -- the panel put it on Close when it opened -- and
  // that is the precondition, not scenery. The listener is on the section
  // rather than on `window`, so an Escape pressed anywhere else on a page that
  // is now fully live does nothing here. Asserted below.
  await userEvent.keyboard('{Escape}')

  expect(onClose).toHaveBeenCalled()
})

/** Reverting the listener to `window` -- which is what a demodalised component
 *  most easily becomes, and what `GraphDetail` actually shipped -- passes the
 *  test above and fails this one. The defect it names is real and was filed:
 *  one keypress closing this panel and whatever else on the live page happened
 *  to be listening. */
it('ignores an escape pressed outside it', async () => {
  const onClose = vi.fn()
  renderPane(<TopicManagePane projectId={PROJECT} topic={aTopic()} onClose={onClose} />)

  const outside = document.createElement('button')
  document.body.append(outside)
  outside.focus()

  await userEvent.keyboard('{Escape}')

  expect(onClose).not.toHaveBeenCalled()
})

it('does not offer the topic’s current status as a choice', () => {
  renderPane(
    <TopicManagePane
      projectId={PROJECT}
      topic={aTopic({ status: 'investigating' })}
      onClose={vi.fn()}
    />,
  )

  expect(screen.queryByRole('button', { name: /^investigating$/i })).toBeNull()
  expect(screen.getByRole('button', { name: /^answered$/i })).toBeInTheDocument()
})

/** **Save now takes two clicks, and the second one is the change.** The panel
 *  is a region of a live page, so a stray click can reach the control that
 *  writes the project's audit trail -- which it could not while this was a
 *  modal. The commit went behind `Confirm` rather than the whole panel going
 *  back to being a dialog, which is the plan's §3.3 conclusion and is why
 *  `Confirm` is asserted by name below rather than by whatever it renders. */
it('saves the chosen status with its justification, then closes', async () => {
  const onClose = vi.fn()
  const setStatus = vi
    .fn<TopicRepository['setStatus']>()
    .mockResolvedValue(aTopic({ status: 'answered' }))

  renderPane(<TopicManagePane projectId={PROJECT} topic={aTopic()} onClose={onClose} />, {
    topics: fakeTopics({ setStatus }),
  })

  await userEvent.click(screen.getByRole('button', { name: /^answered$/i }))
  await userEvent.type(screen.getByLabelText(/justification/i), 'confirmed in the filing')
  await userEvent.click(screen.getByRole('button', { name: /save/i }))

  // Nothing has been written yet, which is the whole point of the step.
  expect(setStatus).not.toHaveBeenCalled()
  const confirm = await screen.findByRole('dialog')
  // The justification is quoted back rather than described: it is the last
  // moment anyone can read it before it becomes a fact about the project.
  expect(within(confirm).getByText(/confirmed in the filing/)).toBeInTheDocument()

  await userEvent.click(within(confirm).getByRole('button', { name: /set to answered/i }))

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

  renderPane(
    <TopicManagePane
      projectId={PROJECT}
      topic={aTopic({ status: 'answered' })}
      onClose={vi.fn()}
    />,
    { topics: fakeTopics({ setStatus }) },
  )

  await userEvent.click(screen.getByRole('button', { name: /^investigating$/i }))
  await userEvent.type(screen.getByLabelText(/justification/i), 'new evidence surfaced')
  await userEvent.click(screen.getByRole('button', { name: /save/i }))
  await userEvent.click(
    within(await screen.findByRole('dialog')).getByRole('button', {
      name: /set to investigating/i,
    }),
  )

  expect(setStatus).toHaveBeenCalledWith(
    PROJECT,
    aTopic().topicId,
    'investigating',
    'new evidence surfaced',
  )
})
