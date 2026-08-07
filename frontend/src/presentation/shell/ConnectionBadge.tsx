import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { useEffect } from 'react'

import { queryKeys } from '@application/queries/keys.ts'
import type { ConnectionState } from '@application/ports/event-stream.ts'
import { useContainer } from '@app/container-context.tsx'

import { useStream } from './StreamProvider.tsx'

const LABELS: Readonly<Record<ConnectionState, string>> = {
  connecting: 'connecting',
  open: 'live',
  down: 'reconnecting',
}

export const ConnectionBadge = ({ state }: { state: ConnectionState }) => (
  <span
    className="conn"
    id="conn"
    data-state={state === 'open' ? 'open' : state === 'down' ? 'down' : 'init'}
    title="event stream"
    role="status"
    aria-live="polite"
    aria-atomic="true"
  >
    <span className="conn-dot" />
    <span className="conn-label">{LABELS[state]}</span>
  </span>
)

/** The session list is answered from a projection, which can be wrong in a way
 *  that reading it will never reveal — a wrong row looks exactly like a right
 *  one. This badge is the only thing that would tell you otherwise, which is
 *  why it is hidden whenever the list is trustworthy. */
export const DriftBadge = () => {
  const { health } = useContainer()
  const queryClient = useQueryClient()
  const stream = useStream()

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

  // A projection does not drift on a schedule, but a reconnect is exactly when
  // it might have: the connection dropped because something restarted, and a
  // projection that did not come back with it is what this badge is for.
  useEffect(
    () =>
      stream.onReconnect(() => {
        void queryClient.invalidateQueries({ queryKey: queryKeys.health() })
      }),
    [queryClient, stream],
  )

  if (!data || data.healthy) return null

  return (
    <span className="drift" id="drift" role="status" aria-live="polite">
      <span className="conn-dot" />
      <span className="drift-label">
        {data.following ? `list drifted (${data.failedEvents})` : 'list not updating'}
      </span>
      {/* Only a drifted list has a remedy from here. A stopped projection needs
          a restart, which a browser cannot do. */}
      {data.following ? (
        <button
          type="button"
          className="drift-fix"
          id="drift-fix"
          disabled={rebuild.isPending}
          onClick={() => rebuild.mutate()}
        >
          {rebuild.isPending ? 'rebuilding' : 'rebuild'}
        </button>
      ) : null}
    </span>
  )
}
