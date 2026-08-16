import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { useContainer } from '@app/container-context.tsx'
import { queryKeys } from '@application/queries/keys.ts'
import type { ProjectId } from '@domain/shared/identifier.ts'

/** Every proposal in the project, grouped by need.
 *
 * No poll and no frame subscription here -- the application layer must not
 * depend on the UI (see `eslint.config.js`'s layering rule), and
 * `useFrameRefresh` lives in `presentation/shell`. `MediaProposalPane`
 * invalidates this query's key on the live feed's `media` frame instead; see
 * its own comment for what that frame replaced.
 */
export const useMediaProposals = (projectId: ProjectId) => {
  const { mediaProposals } = useContainer()

  return useQuery({
    queryKey: queryKeys.mediaProposals(projectId),
    queryFn: () => mediaProposals.list(projectId),
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
