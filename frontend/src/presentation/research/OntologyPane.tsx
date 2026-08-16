import { useQuery } from '@tanstack/react-query'

import { useContainer } from '@app/container-context.tsx'
import { queryKeys } from '@application/queries/keys.ts'
import type { OntologyClass } from '@domain/knowledge/ontology.ts'
import type { ProjectId } from '@domain/shared/identifier.ts'

import { ErrorBox, Loading } from '../common/primitives.tsx'
import { projectHref } from '../routing/routes.ts'
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
  const query = useQuery({
    queryKey: queryKeys.ontology(projectId),
    queryFn: () => ontology.classes(projectId),
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
  )
}
