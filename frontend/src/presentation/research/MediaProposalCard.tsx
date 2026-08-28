import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'

import { useContainer } from '@app/container-context.tsx'
import { errorMessage } from '@application/ports/errors.ts'
import { notify } from '@application/notifications/toast-store.ts'
import { queryKeys } from '@application/queries/keys.ts'
import {
  useAcceptMediaProposal,
  useIgnoreMediaProposal,
  useRejectMediaProposal,
} from '@application/research/use-media-proposals.ts'
import type { MediaProposal } from '@domain/research/media-proposal.ts'
import type { ProjectId, SourceId } from '@domain/shared/identifier.ts'

import { Button, Disclosure, ErrorBox, Loading } from '../common/primitives.tsx'
import { DocumentReader } from './DocumentReader.tsx'

/** One candidate: thumbnail, title, the judge's reason, and the decision.
 *
 * Reject is the primary action and sits on the card; ignore is secondary and
 * behind a confirming choice of grain. Ignoring is the explicit forever --
 * an asset or a host is refused for every future need, not just this one --
 * and a blacklist entry added by a misaimed click is worse than a rejection
 * added the same way, which is reversible only in the sense that a fresh
 * proposal for the same asset is still allowed later. See "Rejecting is not
 * blacklisting" in `domain/media_proposals.py`.
 */
export const MediaProposalCard = ({
  projectId,
  proposal,
}: {
  projectId: ProjectId
  proposal: MediaProposal
}) => {
  const accept = useAcceptMediaProposal(projectId)
  const reject = useRejectMediaProposal(projectId)
  const ignore = useIgnoreMediaProposal(projectId)
  const [choosingIgnore, setChoosingIgnore] = useState(false)

  const handleAccept = () =>
    accept.mutate(proposal.proposalId, {
      onError: (error) => notify(errorMessage(error), 'bad'),
    })

  const handleReject = () =>
    reject.mutate(
      { proposalId: proposal.proposalId },
      { onError: (error) => notify(errorMessage(error), 'bad') },
    )

  const handleIgnore = (grain: 'asset' | 'host') => {
    ignore.mutate(
      { proposalId: proposal.proposalId, grain },
      {
        onSuccess: () => notify(grain === 'asset' ? 'Asset ignored' : 'Host ignored'),
        onError: (error) => notify(errorMessage(error), 'bad'),
      },
    )
    setChoosingIgnore(false)
  }

  const deciding = proposal.status === 'proposed'

  return (
    <article className="flex gap-3 rounded-md border border-line p-3">
      <Thumbnail url={proposal.thumbnailUrl} kind={proposal.kind} />

      <div className="flex flex-1 flex-col gap-1">
        <strong>{proposal.title || proposal.assetUrl}</strong>
        {/* The reason a person judges the asset against, not a caption for
            it -- see the pane's own docstring. */}
        <p className="text-sm text-fg-dim">{proposal.reason}</p>

        <ProposalOutcome projectId={projectId} proposal={proposal} />

        {deciding ? (
          <div className="flex flex-wrap items-center gap-2">
            <Button tone="danger" onClick={handleReject} disabled={reject.isPending}>
              Reject
            </Button>
            <Button tone="quiet" onClick={handleAccept} disabled={accept.isPending}>
              Accept
            </Button>
            {choosingIgnore ? (
              <>
                <Button small tone="ghost" onClick={() => handleIgnore('asset')}>
                  Ignore this asset
                </Button>
                <Button small tone="ghost" onClick={() => handleIgnore('host')}>
                  Ignore this host
                </Button>
                <Button small tone="ghost" onClick={() => setChoosingIgnore(false)}>
                  Cancel
                </Button>
              </>
            ) : (
              <Button small tone="ghost" onClick={() => setChoosingIgnore(true)}>
                Ignore…
              </Button>
            )}
          </div>
        ) : null}
      </div>
    </article>
  )
}

/** What the card says beneath the reason, keyed off the proposal's own
 *  status -- one thing rendered per state, never two, so a person cannot
 *  read "Storing…" beside a finished error. */
const ProposalOutcome = ({
  projectId,
  proposal,
}: {
  projectId: ProjectId
  proposal: MediaProposal
}) => {
  switch (proposal.status) {
    case 'accepted':
      // Stays visible in a working state until `list` reports `stored` or
      // `failed` -- see `MediaProposalPane`'s own comment for the live-feed
      // frame that triggers that re-read. BACKLOG.md B94 records the inverse
      // defect already in this codebase (a media row showing no state at all
      // for the minutes an hour of audio takes to transcribe) and this is
      // deliberately not that.
      return <span className="text-sm">Storing…</span>
    case 'stored':
      return proposal.sourceId ? (
        <StoredMediaView projectId={projectId} sourceId={proposal.sourceId} />
      ) : null
    case 'failed':
      return (
        <span className="text-sm text-k-failure">
          Failed{proposal.error ? `: ${proposal.error}` : ''}
        </span>
      )
    case 'rejected':
      return (
        <span className="text-sm text-fg-dim">
          Rejected{proposal.note ? `: ${proposal.note}` : ''}
        </span>
      )
    case 'proposed':
      return null
  }
}

/** A stored proposal, opened through the same `DocumentReader` the document
 *  pane uses -- nothing new is needed to *view* media, only to view
 *  something that was not stored yet. See "The pane" in the design doc.
 *
 * The document list is fetched here rather than threaded down from a parent:
 * this card is the only place in the media pane that needs a `SourceSummary`,
 * and it shares `queryKeys.documents(projectId)` with `DocumentList`, so a
 * corpus already open elsewhere costs this disclosure nothing to open.
 * `enabled: open` keeps that read off every stored card that nobody has
 * expanded.
 */
const StoredMediaView = ({ projectId, sourceId }: { projectId: ProjectId; sourceId: SourceId }) => {
  const { documents } = useContainer()
  const [open, setOpen] = useState(false)

  const query = useQuery({
    queryKey: queryKeys.documents(projectId),
    queryFn: () => documents.list(projectId),
    enabled: open,
  })

  return (
    <Disclosure label="Stored — view" open={open} onToggle={() => setOpen((v) => !v)}>
      {query.isPending ? (
        <Loading what="document" />
      ) : query.isError ? (
        <ErrorBox heading="Could not open this source" message={errorMessage(query.error)} />
      ) : (
        <DocumentReader
          projectId={projectId}
          sourceId={sourceId}
          source={(query.data ?? []).find((row) => row.sourceId === sourceId) ?? null}
        />
      )}
    </Disclosure>
  )
}

/** The thumbnail, or a typed placeholder.
 *
 * Measured 2026-08-15: `thumbnail_url` was absent on 46 of 262 image
 * results. Falling back to the full-size asset for those would put a grid of
 * full-resolution images on the page -- exactly the cost the design doc's
 * "Thumbnails" section rules out. A placeholder that names the kind is the
 * fix: it costs nothing to render and still tells a person what they are
 * about to judge.
 */
const Thumbnail = ({ url, kind }: { url: string | null; kind: string }) => {
  if (url) {
    // `alt=""`: the title beside this image already carries the same
    // information a description would, and a screen reader announcing both
    // is announcing the same card twice.
    return <img src={url} alt="" className="h-[64px] w-[64px] shrink-0 rounded-md object-cover" />
  }
  return (
    <div
      aria-hidden="true"
      className="flex h-[64px] w-[64px] shrink-0 items-center justify-center rounded-md border border-line bg-bg-raise text-xs text-fg-dim uppercase"
    >
      {kind || 'media'}
    </div>
  )
}
