import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { useContainer } from '@app/container-context.tsx'
import { TERMINAL } from '@application/knowledge/extraction-store.ts'
import type { FeedFrame } from '@application/ports/event-stream.ts'
import { queryKeys } from '@application/queries/keys.ts'
import { emptyExtractionQueue } from '@domain/research/extraction-queue.ts'
import type { ProjectId, SourceId } from '@domain/shared/identifier.ts'
import { readExtractionFrame } from '@infrastructure/http/mappers.ts'

import { useFrameRefresh } from '../../presentation/shell/use-frame-refresh.ts'

/** What this project is extracting, what is waiting, and how the last ones
 *  went.
 *
 * Modelled on `useDispatchBoard` and different from it in one way that matters:
 * the extraction queue publishes *no frames of its own*. `/dispatch` has a
 * `Dispatch` frame per transition; this queue has none, because
 * `ExtractionActivity` already carries the running item's progress and nobody
 * wanted a second feed saying the same thing. So the only announcement this
 * hook can hear is the running extraction reaching a terminal stage — which
 * tells it a document *left* the queue, and never that one joined it.
 *
 * The consequence, said plainly rather than discovered later: a document
 * queued behind five others shows as queued the moment the press that queued
 * it invalidates this key, and thereafter only when something finishes. Nobody
 * else can queue a document without going through a client that invalidates,
 * so the gap is a second tab, and the cost of closing it would be a poll on
 * every open Documents pane. That trade is why this is not polled.
 *
 * Invalidated rather than folded, for `useDispatchBoard`'s reason: folding a
 * terminal frame in would mean restating the server's bookkeeping here — that
 * `consolidated` moves an entry from `running` to `finished` with a count on
 * it, that `failed` carries a detail this side never sees on the frame at all
 * — and the two would disagree the first time either changed.
 */
export const useExtractionQueue = (projectId: ProjectId) => {
  const { documents } = useContainer()
  const queryClient = useQueryClient()

  const query = useQuery({
    queryKey: queryKeys.extractionQueue(projectId),
    queryFn: () => documents.extractionQueue(projectId),
  })

  useFrameRefresh(true, isTerminalExtraction(projectId), () => {
    void queryClient.invalidateQueries({ queryKey: queryKeys.extractionQueue(projectId) })
    // And the corpus, because a finished extraction is exactly what flips a
    // row's `extracted` flag — the listing is where that flag lives, and
    // without this the row would keep offering "Extract" until a reload.
    //
    // This is the second invalidator over `documents(projectId)`, and it does
    // not contradict `useDocumentRefresh`'s refusal to refresh on *graph*
    // frames: that refusal is about a frame which announces nothing the
    // corpus frame beside it does not already announce. A terminal extraction
    // frame has no corpus frame beside it — storing a document and extracting
    // it are separate acts, and only the first appends to the corpus. The
    // debounce in `useFrameRefresh` collapses the burst either way, so the
    // cost of the overlap is bounded at one extra read per extraction.
    void queryClient.invalidateQueries({ queryKey: queryKeys.documents(projectId) })
  })

  return {
    // Never `undefined`: every consumer here asks the board a question about
    // some row, and an empty queue and a queue not yet read give the same
    // honest answer — nothing is known to be extracting.
    board: query.data ?? emptyExtractionQueue,
    isPending: query.isPending,
  }
}

/** Decoded here rather than in `decodeFrame`, which routes the payload
 *  undecoded on purpose (see its comment) — this is the same two-step
 *  `extraction-store.ts` does: the cheap channel test, then the parse that
 *  makes the fields trustworthy, because the frame arrives off an unvalidated
 *  socket.
 *
 * Only terminal stages. Refreshing on every `extracting` note would be a read
 * per progress tick for a board that has not moved: the running document is
 * still the running document until it stops being one. */
const isTerminalExtraction =
  (projectId: ProjectId) =>
  (frame: FeedFrame): boolean => {
    if (frame.kind !== 'extraction') return false
    const decoded = readExtractionFrame(frame.payload)
    return decoded !== null && decoded.projectId === projectId && TERMINAL.includes(decoded.stage)
  }

/** Queue one document for extraction.
 *
 * The mutation answers whether *this* press took it on; `false` means the
 * queue already held it. Reported rather than swallowed so the caller can
 * avoid saying "started" about something it did not start — the reason the
 * server answers 202 with a boolean instead of 409.
 *
 * Invalidated on success rather than written into the cache, following
 * `useDispatchTopic`: by the time the 202 lands the server may already have
 * started it, and writing the stale answer in would show a position the next
 * read corrects.
 */
export const useExtractDocument = (projectId: ProjectId) => {
  const { documents } = useContainer()
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: (sourceId: SourceId) => documents.extract(projectId, sourceId),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: queryKeys.extractionQueue(projectId) }),
  })
}

/** Queue one stored medium to be perceived into a text source.
 *
 * Beside the extract mutations rather than in `use-document-writes.ts`,
 * because it is a queue operation and not a corpus write: it queues into the
 * same place `extract` does and reports through the same `ExtractionActivity`
 * frames, so the hook that has to know about that queue is this file.
 *
 * Invalidates only the queue, deliberately. The listing does not change until
 * the perception *finishes* and writes the derived source, which is minutes
 * later and announced by the terminal `perceived` frame -- `useExtractionQueue`
 * above invalidates the corpus on that, and that is the read which makes the
 * transcript row appear. Invalidating the listing here as well would be a read
 * of a corpus that provably has not moved yet.
 */
export const usePerceiveDocument = (projectId: ProjectId) => {
  const { documents } = useContainer()
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: (sourceId: SourceId) => documents.perceive(projectId, sourceId),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: queryKeys.extractionQueue(projectId) }),
  })
}

/** Queue every stored document that has no graph yet. */
export const useExtractAll = (projectId: ProjectId) => {
  const { documents } = useContainer()
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: () => documents.extractAll(projectId),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: queryKeys.extractionQueue(projectId) }),
  })
}

/** Stop the running extraction and drop everything waiting. */
export const useCancelExtraction = (projectId: ProjectId) => {
  const { documents } = useContainer()
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: () => documents.cancelExtraction(projectId),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: queryKeys.extractionQueue(projectId) }),
  })
}
