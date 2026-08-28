import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { ApiError, errorMessage } from '@application/ports/errors.ts'
import { queryKeys } from '@application/queries/keys.ts'
import { useContainer } from '@app/container-context.tsx'
import type { AutonomyChange, AutonomyPolicyView } from '@domain/autonomy/autonomy.ts'
import type { SessionId } from '@domain/shared/identifier.ts'

/** The one reader and writer of autonomy state, shared by every surface.
 *
 * Two surfaces show this policy — the allow-all control in the worker drawer,
 * beside the approvals where the pain is, and the full per-tool panel in the
 * project page's queue header. They must never disagree, and the only reliable way to
 * guarantee that is for both to go through here: one query key
 * (`queryKeys.autonomy()`, deliberately unparameterised because the policy is
 * instance-wide), one cache entry, and a write that seeds *and* invalidates it
 * so both re-render from the same bytes.
 *
 * Seeding with the response and then invalidating looks redundant and is not.
 * The seed makes the flipped switch appear without a round trip; the
 * invalidation catches the case the API report warns about — another tab wrote
 * between this view's last read and this write, so the seeded map is correct
 * and any *other* observer's is not.
 *
 * `sessionId` may be null. The read never needs one; the writes always do,
 * because the audit record has to land on somebody's stream. Rather than
 * fabricating a session or firing a request that will 404, `canWrite` reports
 * it and the surfaces render their controls disabled with a reason. A policy
 * change with no trace makes every surrounding decision unreadable, which is
 * the one thing this system exists to prevent — so no session means no write,
 * not a quiet write.
 */
export interface AutonomyControls {
  readonly policy: AutonomyPolicyView | null
  readonly loading: boolean
  /** Why the policy could not be read, or null. The 404 for an unwired policy
   *  arrives here too: it is a fact about the build, and the surfaces say so
   *  rather than rendering switches over state they do not have. */
  readonly readError: string | null
  /** The read 404'd, which on these routes means only one thing: this build has
   *  no policy wired up. Told apart from any other read failure because the
   *  honest sentence differs — "this build cannot tell you" versus "the request
   *  failed" — and neither may be rendered as "nothing is gated". */
  readonly readNotFound: boolean
  readonly canWrite: boolean
  readonly setLevel: (tool: string, level: string) => void
  readonly allowAll: () => void
  readonly writing: boolean
  /** The server's own message from a rejected write, verbatim — it names the
   *  offending value, which nothing this side could reconstruct. */
  readonly writeError: string | null
  /** What the last allow-all actually moved, or null if none has run here.
   *  Only what moved: reporting the whole map would claim eight changes where
   *  the person made one. */
  readonly lastAllowAll: AutonomyChange | null
}

export const useAutonomy = (sessionId: SessionId | null): AutonomyControls => {
  const { autonomy } = useContainer()
  const queryClient = useQueryClient()

  const policy = useQuery({
    queryKey: queryKeys.autonomy(),
    queryFn: () => autonomy.read(),
    // Retry off so an unwired policy's 404 is visible immediately rather than
    // behind backoff. There is nothing to poll for: this state only changes
    // when somebody changes it, and every write returns the whole map.
    retry: false,
  })

  const invalidate = () => queryClient.invalidateQueries({ queryKey: queryKeys.autonomy() })
  const seed = (next: AutonomyPolicyView) => queryClient.setQueryData(queryKeys.autonomy(), next)

  const set = useMutation({
    mutationFn: ({ tool, level }: { tool: string; level: string }) => {
      if (!sessionId)
        throw new Error(
          'No session is attached, so there is nothing to record this change against.',
        )
      return autonomy.setLevel(sessionId, tool, level)
    },
    onSuccess: seed,
    onSettled: invalidate,
  })

  const allow = useMutation({
    mutationFn: () => {
      if (!sessionId)
        throw new Error(
          'No session is attached, so there is nothing to record this change against.',
        )
      return autonomy.allowAll(sessionId)
    },
    onSuccess: (result) => seed(result.policy),
    onSettled: invalidate,
  })

  return {
    policy: policy.data ?? null,
    loading: policy.isPending,
    readError: policy.error ? errorMessage(policy.error) : null,
    readNotFound: policy.error instanceof ApiError && policy.error.isNotFound,
    canWrite: sessionId !== null,
    setLevel: (tool, level) => set.mutate({ tool, level }),
    allowAll: () => allow.mutate(),
    writing: set.isPending || allow.isPending,
    // Errors are surfaced inline by both callers rather than as a toast: a
    // rejected autonomy change has to stay on screen next to the control that
    // failed, because the reader's next move is to correct the value, and a
    // toast that has faded leaves them looking at a switch whose position no
    // longer matches anything.
    writeError: set.error
      ? errorMessage(set.error)
      : allow.error
        ? errorMessage(allow.error)
        : null,
    lastAllowAll: allow.data ?? null,
  }
}
