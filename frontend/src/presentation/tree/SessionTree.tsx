import { useQuery } from '@tanstack/react-query'
import { useMemo } from 'react'

import { queryKeys } from '@application/queries/keys.ts'
import { useContainer } from '@app/container-context.tsx'
import { summariesAsForest } from '@infrastructure/http/mappers.ts'
import { flatten } from '@domain/project/landing.ts'
import type { ForkNode, SessionSummary } from '@domain/session/session.ts'

/** Every session, as the fork tree it actually is.
 *
 * Two sources, deliberately. `/api/tree` is the shape; `/api/sessions` is the
 * per-row detail *and* the fallback — if the tree projection has drifted and
 * answers empty while sessions plainly exist, the flat list is rendered
 * instead. A truthful degradation beats a "no sessions yet" that is a lie.
 */
export const useSessionForest = (): {
  readonly roots: readonly ForkNode[]
  readonly all: readonly SessionSummary[]
  readonly isPending: boolean
  readonly error: unknown
  readonly refetch: () => void
} => {
  const { sessions } = useContainer()

  const tree = useQuery({
    queryKey: queryKeys.tree(),
    queryFn: () => sessions.tree(),
  })
  const list = useQuery({
    queryKey: queryKeys.sessions(),
    queryFn: () => sessions.list(),
  })

  const summaries = useMemo(() => list.data ?? [], [list.data])
  const roots = useMemo(() => {
    const fromTree = tree.data ?? []
    return fromTree.length > 0 ? fromTree : summaries.length > 0 ? summariesAsForest(summaries) : []
  }, [tree.data, summaries])

  /** Every row, from whichever source has more of them.
   *
   * The two projections can disagree about *membership*, not only about a
   * field, and grouping sessions under projects needs the fuller set: a
   * project whose only session the tree has not caught up with would otherwise
   * read "0 sessions" beside a session list that plainly has one. */
  const all = useMemo(() => {
    const flat = flatten(roots)
    return flat.length >= summaries.length ? flat : summaries
  }, [roots, summaries])

  return {
    all,
    roots,
    isPending: tree.isPending,
    error: tree.isError ? tree.error : null,
    refetch: () => void tree.refetch(),
  }
}
