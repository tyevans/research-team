import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'

import { useContainer } from '@app/container-context.tsx'
import { queryKeys } from '@application/queries/keys.ts'
import type { OntologyClass } from '@domain/knowledge/ontology.ts'
import type { ProjectId } from '@domain/shared/identifier.ts'

import { ErrorBox, Loading } from '../common/primitives.tsx'
import { projectHref } from '../routing/routes.ts'
import { DiscoverySweep, type SweepProgress, type SweepRequest } from './DiscoverySweep.tsx'
import { OntologyClasses } from './OntologyClasses.tsx'

/** The classes a discovery pass has found in this project.
 *
 * Fetched on open rather than pushed: `Ontology` is deliberately off the live
 * feed (see `UNROUTED_AGGREGATE_TYPES` on the server), because the pass that
 * writes these events is queued by a reader who is already holding the
 * response. The staleness that leaves is real and bounded -- a pass finishing
 * in another tab does not repaint this one until it is reopened.
 */
export const OntologyPane = ({ projectId }: { projectId: ProjectId }) => {
  const { ontology } = useContainer()
  const queryClient = useQueryClient()
  const query = useQuery({
    queryKey: queryKeys.ontology(projectId),
    queryFn: () => ontology.classes(projectId),
  })

  const pending = useQuery({
    queryKey: queryKeys.ungroupedSources(projectId),
    queryFn: () => ontology.ungrouped(projectId),
  })

  /** Held here rather than derived from the mutation, because a mutation has
   *  one result and this has one per document: the counts have to move while
   *  the loop is still running, or a sweep over thirty-seven documents is a
   *  disabled button and no other feedback for several minutes. */
  const [progress, setProgress] = useState<SweepProgress | null>(null)

  const sweep = useMutation({
    mutationFn: async ({ again, lenient }: SweepRequest) => {
      // Fetched here rather than read off `pending.data` when the reader asked
      // for a re-read: that query holds the *unexamined* list, and the whole
      // point of `again` is the documents it excludes. Fetching it inside the
      // mutation also means the work list is as fresh as the press.
      const work = again
        ? await ontology.ungrouped(projectId, { includeExamined: true })
        : (pending.data ?? [])
      let found = 0
      let barren = 0
      let declined = 0
      setProgress({ done: 0, total: work.length, found, barren, declined })
      for (const [index, sourceId] of work.entries()) {
        // Sequential and deliberately not `Promise.all`: see `DiscoverySweep`.
        // Each pass is one model call over a whole document.
        const count = await ontology.discover(projectId, sourceId, { strict: !lenient })
        if (count === null) declined += 1
        else if (count === 0) barren += 1
        else found += 1
        setProgress({ done: index + 1, total: work.length, found, barren, declined })
      }
    },
    // `onSettled`, not `onSuccess`: a sweep that failed on document twenty has
    // still examined nineteen, and each was recorded by its own pass rather
    // than at the end. Invalidating only on success would leave the list and
    // the classes showing a corpus that had not been touched.
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.ontology(projectId) })
      void queryClient.invalidateQueries({ queryKey: queryKeys.ungroupedSources(projectId) })
    },
  })

  if (query.isPending) return <Loading what="classes" />
  if (query.isError) {
    return (
      <ErrorBox
        heading="The classes could not be read."
        message={query.error instanceof Error ? query.error.message : 'Unknown error.'}
        onRetry={() => void query.refetch()}
      />
    )
  }

  return (
    <>
      <DiscoverySweep
        // `null` while the work list is still loading *or* unreadable: a
        // failed read must not render as "every document has been read",
        // which is what an empty array would say.
        pending={pending.isSuccess ? pending.data : null}
        running={sweep.isPending}
        progress={progress}
        error={
          sweep.error instanceof Error
            ? sweep.error.message
            : sweep.error !== null
              ? 'The sweep stopped.'
              : null
        }
        onRun={(request) => sweep.mutate(request)}
      />
      <OntologyClasses
        classes={query.data}
        // Into the document reader, at the span the class was stated in. The
        // route owns what that URL looks like; this pane owns only the fact
        // that evidence is somewhere a reader can open.
        // Into the document reader, selecting the source the class came from.
        // The offsets are deliberately *not* in the URL: the routing grammar has
        // no arm that carries a span, and inventing one here would be a second
        // grammar for the same idea. Opening the right document is the promise
        // this can keep today; scrolling to the sentence wants a route change,
        // which belongs with whoever owns that grammar.
        sourceHref={(evidence: OntologyClass['evidence']) =>
          projectHref(projectId, { facet: 'doc', id: evidence.sourceId })
        }
      />
    </>
  )
}
