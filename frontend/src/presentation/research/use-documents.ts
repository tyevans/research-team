import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useMemo, useState } from 'react'

import { queryKeys } from '@application/queries/keys.ts'
import { useContainer } from '@app/container-context.tsx'
import { documentLabel, type DocumentSummary } from '@domain/research/document.ts'
import type { ProjectId, SourceId } from '@domain/shared/identifier.ts'

import { useFrameRefresh } from '../shell/use-frame-refresh.ts'

/** The corpus, the filter over it, and which document the route says is open.
 *
 * The filter stays local state and the open document does not, which is the
 * same line `ProjectView` draws for its tabs: a filter is how you are looking,
 * an open document is what you are looking at, and only the second is worth
 * sending to somebody.
 *
 * Refreshed off the live feed, like the topic queue and for the same reason: a
 * document being stored *is* a log entry, so the frames that change this list
 * are already on the connection the shell holds open and a poll would be a
 * second delivery path for something already delivered. Without
 * `useDocumentRefresh` below, this pane changed only on a reload -- which is
 * what a reader watching a session fetch three papers actually saw.
 */
export const useDocuments = (
  projectId: ProjectId,
  /** Which document is open, owned by the route.
   *
   * It was `useState` here, and that was the whole of a shipped broken link:
   * `CitationList` writes `#/p/<id>/doc/<sourceId>`, its comment says the point
   * is to keep the reader on the project page, and following it opened the
   * Documents tab with nothing read -- the reader had to find the source by
   * hand in an unfiltered list. State cannot be linked to, and this pane's one
   * inbound link is the reason the address bar has to own it.
   *
   * `null` for both is a real caller: `DocumentList` outside a routed page has
   * no address to write to. It then opens nothing, which is honest -- a drawer
   * that opens and cannot be linked back to is the state this replaces. */
  open: SourceId | null = null,
  onOpen: (sourceId: SourceId | null) => void = () => {},
) => {
  const { documents } = useContainer()
  const [filter, setFilter] = useState('')

  const query = useQuery({
    queryKey: queryKeys.documents(projectId),
    queryFn: () => documents.list(projectId),
  })
  useDocumentRefresh(projectId)

  const filtered = useMemo(() => {
    const rows = query.data ?? []
    const needle = filter.trim().toLowerCase()
    if (!needle) return rows
    return rows.filter((row) => documentLabel(row).toLowerCase().includes(needle))
  }, [query.data, filter])

  return {
    query,
    reading: open,
    onClose: () => {
      onOpen(null)
    },
    /** The open document's title, for the drawer's heading.
     *
     * Taken from the row that opened it rather than waited for from the
     * reader's own fetch: the heading is on screen while that request is in
     * flight, and a drawer that opens with an empty title and fills it in a
     * moment later reads as a bug. Falls back to the id, which is all the list
     * can offer if the row has been filtered out from under the open document.
     */
    readingLabel: (sourceId: SourceId): string => label(query.data ?? [], sourceId),
    browser: {
      documents: filtered,
      total: query.data?.length ?? 0,
      filter,
      onFilterChange: setFilter,
      onOpen,
    },
  }
}

const label = (rows: readonly DocumentSummary[], sourceId: SourceId): string => {
  const row = rows.find((candidate) => candidate.sourceId === sourceId)
  return row ? documentLabel(row) : String(sourceId)
}

/** Re-read this project's sources when its corpus moves.
 *
 * Scoped to `projectId` off the frame's own project id rather than by
 * refreshing on everything and letting the read discover nothing changed -- a
 * corpus frame carries one, unlike a topic frame, because a corpus shares its
 * project's UUID and the server gets the answer for free.
 *
 * Only corpus frames. A graph frame rides the same ingest and is deliberately
 * ignored: it would double every read and answer nothing the corpus frame did
 * not. A log frame is ignored the way the topic queue ignores it -- the
 * session tree already refetches on every one, and this list doing the same
 * would re-read the corpus on every token of every turn. Both are asserted.
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
