import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { useContainer } from '@app/container-context.tsx'
import { queryKeys } from '@application/queries/keys.ts'
import { isRunning, type AuthoringStatus } from '@domain/knowledge/authoring.ts'
import type { ProjectId } from '@domain/shared/identifier.ts'

import { ErrorBox, Loading } from '../common/primitives.tsx'
import { projectHref } from '../routing/routes.ts'
import { AreaMap } from './AreaMap.tsx'
import { AreaDetail } from './AreaDetail.tsx'
import { AuthoringBar } from './AuthoringBar.tsx'
import { EmbeddingRefresh } from './EmbeddingRefresh.tsx'
import { PathSteps } from './PathSteps.tsx'

/** How often the authoring status is re-read while a run is in flight.
 *
 * A poll rather than a live-feed subscription, and the reason is that there is
 * nothing on the feed to subscribe to: an authoring run leaves no event, only
 * the `write_file` calls its turns make. Those *do* arrive as log frames, but
 * they say a file was written rather than which area finished, so a panel
 * built on them could show files appearing and never say the run was done.
 *
 * Four seconds because the thing being watched is a model turn: a run's state
 * changes on the order of a minute, so a shorter interval is requests nobody
 * reads and a longer one is a progress bar that looks stuck.
 */
const AUTHORING_POLL_MS = 4_000

/** The curriculum, in whichever of its two readings the route asked for.
 *
 * One pane for both facets rather than two, because they are two views of one
 * response and splitting them would mean two fetches of the same projection
 * that could be answered from two different ones while a project extracts.
 *
 * Fetched on open rather than pushed. The projection is recomputed per request
 * behind a cache keyed on the graph's counts, so a run finishing in another
 * tab does not repaint this one until it is reopened — which is the same
 * bounded staleness `OntologyPane` documents, and for a stronger reason here:
 * silently re-clustering under a reader halfway through a path would move the
 * ground they are standing on.
 */
export const CurriculumPane = ({
  projectId,
  reading,
  selected,
  onReading,
}: {
  projectId: ProjectId
  reading: 'areas' | 'path'
  selected: string | null
  /** Switch reading. Writes the *facet*, not local state, so which reading a
   *  person is looking at survives a reload and can be sent to somebody --
   *  which is the whole argument for `path` being a facet at all given that it
   *  shares a tab. */
  onReading: (reading: 'areas' | 'path') => void
}) => {
  const { curricula } = useContainer()
  const queryClient = useQueryClient()

  const query = useQuery({
    queryKey: queryKeys.curriculum(projectId),
    queryFn: () => curricula.curriculum(projectId),
  })

  const status = useQuery<AuthoringStatus>({
    queryKey: queryKeys.authoring(projectId),
    queryFn: () => curricula.authoringStatus(projectId),
    // Polls only while something is running, and stops on its own when the run
    // settles. `false` is what react-query reads as "do not poll", so an idle
    // project costs one request on open and nothing after it.
    refetchInterval: (q) => (q.state.data && isRunning(q.state.data) ? AUTHORING_POLL_MS : false),
  })

  const author = useMutation({
    mutationFn: (request: { area?: string; lessons?: number }) =>
      curricula.author(projectId, request),
    onSuccess: () => {
      // The status, not the curriculum: authoring writes files and does not
      // touch the graph, so the projection is unchanged and re-clustering here
      // would be a superlinear pass run for nothing.
      void queryClient.invalidateQueries({ queryKey: queryKeys.authoring(projectId) })
    },
  })

  const cancel = useMutation({
    mutationFn: () => curricula.cancelAuthoring(projectId),
    onSuccess: () => {
      // The status, like `author` above. Deliberately *only* the status: the
      // run does not reach `cancelled` on the log synchronously with this
      // response -- the driving task appends that after the model turn it just
      // cancelled unwinds -- so this invalidation is what starts the poll
      // that will eventually see it, not a read of the settled state.
      void queryClient.invalidateQueries({ queryKey: queryKeys.authoring(projectId) })
    },
  })

  const refresh = useMutation({
    mutationFn: () => curricula.refreshEmbeddings(projectId),
    onSuccess: () => {
      // The curriculum, unlike authoring above: re-embedding changes the
      // signal the clustering runs on, and the server has already dropped its
      // cached projection. Not invalidating here would leave the button
      // apparently working and visibly changing nothing, because the entity
      // and relationship counts the cache keys on have not moved.
      void queryClient.invalidateQueries({ queryKey: queryKeys.curriculum(projectId) })
    },
  })

  if (query.isPending) return <Loading what="learning areas" />
  if (query.isError) {
    return (
      <ErrorBox
        heading="The learning areas could not be projected."
        message={query.error instanceof Error ? query.error.message : 'Unknown error.'}
        onRetry={() => void query.refetch()}
      />
    )
  }

  const curriculum = query.data
  const areaHref = (slug: string) =>
    projectHref(projectId, { facet: reading === 'path' ? 'path' : 'area', id: slug })
  const area =
    selected === null ? null : (curriculum.areas.find((a) => a.slug === selected) ?? null)

  return (
    <div className="flex min-h-0 flex-col gap-3 overflow-y-auto p-3">
      <AuthoringBar
        status={status.data ?? null}
        areaSlug={area?.slug ?? null}
        areaTitle={area?.title ?? null}
        pathLength={curriculum.path.areaSlugs.length}
        pending={author.isPending}
        stopping={cancel.isPending}
        // Either mutation's error, whichever happened -- one line, because the
        // two are never in flight together: the stop only exists while a run
        // is running and the write buttons are disabled for exactly then.
        error={
          author.error instanceof Error
            ? author.error.message
            : cancel.error instanceof Error
              ? cancel.error.message
              : null
        }
        onAuthor={(request) => author.mutate(request)}
        onCancel={() => cancel.mutate()}
      />
      <EmbeddingRefresh
        derivedFrom={curriculum.derivedFrom}
        pending={refresh.isPending}
        embedded={refresh.data ?? null}
        error={refresh.error instanceof Error ? refresh.error.message : null}
        onRefresh={() => refresh.mutate()}
      />
      <ReadingToggle reading={reading} onReading={onReading} />
      {reading === 'path' ? (
        <PathSteps curriculum={curriculum} selected={selected} areaHref={areaHref} />
      ) : (
        <AreaMap curriculum={curriculum} selected={selected} areaHref={areaHref} />
      )}
      {area !== null && <AreaDetail projectId={projectId} slug={area.slug} />}
    </div>
  )
}

/** Which reading of the curriculum is on screen.
 *
 * A radio group rather than two buttons or a tab strip: the two readings are
 * mutually exclusive views of one thing, which is exactly what a radio group
 * means to assistive technology, and the strip above is already full — see
 * `MATERIAL_TABS` on why this is one tab rather than two.
 */
const ReadingToggle = ({
  reading,
  onReading,
}: {
  reading: 'areas' | 'path'
  onReading: (reading: 'areas' | 'path') => void
}) => (
  <div role="radiogroup" aria-label="Curriculum reading" className="flex gap-1">
    {(
      [
        ['areas', 'Areas'],
        ['path', 'Path'],
      ] as const
    ).map(([value, label]) => (
      <button
        key={value}
        type="button"
        role="radio"
        aria-checked={reading === value}
        onClick={() => onReading(value)}
        className={[
          'rounded focus-visible:lay-ring-inward border border-line px-2 py-1 text-xs',
          reading === value ? 'border-accent bg-bg-raise text-fg' : 'bg-bg-panel text-fg-dim',
        ].join(' ')}
      >
        {label}
      </button>
    ))}
  </div>
)
