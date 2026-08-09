import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useVirtualizer } from '@tanstack/react-virtual'
import { useMemo, useRef, useState } from 'react'
import clsx from 'clsx'

import { queryKeys } from '@application/queries/keys.ts'
import { useContainer } from '@app/container-context.tsx'
import { documentLabel, isDropped, type DocumentSummary } from '@domain/research/document.ts'
import type { ProjectId, SourceId } from '@domain/shared/identifier.ts'

import { Drawer } from '../common/Drawer.tsx'
import { EmptyState, ErrorBox, Loading } from '../common/primitives.tsx'
import { useFrameRefresh } from '../shell/use-frame-refresh.ts'
import { DocumentReader } from './DocumentReader.tsx'

const ROW_HEIGHT = 52

/** Every source this project has stored, virtualized so a corpus of hundreds
 *  of papers costs the same to render as one of ten.
 *
 * Dropped documents stay in the list rather than being filtered out -- the
 * corpus keeps them as an audit trail, and hiding them here would misreport
 * what the project holds. They render with their reason and a visual mark
 * instead.
 *
 * Sorting and filtering are left as a `useMemo` over the fetched array
 * rather than a table library: the whole point of trying `react-virtual`
 * first is that a plain list is all a document browser needs.
 *
 * Refreshed off the live feed, like `TopicList` and for the same reason: a
 * document being stored *is* a log entry, so the frames that change this list
 * are already on the connection the shell holds open and a poll would be a
 * second delivery path for something already delivered. Without
 * `useDocumentRefresh` below, this pane changed only on a reload -- which is
 * what a reader watching a session fetch three papers actually saw. */
export const DocumentList = ({ projectId }: { projectId: ProjectId }) => {
  const { documents } = useContainer()
  const [reading, setReading] = useState<SourceId | null>(null)
  const [query_, setQuery_] = useState('')
  const scrollRef = useRef<HTMLDivElement>(null)

  const query = useQuery({
    queryKey: queryKeys.documents(projectId),
    queryFn: () => documents.list(projectId),
  })
  useDocumentRefresh(projectId)

  const filtered = useMemo(() => {
    const rows = query.data ?? []
    const needle = query_.trim().toLowerCase()
    if (!needle) return rows
    return rows.filter((row) => documentLabel(row).toLowerCase().includes(needle))
  }, [query.data, query_])

  // React Compiler cannot memoize `useVirtualizer`'s returned functions --
  // that is the library's own documented shape, not a bug in this
  // component -- so it skips optimizing this component rather than risk a
  // stale virtualizer. That trade is exactly right here: this component
  // does no other expensive work worth memoizing.
  // eslint-disable-next-line react-hooks/incompatible-library
  const virtualizer = useVirtualizer({
    count: filtered.length,
    getScrollElement: () => scrollRef.current,
    // An estimate now, not the truth. `ROW_HEIGHT` was treated as exact, and a
    // title that wrapped to two lines -- most of them, in a 340px rail -- drew
    // over the row beneath it. Each row reports its real height through
    // `measureElement` below, and this is only what the virtualizer assumes
    // for rows it has not drawn yet.
    estimateSize: () => ROW_HEIGHT,
    // Measured, except when the environment has no layout to measure. jsdom
    // reports every height as 0, and a measured 0 would collapse the list to
    // nothing and take the rows with it -- so a zero measurement falls back to
    // the estimate, which is what keeps this component testable at all.
    measureElement: (element) => element.getBoundingClientRect().height || ROW_HEIGHT,
    overscan: 8,
  })

  if (query.isPending) return <Loading what="documents" />

  if (query.isError) {
    return (
      <ErrorBox
        title="Could not read this project's documents"
        message={query.error instanceof Error ? query.error.message : String(query.error)}
        onRetry={() => void query.refetch()}
      />
    )
  }

  if (query.data.length === 0) {
    return <EmptyState title="No documents" detail="Nothing has been stored in this corpus yet." />
  }

  return (
    <div className="document-browser">
      <input
        type="search"
        className="input document-filter"
        placeholder="Filter documents"
        value={query_}
        onChange={(event) => setQuery_(event.target.value)}
        aria-label="Filter documents"
      />
      <div ref={scrollRef} className="document-list-scroll">
        <ul
          className="document-list"
          style={{ height: virtualizer.getTotalSize(), position: 'relative' }}
        >
          {virtualizer.getVirtualItems().map((item) => {
            const row = filtered[item.index]
            if (!row) return null
            return (
              <DocumentRow
                key={row.sourceId}
                document={row}
                index={item.index}
                top={item.start}
                measure={virtualizer.measureElement}
                onOpen={() => setReading(row.sourceId)}
              />
            )
          })}
        </ul>
      </div>
      {/* Over the page, not below the list. The list lives in a 340px rail,
          and a document is a wall of prose -- read in that column it was a
          few words per line under a list that had been pushed up out of the
          way. The drawer is the console's existing answer to "read this
          without losing where you were", and a source is exactly that kind of
          thing: you open one, read it, and go back to the graph you were
          looking at. */}
      {reading ? (
        <Drawer
          title={readingLabel(filtered, reading)}
          label={`Reading ${readingLabel(filtered, reading)}`}
          onClose={() => setReading(null)}
        >
          <DocumentReader projectId={projectId} sourceId={reading} />
        </Drawer>
      ) : null}
    </div>
  )
}

/** The open document's title, for the drawer's heading.
 *
 * Taken from the row that opened it rather than waited for from the reader's
 * own fetch: the heading is on screen while that request is in flight, and a
 * drawer that opens with an empty title and fills it in a moment later reads
 * as a bug. Falls back to the id, which is all the list can offer if the row
 * has been filtered out from under the open document.
 */
const readingLabel = (rows: readonly DocumentSummary[], sourceId: SourceId): string => {
  const row = rows.find((candidate) => candidate.sourceId === sourceId)
  return row ? documentLabel(row) : String(sourceId)
}

const DocumentRow = ({
  document,
  index,
  top,
  measure,
  onOpen,
}: {
  document: DocumentSummary
  /** The virtualizer reads this back off the DOM node to know which row it
   *  just measured, so it has to be on the element `measure` is given. */
  index: number
  top: number
  measure: (element: HTMLElement | null) => void
  onOpen: () => void
}) => (
  <li
    ref={measure}
    data-index={index}
    className={clsx('document-row', isDropped(document) && 'document-dropped')}
    // Positioned by transform rather than `top`, and with no height at all:
    // the row is now as tall as its content, and `translateY` is what the
    // virtualizer's own measurement expects to find -- a `top` offset would be
    // counted twice once a row reports a height different from the estimate.
    style={{
      position: 'absolute',
      top: 0,
      left: 0,
      right: 0,
      transform: `translateY(${top}px)`,
    }}
  >
    <button type="button" className="document-row-open" onClick={onOpen}>
      <span className="document-row-title">{documentLabel(document)}</span>
      <span className="document-row-meta">{document.charCount} chars</span>
      {isDropped(document) ? (
        <span className="document-row-dropped-reason">Dropped: {document.droppedReason}</span>
      ) : null}
    </button>
  </li>
)

/** Re-read this project's sources when its corpus moves.
 *
 * Scoped to `projectId` off the frame's own project id rather than by
 * refreshing on everything and letting the read discover nothing changed --
 * a corpus frame carries one, unlike a topic frame, because a corpus shares
 * its project's UUID and the server gets the answer for free.
 *
 * Only corpus frames. A graph frame rides the same ingest and is deliberately
 * ignored: it would double every read and answer nothing the corpus frame did
 * not. A log frame is ignored the way `TopicList` ignores it -- the session
 * tree already refetches on every one, and this list doing the same would
 * re-read the corpus on every token of every turn. Both are asserted.
 *
 * One key, not a prefix: a stored document changes the list. It does not
 * change the *text* of a document already open in the reader, which is
 * immutable once stored, so `queryKeys.document` is left alone.
 */
const useDocumentRefresh = (projectId: ProjectId) => {
  const queryClient = useQueryClient()

  useFrameRefresh(
    // Always on: this hook lives in the pane it refreshes, so being mounted is
    // the "on screen" test `useTreeRefresh` needs its flag for.
    true,
    (frame) => frame.kind === 'corpus' && frame.projectId === projectId,
    () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.documents(projectId) })
    },
  )
}
