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

  // Counted off the ignore lists rather than off `showIgnored` alone, so the
  // toggle can say "Show ignored (3)" instead of a bare disclosure a person
  // has to open to find out whether it does anything.
  const ignoredCount =
    (ignoredQuery.data?.assets.length ?? 0) + (ignoredQuery.data?.hosts.length ?? 0)

  // Ignoring an asset or host appends `MediaAssetIgnored`/`MediaHostIgnored`
  // but leaves the proposal itself at `proposed` -- `decide` has no
  // transition that closes it, and the design leaves "does ignoring also
  // reject" unsettled. Left unfiltered, the card that was just ignored comes
  // back from the refetch byte-identical, Accept/Reject/Ignore still on it,
  // and the only evidence anything happened is a toast that fades. Filtering
  // client-side, here, is the fix: the server-recorded ignore is the source
  // of truth (an `assetUrl` exact match against `assets`, a hostname match
  // against `hosts`), and this pane is the one place both that list and the
  // proposal list are already in hand.
  //
  // The asset match is exact-string against `assets`, which the server
  // populates from `normalize_url` -- not reproduced client-side, so a
  // proposal whose `assetUrl` differs from the ignored form only by
  // normalization (trailing slash, case) would not be filtered here even
  // though `decide` would refuse re-proposing it. The host match does not
  // have this gap: `new URL(...).hostname` and the server's `_host_of` agree
  // on lowercasing and on stripping everything but the host.
  const ignoredAssets = new Set(ignoredQuery.data?.assets ?? [])
  const ignoredHosts = new Set(ignoredQuery.data?.hosts ?? [])
  const isIgnored = (proposal: { assetUrl: string }): boolean => {
    if (ignoredAssets.has(proposal.assetUrl)) return true
    try {
      return ignoredHosts.has(new URL(proposal.assetUrl).hostname.toLowerCase())
    } catch {
      return false
    }
  }
  const groups = (query.data ?? [])
    .map((group) => ({
      ...group,
      proposals: group.proposals.filter((proposal) => !isIgnored(proposal)),
    }))
    .filter((group) => group.proposals.length > 0)

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
            <h3 className="text-sm font-medium text-fg-dim">
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
