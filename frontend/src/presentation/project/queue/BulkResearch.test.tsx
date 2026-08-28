import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { ReactNode } from 'react'
import { expect, it, vi } from 'vitest'

import type { Container as AppContainer } from '@app/container.ts'
import { ContainerProvider } from '@app/container-context.tsx'
import type { TopicRepository } from '@application/ports/repositories.ts'
import { BULK_CAP } from '@application/research/use-dispatch.ts'
import { ProjectId, TopicId } from '@domain/shared/identifier.ts'

import { OverlayHost } from '../../layout/OverlayHost.tsx'
import { BulkResearch } from './BulkResearch.tsx'

const PROJECT = ProjectId('11111111-1111-1111-1111-111111111111')

/** Distinct ids rather than one repeated, because the assertion that matters
 *  is that the *list* travels: fifty copies of one id would pass against a
 *  client that sent only the first. */
const ids = (count: number): readonly TopicId[] =>
  Array.from({ length: count }, (_unused, index) =>
    TopicId(`22222222-2222-2222-2222-${String(index).padStart(12, '0')}`),
  )

const frame = (topicId: string) => ({
  dispatchId: `d-${topicId}`,
  topicId,
  action: 'research',
  status: 'queued' as const,
  question: null,
  position: 1,
  path: null,
  sessionId: null,
  detail: null,
})

const renderBulk = (
  topicIds: readonly TopicId[],
  dispatchBulk: TopicRepository['dispatchBulk'],
) => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } })
  // `OverlayHost` innermost, matching the real tree and `QueueHeader.test.tsx`:
  // the button hangs its explanation on a `Tooltip`, which portals into the
  // host and renders `null` without one -- so every "says why it is off"
  // assertion below would fail for a reason that has nothing to do with this
  // component.
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>
      <ContainerProvider
        container={
          {
            topics: {
              dispatchBulk,
              dispatchStatus: vi
                .fn()
                .mockResolvedValue({ running: null, queued: [], finished: [] }),
            },
          } as unknown as AppContainer
        }
      >
        <OverlayHost>{children}</OverlayHost>
      </ContainerProvider>
    </QueryClientProvider>
  )
  return render(<BulkResearch projectId={PROJECT} topicIds={topicIds} />, { wrapper })
}

/** The safety property, and the only test in this file that is about anything
 *  other than wording.
 *
 * `docs/design/topic-actions-on-the-row.md` §3.3: the count on the button and
 * the number of turns started have to be the same number *by construction*.
 * So the assertion is the pair together -- the label says twelve and exactly
 * those twelve ids reach the client -- rather than either half alone. A label
 * asserted on its own passes against a call that sent every topic in the
 * project, which is the failure mode the route refuses an "all" to prevent.
 *
 * **Proved red** by sending `topicIds.slice(0, 10)` from `BulkResearch`: the
 * label still reads twelve and the ids no longer match.
 */
it('starts exactly the topics its label counts', async () => {
  const dispatchBulk = vi
    .fn<TopicRepository['dispatchBulk']>()
    .mockResolvedValue({ queued: ids(12).map((id) => frame(String(id))), unknown: [] })
  const shown = ids(12)
  renderBulk(shown, dispatchBulk)

  const button = await screen.findByRole('button', { name: 'Find sources for 12 topics' })
  await userEvent.click(button)

  expect(dispatchBulk).toHaveBeenCalledWith(PROJECT, 'research', shown)
})

/** `research`, not `understanding`, and it is worth its own line.
 *
 * The two are one string apart at the call site and the server accepts both,
 * so a fan-out pointed at the wrong one enqueues forty turns that succeed,
 * write forty files, and are wrong -- with nothing on screen saying which verb
 * ran until somebody opens one. The test above would pass against it.
 *
 * **Proved red** by changing the action to `'understanding'`.
 */
it('fans out research rather than any other verb', async () => {
  const dispatchBulk = vi
    .fn<TopicRepository['dispatchBulk']>()
    .mockResolvedValue({ queued: [], unknown: [] })
  renderBulk(ids(2), dispatchBulk)

  await userEvent.click(await screen.findByRole('button', { name: /Find sources/ }))

  expect(dispatchBulk).toHaveBeenCalledWith(PROJECT, 'research', expect.anything())
})

/** Over the cap, refused here rather than by a 422 nobody can read.
 *
 * `aria-disabled` rather than `disabled`, for the row verbs' reason: the
 * sentence saying *which* of the three off-states applies is the whole value
 * of the control being off, and a `disabled` element takes neither focus nor
 * pointer events, so a keyboard could never open it.
 *
 * **Proved red** by dropping the `overCap` term from `off`: the press goes
 * through and the server answers 422 for a list of 51.
 */
it('refuses more than the cap, and says how to get under it', async () => {
  const dispatchBulk = vi
    .fn<TopicRepository['dispatchBulk']>()
    .mockResolvedValue({ queued: [], unknown: [] })
  renderBulk(ids(BULK_CAP + 1), dispatchBulk)

  const button = await screen.findByRole('button', {
    name: `Find sources for ${String(BULK_CAP + 1)} topics`,
  })
  expect(button).toHaveAttribute('aria-disabled', 'true')

  button.focus()
  expect(await screen.findByText(/Too many topics shown/)).toBeInTheDocument()

  await userEvent.click(button)
  expect(dispatchBulk).not.toHaveBeenCalled()
})

/** An empty filter is its own refusal, with its own sentence.
 *
 * The generic "not available" that would cover this and the cap together is
 * actionable for neither: one is fixed by widening the filter and the other by
 * narrowing it, which is the same control moved in opposite directions.
 *
 * **Proved red** by dropping the `empty` term from `off`: the route answers
 * 422 for an empty list, so this state cannot be allowed to press either.
 */
it('will not fan out over nothing', async () => {
  const dispatchBulk = vi
    .fn<TopicRepository['dispatchBulk']>()
    .mockResolvedValue({ queued: [], unknown: [] })
  renderBulk([], dispatchBulk)

  const button = await screen.findByRole('button', { name: 'Find sources for 0 topics' })
  // Focus before the click, not after: a click on an open tooltip's trigger
  // dismisses it, so the order that reads more naturally asserts on a tooltip
  // that was correctly there and has correctly gone.
  button.focus()
  expect(await screen.findByText(/No topics are shown/)).toBeInTheDocument()

  await userEvent.click(button)
  expect(dispatchBulk).not.toHaveBeenCalled()
})

/** The `unknown` array, said out loud.
 *
 * This is the assertion the whole `unknown` field exists for. A client that
 * ignores it starts eleven dispatches under a button that said twelve, reports
 * success, and is indistinguishable from one that started all twelve -- which
 * is precisely "silently starting fewer than you said".
 *
 * **Proved red** by rendering `outcome(queued.length, 0)`: the count is right
 * and the sentence about the missing topic disappears.
 */
it('reports the topics that were no longer there rather than folding them in', async () => {
  const dispatchBulk = vi.fn<TopicRepository['dispatchBulk']>().mockResolvedValue({
    queued: ids(11).map((id) => frame(String(id))),
    unknown: ['22222222-2222-2222-2222-000000000011'],
  })
  renderBulk(ids(12), dispatchBulk)

  await userEvent.click(await screen.findByRole('button', { name: 'Find sources for 12 topics' }))

  const report = await screen.findByRole('status')
  expect(report).toHaveTextContent('Started 11 dispatches.')
  expect(report).toHaveTextContent('1 topic was no longer there')
})

/** One topic reads as one topic.
 *
 * Small, and here because the plural is built by hand: `12 topics` and
 * `1 topics` come out of the same expression, and the second is the kind of
 * thing that ships and stays.
 */
it('counts one topic in the singular', async () => {
  renderBulk(ids(1), vi.fn<TopicRepository['dispatchBulk']>())

  expect(
    await screen.findByRole('button', { name: 'Find sources for 1 topic' }),
  ).toBeInTheDocument()
})
