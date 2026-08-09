import { useQuery } from '@tanstack/react-query'
import { useVirtualizer } from '@tanstack/react-virtual'
import { useLayoutEffect, useMemo, useRef, useState, type RefObject } from 'react'

import { queryKeys } from '@application/queries/keys.ts'
import { useContainer } from '@app/container-context.tsx'
import { summariesAsForest } from '@infrastructure/http/mappers.ts'
import { flatten, looseSessions } from '@domain/project/landing.ts'
import type { ForkNode, SessionSummary } from '@domain/session/session.ts'
import { errorMessage } from '@application/ports/errors.ts'

import { EmptyState, ErrorBox } from '../common/primitives.tsx'
import { SessionRow } from './SessionRow.tsx'
import { SkeletonRows } from './Skeletons.tsx'

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

/** Sessions belonging to no project.
 *
 * Flat and newest-first rather than nested: lineage among orphans is a chip on
 * the row, because these sessions have nothing to do with each other and a
 * forest of them buries this morning's under a parent from March. Lineage that
 * matters lives inside a project, where it is a relationship between rows the
 * reader can see at once.
 */
export const LooseSessions = ({ scrollRef }: { scrollRef: RefObject<HTMLElement | null> }) => {
  const { all, isPending, error, refetch } = useSessionForest()
  const rows = useMemo(() => looseSessions(all), [all])

  if (isPending) return <SkeletonRows count={3} />
  if (error) {
    return (
      <ErrorBox
        title="Could not load the session tree"
        message={errorMessage(error)}
        onRetry={refetch}
      />
    )
  }
  if (rows.length === 0) {
    return (
      <EmptyState
        title="Every session belongs to a project."
        detail="Sessions started outside one would appear here."
      />
    )
  }

  return <LooseList rows={rows} scrollRef={scrollRef} />
}

const ROW_HEIGHT = 62

const LooseList = ({
  rows,
  scrollRef,
}: {
  rows: readonly SessionSummary[]
  scrollRef: RefObject<HTMLElement | null>
}) => {
  const listRef = useRef<HTMLUListElement>(null)
  const [listTop, setListTop] = useState(0)

  // See `ProjectList` for why this and `getItemKey` below are needed: the
  // list does not start at the top of the scroll container, and a
  // measurement cached against an array index follows the wrong row.
  // Deliberately without a dependency list: what moves this list down the page
  // is everything above it -- the purpose line wrapping, the action bar, the
  // new-project form opening -- and there is no value to depend on that
  // captures "the layout above changed". Re-reading after every render is the
  // honest way to track it, and the update is a no-op when the number has not
  // changed, so React bails out rather than looping.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useLayoutEffect(() => {
    const element = listRef.current
    if (element)
      setListTop((current) => (current === element.offsetTop ? current : element.offsetTop))
  })

  // React Compiler cannot memoize `useVirtualizer`'s returned functions --
  // the library's own documented shape, not a bug here -- so it skips this
  // component rather than risk a stale virtualizer. See `DocumentList`, which
  // made the same trade for the same reason.
  // eslint-disable-next-line react-hooks/incompatible-library
  const virtualizer = useVirtualizer({
    count: rows.length,
    getScrollElement: () => scrollRef.current,
    getItemKey: (index) => String(rows[index]!.id),
    scrollMargin: listTop,
    estimateSize: () => ROW_HEIGHT,
    // A measured 0 is jsdom having no layout, not a row of no height, and
    // trusting it would collapse the list and take every row with it.
    measureElement: (element) => element.getBoundingClientRect().height || ROW_HEIGHT,
    overscan: 6,
  })

  return (
    <ul
      ref={listRef}
      className="rows"
      style={{ height: virtualizer.getTotalSize(), position: 'relative' }}
    >
      {virtualizer.getVirtualItems().map((item) => {
        const row = rows[item.index]
        if (!row) return null
        return (
          <li
            key={row.id}
            ref={virtualizer.measureElement}
            data-index={item.index}
            className="rows-item"
            // Transform rather than `top`, and no inline height: a measured row
            // whose height differs from the estimate would otherwise be offset
            // twice. `DocumentList` documents the same shape.
            style={{
              position: 'absolute',
              top: 0,
              left: 0,
              right: 0,
              transform: `translateY(${item.start - virtualizer.options.scrollMargin}px)`,
            }}
          >
            <SessionRow session={row} />
          </li>
        )
      })}
    </ul>
  )
}
