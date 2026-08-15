import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useMemo, useState } from 'react'

import { notify } from '@application/notifications/toast-store.ts'
import { errorMessage } from '@application/ports/errors.ts'
import { queryKeys } from '@application/queries/keys.ts'
import {
  useCancelExtraction,
  useExtractAll,
  useExtractDocument,
  useExtractionQueue,
} from '@application/research/use-extraction-queue.ts'
import { useContainer } from '@app/container-context.tsx'
import { documentLabel, type DocumentSummary } from '@domain/research/document.ts'
import { unextractedCount } from '@domain/research/extraction-queue.ts'
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
  const [adding, setAdding] = useState(false)

  const query = useQuery({
    queryKey: queryKeys.documents(projectId),
    queryFn: () => documents.list(projectId),
  })
  useDocumentRefresh(projectId)

  // Read unconditionally rather than only once something has been pressed, for
  // `useTopicQueue`'s reason: the whole point of a catch-up route is a tab that
  // arrived *after* the queue started, which cannot be detected without asking.
  const { board } = useExtractionQueue(projectId)
  const extracting = useExtractDocument(projectId)
  const extractingAll = useExtractAll(projectId)
  const cancelling = useCancelExtraction(projectId)

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
    adding,
    onAddClose: () => setAdding(false),
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
      // The *unfiltered* corpus, deliberately: "extract all unextracted" is a
      // project-level action the server computes over everything, and a count
      // taken from the filtered rows would promise to extract what the reader
      // can see while the press extracted more.
      extractableCount: unextractedCount(query.data ?? [], board),
      queue: board,
      queueSize: board.queued.length + (board.running === null ? 0 : 1),
      busy: extracting.isPending || extractingAll.isPending,
      cancelling: cancelling.isPending,
      onExtract: (sourceId: SourceId) => {
        extracting.mutate(sourceId, {
          // Reported off the answer rather than off the press. `queued: false`
          // means the queue already holds this document, which is not an error
          // and not a start -- and a toast that said "queued" either way would
          // be the lie the server shaped its 202 to let the client avoid.
          onSuccess: (queued) => {
            notify(queued ? 'Queued for extraction' : 'Already queued for extraction')
          },
          onError: (error) => {
            notify(errorMessage(error), 'bad')
          },
        })
      },
      onExtractAll: () => {
        extractingAll.mutate(undefined, {
          // The server's count, not `extractableCount`: it recomputes the set
          // at press time and refuses what the queue already holds, so the two
          // differ exactly when a previous press is still draining.
          onSuccess: (queued) => {
            notify(
              queued === 0
                ? 'Nothing left to extract'
                : `Queued ${String(queued)} document${queued === 1 ? '' : 's'} for extraction`,
            )
          },
          onError: (error) => {
            notify(errorMessage(error), 'bad')
          },
        })
      },
      onCancelExtraction: () => {
        cancelling.mutate(undefined, {
          onSuccess: (cancelled) => {
            notify(`Stopped ${String(cancelled)} extraction${cancelled === 1 ? '' : 's'}`)
          },
          onError: (error) => {
            notify(errorMessage(error), 'bad')
          },
        })
      },
      onAdd: () => setAdding(true),
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
 * `useExtractionQueue` invalidates this same key on a *terminal extraction*
 * frame, and that is not a second violation of the rule above: a document
 * extracted from the corpus days after it was stored has no corpus frame
 * beside it, and its row's `extracted` flag has just changed. The rule this
 * paragraph documents is "no frame that only restates another one", not "one
 * invalidator" -- and it is why the extraction subscription lives beside the
 * queue it also refreshes rather than being folded in here.
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
