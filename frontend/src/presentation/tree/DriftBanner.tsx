import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { queryKeys } from '@application/queries/keys.ts'
import { useContainer } from '@app/container-context.tsx'

import { Button } from '../common/primitives.tsx'

/** "The list below may be wrong", said next to the list.
 *
 * The session list is answered from a projection, so a drifted row looks
 * exactly like a correct one and reading it will never reveal the difference.
 * The topbar badge is the only signal there is, and on every other page that
 * is the right size for it — but this is the page whose entire content is that
 * list, and a small mark in the far corner is not proportionate to "none of
 * this is trustworthy". Same query, same rebuild, said louder in the one place
 * it matters.
 */
export const DriftBanner = () => {
  const { health } = useContainer()
  const queryClient = useQueryClient()

  const { data } = useQuery({
    queryKey: queryKeys.health(),
    queryFn: () => health.summaries(),
    // A projection does not drift on a schedule, and a failed check is not
    // worth a retry storm: the next reconnect asks again.
    retry: false,
    refetchOnWindowFocus: false,
  })

  const rebuild = useMutation({
    mutationFn: () => health.rebuildSummaries(),
    onSettled: async () => {
      await queryClient.invalidateQueries({ queryKey: queryKeys.health() })
      await queryClient.invalidateQueries({ queryKey: queryKeys.tree() })
      await queryClient.invalidateQueries({ queryKey: queryKeys.sessions() })
    },
  })

  if (!data || data.healthy) return null

  return (
    <div className="drift-banner" role="status">
      <strong>
        {data.following
          ? `The session list has drifted: ${data.failedEvents} events did not apply.`
          : 'The session list has stopped updating.'}
      </strong>
      <span>
        {data.following
          ? 'Sessions may be missing, or may show counts that are behind. Rebuilding re-derives every row from the log.'
          : // A stopped projection needs a restart, which a browser cannot do —
            // so this says what is wrong and offers nothing, rather than a
            // button that would quietly fail.
            'The projection is not following the log. Nothing here can restart it; the server has to.'}
      </span>
      {data.following ? (
        <Button small disabled={rebuild.isPending} onClick={() => rebuild.mutate()}>
          {rebuild.isPending ? 'Rebuilding…' : 'Rebuild the list'}
        </Button>
      ) : null}
    </div>
  )
}
