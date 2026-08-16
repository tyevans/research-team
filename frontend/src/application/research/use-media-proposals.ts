import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { useContainer } from '@app/container-context.tsx'
import { queryKeys } from '@application/queries/keys.ts'
import type { ProjectId } from '@domain/shared/identifier.ts'

/** Every proposal in the project, grouped by need.
 *
 * Polled, and only while something is still working -- there is no push
 * channel for this. `FeedFrame` in `event-stream.ts` names every aggregate the
 * server pushes frames for (`log`, `approval`, `activity`, `extraction`,
 * `seeding`, `dispatch`, `topic`, `graph`, `corpus`, `project`), and
 * `MediaProposals` is not among them -- `MediaProposalAccepted`,
 * `MediaProposalStored` and `MediaProposalFailed` are domain events with no
 * frame at all. BACKLOG.md B94 is the shape of what happens without this: a
 * row that shows no state at all for the minutes a transcription takes,
 * because nothing tells it the state changed. Polling is not free, so this
 * is conditional -- `refetchInterval` reads the query's own cached data and
 * returns `false` (no poll) unless a proposal is sitting in `accepted`,
 * which is the one state that is known to be transient. A pane nobody has
 * pressed accept on, which is the common case, never polls.
 */
export const useMediaProposals = (projectId: ProjectId) => {
  const { mediaProposals } = useContainer()

  return useQuery({
    queryKey: queryKeys.mediaProposals(projectId),
    queryFn: () => mediaProposals.list(projectId),
    refetchInterval: (query) => {
      const groups = query.state.data ?? []
      const stillWorking = groups.some((group) =>
        group.proposals.some((proposal) => proposal.status === 'accepted'),
      )
      return stillWorking ? 3000 : false
    },
  })
}

/** The ignore lists, for the undo list beside the pane. */
export const useIgnoredMedia = (projectId: ProjectId) => {
  const { mediaProposals } = useContainer()

  return useQuery({
    queryKey: queryKeys.ignoredMedia(projectId),
    queryFn: () => mediaProposals.ignored(projectId),
  })
}

/** Accept one proposal. Invalidates the listing rather than writing an
 *  optimistic `accepted` into the cache: the mutation resolves once the
 *  decision is recorded, before the download starts, and a re-read is what
 *  actually carries the status the card renders a working state from.
 */
export const useAcceptMediaProposal = (projectId: ProjectId) => {
  const { mediaProposals } = useContainer()
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: (proposalId: string) => mediaProposals.accept(projectId, proposalId),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: queryKeys.mediaProposals(projectId) }),
  })
}

export const useRejectMediaProposal = (projectId: ProjectId) => {
  const { mediaProposals } = useContainer()
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: ({ proposalId, note }: { proposalId: string; note?: string }) =>
      mediaProposals.reject(projectId, proposalId, note),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: queryKeys.mediaProposals(projectId) }),
  })
}

/** Ignore the asset or host behind one proposal.
 *
 * Invalidates both keys: the listing, because the card the proposal came
 * from should stop offering it, and the ignore list, because that is the
 * one place the person who just clicked can see -- and undo -- what they
 * did. Missing either invalidation would leave one of the two panes stale
 * until something unrelated happened to refetch it.
 */
export const useIgnoreMediaProposal = (projectId: ProjectId) => {
  const { mediaProposals } = useContainer()
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: ({ proposalId, grain }: { proposalId: string; grain: 'asset' | 'host' }) =>
      mediaProposals.ignore(projectId, proposalId, grain),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: queryKeys.mediaProposals(projectId) })
      await queryClient.invalidateQueries({ queryKey: queryKeys.ignoredMedia(projectId) })
    },
  })
}

/** Undo an ignore. Invalidates only the ignore list: unignoring an asset or
 *  host resurrects nothing on its own -- no new `MediaProposed` follows from
 *  it -- so the listing this project already has is still accurate.
 */
export const useUnignoreMedia = (projectId: ProjectId) => {
  const { mediaProposals } = useContainer()
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: ({ grain, key }: { grain: 'asset' | 'host'; key: string }) =>
      mediaProposals.unignore(projectId, grain, key),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: queryKeys.ignoredMedia(projectId) }),
  })
}
