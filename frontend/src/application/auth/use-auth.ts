import { useQuery } from '@tanstack/react-query'

import { queryKeys } from '@application/queries/keys.ts'
import { ApiError } from '@application/ports/errors.ts'
import { useContainer } from '@app/container-context.tsx'

/** Whether this build requires a sign-in, and whether there is one.
 *
 * Fetched once and then left alone: `staleTime: Infinity` and no refetch on
 * focus. The answer changes exactly twice in a page's life -- at sign-in and
 * at sign-out -- and both of those are full-page navigations through the
 * server, so there is no in-page transition for a poll to catch. Polling it
 * would put a request on every window focus for a value that cannot have
 * moved.
 */
export const useAuthStatus = () => {
  const container = useContainer()
  return useQuery({
    queryKey: queryKeys.authStatus(),
    queryFn: () => container.auth.status(),
    staleTime: Infinity,
    // One retry rather than the default three: this query gates the whole
    // console, so a failing network costs a person three back-offs of blank
    // screen before they are told anything.
    retry: 1,
  })
}

/** The signed-in person, or `null`.
 *
 * A 401 is a *value*, not an error. That is the whole of this hook: the query
 * is enabled whenever identity is configured, and a 401 resolves to `null`
 * rather than rejecting, so the account menu renders "signed out" instead of
 * an error box. Letting it reject would also make React Query retry a 401
 * three times on every mount, which is three requests to say the same thing.
 *
 * Any *other* failure is still an error, deliberately: a 500 from `/api/me`
 * means something is broken, and reporting it as "signed out" would send a
 * person round a sign-in loop that cannot succeed.
 */
export const useCurrentUser = ({ enabled = true }: { enabled?: boolean } = {}) => {
  const container = useContainer()
  return useQuery({
    queryKey: queryKeys.currentUser(),
    queryFn: async () => {
      try {
        return await container.auth.me()
      } catch (error) {
        if (error instanceof ApiError && error.status === 401) return null
        throw error
      }
    },
    enabled,
    staleTime: Infinity,
    retry: (count, error) => !(error instanceof ApiError) && count < 1,
  })
}
