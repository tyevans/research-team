import { errorMessage } from '@application/ports/errors.ts'
import { notify } from '@application/notifications/toast-store.ts'
import { useIgnoredMedia, useUnignoreMedia } from '@application/research/use-media-proposals.ts'
import type { ProjectId } from '@domain/shared/identifier.ts'

import { Button, EmptyState, ErrorBox, Loading } from '../common/primitives.tsx'

/** What is currently ignored, at both grains, with an undo on each.
 *
 * Ignoring is the explicit forever -- see `MediaProposalCard`'s own comment
 * -- and a suppression nobody can see is indistinguishable from a chain that
 * has stopped working: a topic that keeps finding nothing to propose for a
 * need may simply have had every candidate ignored by an earlier misclick,
 * and this is the only place that says so. See "The pane" in
 * docs/superpowers/specs/2026-08-16-media-acquisition-design.md.
 */
export const IgnoredList = ({ projectId }: { projectId: ProjectId }) => {
  const query = useIgnoredMedia(projectId)
  const unignore = useUnignoreMedia(projectId)

  if (query.isPending) return <Loading what="ignored media" />

  if (query.isError) {
    return (
      <ErrorBox
        heading="Could not read the ignore lists"
        message={errorMessage(query.error)}
        onRetry={() => void query.refetch()}
      />
    )
  }

  const { assets, hosts } = query.data
  if (assets.length === 0 && hosts.length === 0) {
    return <EmptyState heading="Nothing is ignored" />
  }

  const handleUndo = (grain: 'asset' | 'host', key: string) => {
    unignore.mutate(
      { grain, key },
      {
        onSuccess: () => notify(grain === 'asset' ? 'Asset un-ignored' : 'Host un-ignored'),
        onError: (error) => notify(errorMessage(error), 'bad'),
      },
    )
  }

  return (
    <div className="flex flex-col gap-3 rounded-md border border-line p-3">
      {hosts.length > 0 ? (
        <section className="flex flex-col gap-1">
          <h4 className="font-medium text-sm text-fg-dim">Ignored hosts</h4>
          <ul className="flex flex-col gap-1">
            {hosts.map((host) => (
              <li key={host} className="flex items-center justify-between gap-2 text-sm">
                <span>{host}</span>
                <Button
                  small
                  onClick={() => handleUndo('host', host)}
                  disabled={unignore.isPending}
                >
                  Undo
                </Button>
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      {assets.length > 0 ? (
        <section className="flex flex-col gap-1">
          <h4 className="font-medium text-sm text-fg-dim">Ignored assets</h4>
          <ul className="flex flex-col gap-1">
            {assets.map((asset) => (
              <li key={asset} className="flex items-center justify-between gap-2 text-sm">
                <span className="truncate">{asset}</span>
                <Button
                  small
                  onClick={() => handleUndo('asset', asset)}
                  disabled={unignore.isPending}
                >
                  Undo
                </Button>
              </li>
            ))}
          </ul>
        </section>
      ) : null}
    </div>
  )
}
