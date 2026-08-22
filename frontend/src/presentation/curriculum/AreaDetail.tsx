import { useQuery } from '@tanstack/react-query'

import { useContainer } from '@app/container-context.tsx'
import { queryKeys } from '@application/queries/keys.ts'
import type { ProjectId } from '@domain/shared/identifier.ts'

import { ErrorBox, Loading } from '../common/primitives.tsx'
import { projectHref } from '../routing/routes.ts'

/** One area's full membership, and the way into its course.
 *
 * A second request rather than a field on the map's response: the map wants
 * five names per area and this wants sixty, and sending every member of every
 * area to draw a map is a response that grows with the project while what it
 * draws does not.
 *
 * Every member links into the graph rather than being inert text. That is the
 * payoff of clustering the graph instead of a vector space — an area's members
 * *are* graph entities, with neighbourhoods, definitions and usages already
 * built — and a list a reader cannot follow would throw it away.
 */
export const AreaDetail = ({ projectId, slug }: { projectId: ProjectId; slug: string }) => {
  const { curricula } = useContainer()
  const query = useQuery({
    queryKey: queryKeys.learningArea(projectId, slug),
    queryFn: () => curricula.area(projectId, slug),
  })

  if (query.isPending) return <Loading what="the area" />
  if (query.isError) {
    return (
      <ErrorBox
        heading="That learning area could not be read."
        message={query.error instanceof Error ? query.error.message : 'Unknown error.'}
        onRetry={() => void query.refetch()}
      />
    )
  }

  const area = query.data
  return (
    <section className="rounded-md border border-line bg-bg-panel p-3">
      <h3 className="font-medium m-0 text-sm">{area.title}</h3>
      {area.summary !== null && <p className="mt-1 mb-0 text-xs text-fg-dim">{area.summary}</p>}
      <p className="mt-1 mb-2 text-xs text-fg-dim">
        {area.size} entities, most connected first. The course for this area is written to{' '}
        <code>/course/areas/{area.slug}/</code> and reads in the Workspace tab.
      </p>
      <ul className="m-0 flex list-none flex-col gap-1 p-0">
        {area.members.map((member) => (
          <li key={member.entityId} className="flex items-baseline gap-2 text-xs">
            <a
              href={projectHref(projectId, { facet: 'entity', id: member.entityId })}
              className="focus-visible:lay-ring-inward text-fg no-underline hover:underline"
            >
              {member.name}
            </a>
            <span className="text-fg-faint">{member.entityType}</span>
            {member.temporal !== null && <span className="text-fg-faint">{member.temporal}</span>}
          </li>
        ))}
      </ul>
    </section>
  )
}
