import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { ReactElement, ReactNode } from 'react'
import { expect, it, vi } from 'vitest'

import type { Container as AppContainer } from '@app/container.ts'
import { ContainerProvider } from '@app/container-context.tsx'
import type { EventStream, EventStreamListener } from '@application/ports/event-stream.ts'
import type { MediaProposalRepository } from '@application/ports/repositories.ts'
import type { MediaProposal, MediaProposalGroup } from '@domain/research/media-proposal.ts'
import { ProjectId } from '@domain/shared/identifier.ts'

import { StreamProvider } from '../shell/StreamProvider.tsx'
import { MediaProposalPane } from './MediaProposalPane.tsx'

const project = ProjectId('11111111-1111-1111-1111-111111111111')

const proposal = (over: Partial<MediaProposal> = {}): MediaProposal => ({
  proposalId: 'p1',
  needId: 'n1',
  topicId: 't1',
  pageUrl: 'https://example.com/page',
  assetUrl: 'https://example.com/pic.jpg',
  thumbnailUrl: null,
  kind: 'image',
  title: 'A picture of the thing',
  reason: 'Illustrates the main claim of the topic',
  query: 'the thing',
  status: 'proposed',
  note: '',
  sourceId: null,
  error: null,
  ...over,
})

const group = (over: Partial<MediaProposalGroup> = {}): MediaProposalGroup => ({
  needId: 'n1',
  needDescription: 'A picture showing what the device looked like',
  proposals: [proposal()],
  ...over,
})

/** Every method throws until a test stubs it -- matching
 *  `DocumentManagePane.test.tsx`'s own `fakeDocuments`, so a test that calls
 *  a method it did not mean to fails loudly instead of quietly resolving
 *  `undefined`. */
const fakeMediaProposals = (
  over: Partial<MediaProposalRepository> = {},
): MediaProposalRepository => ({
  list: vi.fn(() => {
    throw new Error('list was not stubbed for this test')
  }),
  accept: vi.fn(() => {
    throw new Error('accept was not stubbed for this test')
  }),
  reject: vi.fn(() => {
    throw new Error('reject was not stubbed for this test')
  }),
  ignore: vi.fn(() => {
    throw new Error('ignore was not stubbed for this test')
  }),
  ignored: vi.fn<MediaProposalRepository['ignored']>().mockResolvedValue({
    assets: [],
    hosts: [],
  }),
  unignore: vi.fn(() => {
    throw new Error('unignore was not stubbed for this test')
  }),
  ...over,
})

/** Mirrors `DocumentList.test.tsx`'s fake stream: a `connect` that captures
 *  the listener `StreamProvider` hands it, so a test can push a frame through
 *  the real fan-out rather than calling a prop the pane does not have. */
const fakeStream = () => {
  let listener: EventStreamListener | null = null
  const stream: EventStream = {
    connect: (received) => {
      listener = received
    },
    disconnect: () => {
      listener = null
    },
  }
  return {
    stream,
    pushMedia: (projectId: string = project, change = 'MediaProposalStored') =>
      act(() => {
        listener?.onFrame({ kind: 'media', projectId, change })
      }),
  }
}

/** `StreamProvider` is not decoration: the pane subscribes to the feed to
 *  replace its old poll, and a harness without one would exercise a
 *  component the application never renders. */
const wrapperFor = (
  mediaProposals: MediaProposalRepository,
  stream: EventStream = fakeStream().stream,
): (({ children }: { children: ReactNode }) => ReactElement) => {
  const container = { mediaProposals, stream } as unknown as AppContainer
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } })
  return ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>
      <ContainerProvider container={container}>
        <StreamProvider>{children}</StreamProvider>
      </ContainerProvider>
    </QueryClientProvider>
  )
}

it('groups proposals under their need’s own sentence', async () => {
  const mediaProposals = fakeMediaProposals({
    list: vi.fn().mockResolvedValue([
      group({
        needId: 'n1',
        needDescription: 'A picture showing what the device looked like',
        proposals: [proposal({ proposalId: 'p1', title: 'Device photo' })],
      }),
    ]),
  })

  render(<MediaProposalPane projectId={project} />, { wrapper: wrapperFor(mediaProposals) })

  expect(
    await screen.findByText('A picture showing what the device looked like'),
  ).toBeInTheDocument()
  expect(screen.getByText('Device photo')).toBeInTheDocument()
})

it('renders a typed placeholder rather than the full asset when there is no thumbnail', async () => {
  // Measured 2026-08-15: thumbnail_url was absent on 46 of 262 image
  // results. Falling back to assetUrl would put a full-resolution image on
  // the page, which this test pins against.
  const mediaProposals = fakeMediaProposals({
    list: vi
      .fn()
      .mockResolvedValue([group({ proposals: [proposal({ thumbnailUrl: null, kind: 'image' })] })]),
  })

  render(<MediaProposalPane projectId={project} />, { wrapper: wrapperFor(mediaProposals) })

  await screen.findByText('A picture of the thing')
  expect(screen.queryByRole('img')).not.toBeInTheDocument()
  expect(screen.getByText('image')).toBeInTheDocument()
})

it('keeps an accepted card in a working state rather than showing nothing', async () => {
  // BACKLOG.md B94: a media row with no state at all, for the minutes an
  // hour of audio takes, is the defect this test exists to keep out.
  const mediaProposals = fakeMediaProposals({
    list: vi.fn().mockResolvedValue([group({ proposals: [proposal({ status: 'accepted' })] })]),
  })

  render(<MediaProposalPane projectId={project} />, { wrapper: wrapperFor(mediaProposals) })

  expect(await screen.findByText('Storing…')).toBeInTheDocument()
  // Neither decision remains available once the decision is made.
  expect(screen.queryByRole('button', { name: 'Reject' })).not.toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'Accept' })).not.toBeInTheDocument()
})

it('reports a failed proposal rather than leaving it looking like it is still working', async () => {
  const mediaProposals = fakeMediaProposals({
    list: vi.fn().mockResolvedValue([
      group({
        proposals: [proposal({ status: 'failed', error: 'HTML interstitial, not an image' })],
      }),
    ]),
  })

  render(<MediaProposalPane projectId={project} />, { wrapper: wrapperFor(mediaProposals) })

  expect(await screen.findByText('Failed: HTML interstitial, not an image')).toBeInTheDocument()
})

it('rejects with the primary button, and opens ignore only behind a second choice of grain', async () => {
  const reject = vi.fn().mockResolvedValue(undefined)
  const mediaProposals = fakeMediaProposals({
    list: vi.fn().mockResolvedValue([group()]),
    reject,
  })
  const user = userEvent.setup()

  render(<MediaProposalPane projectId={project} />, { wrapper: wrapperFor(mediaProposals) })

  await user.click(await screen.findByRole('button', { name: 'Reject' }))
  expect(reject).toHaveBeenCalledWith(project, 'p1', undefined)

  // Ignore is not a single click away, unlike Reject: it needs a grain
  // chosen first, which is the point -- a misaimed click cannot ignore an
  // asset or a host by accident the way it can reject.
  expect(screen.queryByRole('button', { name: 'Ignore this asset' })).not.toBeInTheDocument()
  await user.click(screen.getByRole('button', { name: 'Ignore…' }))
  expect(screen.getByRole('button', { name: 'Ignore this asset' })).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Ignore this host' })).toBeInTheDocument()
})

it('re-reads the listing when a media frame arrives on the live feed, not a poll', async () => {
  // Pins the fix for the bug in the task brief: `MediaProposals` events were
  // pushed (`FEED_AGGREGATE_TYPES`) but misrouted -- the server's SSE
  // generator had no branch for them, so they fell to the generic log-frame
  // path, which stamps `index: 0`, which `decodeFrame` requires be `>= 1` to
  // accept a frame as a log entry, so every one was silently dropped. This
  // asserts the pane actually redraws from the frame, not merely that
  // `decodeFrame` can produce one -- a fix that only added the frame kind and
  // never wired the pane to it would leave this red.
  const feed = fakeStream()
  const first = [group({ proposals: [proposal({ status: 'accepted' })] })]
  const second = [
    group({
      proposals: [proposal({ status: 'failed', error: 'HTML interstitial, not an image' })],
    }),
  ]
  const list = vi.fn().mockResolvedValueOnce(first).mockResolvedValueOnce(second)
  const mediaProposals = fakeMediaProposals({ list })

  render(<MediaProposalPane projectId={project} />, {
    wrapper: wrapperFor(mediaProposals, feed.stream),
  })

  expect(await screen.findByText('Storing…')).toBeInTheDocument()
  expect(list).toHaveBeenCalledTimes(1)

  feed.pushMedia()
  await act(() => new Promise((resolve) => setTimeout(resolve, 450)))

  expect(list).toHaveBeenCalledTimes(2)
  expect(await screen.findByText('Failed: HTML interstitial, not an image')).toBeInTheDocument()
})

it('lists what is currently ignored, with an undo', async () => {
  const unignore = vi.fn().mockResolvedValue(undefined)
  const mediaProposals = fakeMediaProposals({
    list: vi.fn().mockResolvedValue([]),
    ignored: vi.fn<MediaProposalRepository['ignored']>().mockResolvedValue({
      assets: ['https://example.com/pic.jpg'],
      hosts: ['spam.example'],
    }),
    unignore,
  })
  const user = userEvent.setup()

  render(<MediaProposalPane projectId={project} />, { wrapper: wrapperFor(mediaProposals) })

  await user.click(await screen.findByRole('button', { name: /Show ignored/ }))
  expect(await screen.findByText('spam.example')).toBeInTheDocument()
  expect(screen.getByText('https://example.com/pic.jpg')).toBeInTheDocument()

  const undoButtons = screen.getAllByRole('button', { name: 'Undo' })
  await user.click(undoButtons[0]!)
  expect(unignore).toHaveBeenCalledWith(project, 'host', 'spam.example')
})
