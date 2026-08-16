import { useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'

import { useIgnoredMedia, useMediaProposals } from '@application/research/use-media-proposals.ts'
import { errorMessage } from '@application/ports/errors.ts'
import { queryKeys } from '@application/queries/keys.ts'
import type { ProjectId } from '@domain/shared/identifier.ts'

import { Button, EmptyState, ErrorBox, Loading } from '../common/primitives.tsx'
import { useFrameRefresh } from '../shell/use-frame-refresh.ts'
import { IgnoredList } from './IgnoredList.tsx'
import { MediaProposalCard } from './MediaProposalCard.tsx'

/** Every media proposal for one project, grouped under the need that
 *  produced it.
 *
 * Grouped by need rather than shown as one flat list: a person approving a
 * candidate judges it against the reason it was wanted, and a card with no
 * need in view is asking them to guess at that reason from the asset alone.
 * See "The pane" in docs/superpowers/specs/2026-08-16-media-acquisition-design.md.
 */
export const MediaProposalPane = ({ projectId }: { projectId: ProjectId }) => {
  const query = useMediaProposals(projectId)
  const ignoredQuery = useIgnoredMedia(projectId)
  const [showIgnored, setShowIgnored] = useState(false)
  const queryClient = useQueryClient()

  // Refetches on the live feed's `media` frame in place of the poll this pane
  // used to run every 3s while a proposal sat in `accepted` -- the one state
  // known to be transient, because accepting answers 202 and the terminal
  // state (stored or failed) arrives minutes later after a download and a
  // perception pass. `MediaProposals` events were pushed all along
  // (`FEED_AGGREGATE_TYPES` in event_store.py) but misrouted: the server's
  // SSE generator had no branch for them, so they fell to the generic
  // log-frame path, which stamps `index: 0`, which `decodeFrame` requires be
  // `>= 1` to accept a frame as a log entry -- every one was silently
  // dropped. See `media_change` in `presenters.py` for the fix.
  useFrameRefresh(
    // Always on: this pane is the one place that reads this query, so being
    // mounted is the "on screen" test other `useFrameRefresh` callers gate
    // a flag on.
    true,
    (frame) => frame.kind === 'media' && frame.projectId === projectId,
    () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.mediaProposals(projectId) })
    },
  )

  if (query.isPending) return <Loading what="media proposals" />

  if (query.isError) {
    return (
      <ErrorBox
        heading="Could not read this project's media proposals"
        message={errorMessage(query.error)}
        onRetry={() => void query.refetch()}
      />
    )
  }

  const groups = query.data
  // Counted off the ignore lists rather than off `showIgnored` alone, so the
  // toggle can say "Show ignored (3)" instead of a bare disclosure a person
  // has to open to find out whether it does anything.
  const ignoredCount =
    (ignoredQuery.data?.assets.length ?? 0) + (ignoredQuery.data?.hosts.length ?? 0)

  return (
    <div className="flex flex-col gap-4">
      <div className="flex justify-end">
        <Button small tone="ghost" onClick={() => setShowIgnored((open) => !open)}>
          {showIgnored ? 'Hide ignored' : `Show ignored (${ignoredCount})`}
        </Button>
      </div>

      {showIgnored ? <IgnoredList projectId={projectId} /> : null}

      {groups.length === 0 ? (
        <EmptyState
          heading="No media has been proposed yet"
          detail="Run the media curation chain from a topic to search for candidates."
        />
      ) : (
        groups.map((group) => (
          <section key={group.needId} className="flex flex-col gap-2">
            {/* The need's own sentence from stage 1, not the id -- the id is
                an opaque key the projection uses to join rows, and nobody
                approving media should have to read one. */}
            <h3 className="font-medium text-sm text-fg-dim">
              {group.needDescription || group.needId}
            </h3>
            <div className="flex flex-col gap-2">
              {group.proposals.map((proposal) => (
                <MediaProposalCard
                  key={proposal.proposalId}
                  projectId={projectId}
                  proposal={proposal}
                />
              ))}
            </div>
          </section>
        ))
      )}
    </div>
  )
}
