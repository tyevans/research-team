import type { ReactNode, RefObject } from 'react'

import { recencyOf, type ProjectRollup, type Recency } from '@domain/project/landing.ts'

import { VirtualList } from '../common/VirtualList.tsx'

/** The landing list's *structure*: which rows exist, in what order, and what
 *  identifies each one to the virtualizer.
 *
 * Split out of `ProjectList.tsx` for #49, which named two reasons that file had
 * to change. This is the first of them. It moved without being generalised, and
 * that was the finding rather than a shortcut: `VirtualList`'s only other caller
 * is `DocumentBrowser`, which is flat, fixed-height and ungrouped by an argument
 * its own comment makes, so a shared `GroupedVirtualList` would have exactly one
 * user — and would have to re-state in prose the precondition that one function
 * here guarantees by construction. See `itemKey`.
 *
 * What deliberately did not move: the row's drawing, the confirmations and the
 * queries. The file that decides which rows exist is not the file that decides
 * what a row looks like.
 */

export type Item =
  | { readonly kind: 'heading'; readonly recency: Recency; readonly count: number }
  | { readonly kind: 'project'; readonly rollup: ProjectRollup }

const HEADINGS: Readonly<Record<Recency, string>> = {
  today: 'Today',
  week: 'This week',
  older: 'Older',
  empty: 'Nothing in them yet',
}

/** The ranked list with its recency headings folded into it.
 *
 * One flat array rather than a list of groups because the whole thing is
 * virtualized: a virtualizer counts rows, and a nested structure would have to
 * be flattened for it anyway — at which point it may as well be flattened once,
 * here, where the ordering is decided.
 */
export const withHeadings = (shown: readonly ProjectRollup[], now: number): readonly Item[] => {
  const items: Item[] = []
  let current: Recency | null = null
  for (const rollup of shown) {
    const recency = recencyOf(rollup, now)
    if (recency !== current) {
      current = recency
      items.push({
        kind: 'heading',
        recency,
        count: shown.filter((other) => recencyOf(other, now) === recency).length,
      })
    }
    items.push({ kind: 'project', rollup })
  }
  return items
}

const PROJECT_ROW_HEIGHT = 108
const HEADING_HEIGHT = 30

/** What identifies a row to React *and* to the virtualizer's measurement cache.
 *
 * The second is the one that bites. Measurements are cached against whatever
 * key the virtualizer is given, and its default is the array index -- so when
 * the projects query answers and every row shifts down by a heading, index 3
 * keeps the height measured for whatever used to be at index 3. That is not
 * theoretical: it put a project row's 155px against a 33px heading and left a
 * 122px hole in the middle of the list. Keying by identity means a measurement
 * follows its row.
 *
 * **A heading's key is unique only because the input is already sorted by
 * band.** `rollups` yields projects in recency order, so `withHeadings` opens
 * each band exactly once and `h-${recency}` names one row in the whole flat
 * list. Feed it input where a band can reappear and two differently-positioned
 * rows share a key — duplicate React keys, and one measurement cell holding two
 * rows' heights, which is the 122px bug again with a rarer trigger. Said here
 * because this function is now reachable from a file that does not contain the
 * caller that establishes the ordering.
 *
 * The `h-` prefix is load-bearing for the same reason: without it a band named
 * like a `ProjectId` would share a cell with a project row. */
export const itemKey = (item: Item): string =>
  item.kind === 'heading' ? `h-${item.recency}` : String(item.rollup.project.id)

/** `renderProject` rather than the six props this forwarded before.
 *
 * The six — `openIds`, `onToggle`, `onTakeOver`, `onDelete`, `onOpen`, `busy` —
 * were passed through untouched to the row and meant nothing here; this file
 * decides which rows exist, not what happens when one is clicked. Threading
 * them also meant importing the row from `ProjectList.tsx`, which imports this
 * file: a cycle that happens to be harmless (the reference is inside a render
 * callback, so both modules are initialised by the time it resolves) and is not
 * worth relying on. One prop instead of six, and the arrow points one way.
 */
export const ProjectRows = ({
  items,
  scrollRef,
  renderProject,
}: {
  items: readonly Item[]
  scrollRef: RefObject<HTMLElement | null>
  renderProject: (rollup: ProjectRollup) => ReactNode
}) => {
  return (
    <VirtualList
      items={items}
      scrollRef={scrollRef}
      className="rows"
      getKey={(row) => itemKey(row)}
      estimate={(index) => (items[index]?.kind === 'heading' ? HEADING_HEIGHT : PROJECT_ROW_HEIGHT)}
      overscan={4}
    >
      {(row, position) => (
        <li
          ref={position.measure}
          data-index={position.index}
          className="rows-item"
          style={{
            position: 'absolute',
            top: 0,
            left: 0,
            right: 0,
            // `top` is already corrected for where this list sits inside the
            // scroll container; `VirtualList` takes its own offset back off.
            transform: `translateY(${position.top}px)`,
          }}
        >
          {row.kind === 'heading' ? (
            <h3 className="rows-heading">
              {HEADINGS[row.recency]}
              <span className="rows-heading-count">{row.count}</span>
            </h3>
          ) : (
            renderProject(row.rollup)
          )}
        </li>
      )}
    </VirtualList>
  )
}
