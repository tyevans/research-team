import { create } from 'zustand'

import {
  applyNote,
  emptyExtraction,
  isExtractionFrame,
  type Extraction,
  type ExtractionFrame,
} from '@domain/knowledge/extraction.ts'
import type { ProjectId } from '@domain/shared/identifier.ts'
import { readExtractionFrame } from '@infrastructure/http/mappers.ts'

import type { ExtractionRepository } from '../ports/repositories.ts'

/** One project's extraction progress.
 *
 * Project-keyed rather than folded into the session store, because these
 * frames are addressed to a project: extraction is a project-level fact and
 * the graph is tenant-scoped by project. Filing them under whichever session
 * happened to be open would attribute a project's work to a session that may
 * not have caused it.
 *
 * The SSE connection is global, so every project's frames arrive here.
 * Filtering by project is this store's first job, not an optimisation.
 */
export interface ExtractionState {
  readonly current: Extraction | null
  readonly last: Extraction | null
  handleFrame(frame: unknown): void
  /** Rebuild from the catch-up route.
   *
   * The only recovery path there is: these frames carry no feed position, so a
   * reconnect cannot replay them, and without this a dropped connection would
   * leave the pane frozen — indistinguishable from a stalled extraction. */
  catchUp(): Promise<void>
}

export type ExtractionStore = ReturnType<typeof createExtractionStore>

/** The stages that end a job on a source row.
 *
 * Exported because `use-extraction-queue.ts` has to recognise the same set to
 * know when a document's row should be re-read, and spelling them a second
 * time is how the two would come to disagree the next time a stage is added.
 * The list is deliberately *not* every stage -- see `toStage`, which treats an
 * unrecognised one as `extracting` rather than as terminal.
 *
 * `perceived` is here and `perceiving` is not, mirroring `_TERMINAL` in
 * `interfaces/web/extraction.py`.
 *
 * What its absence cost, measured against the code rather than assumed -- an
 * earlier draft of this comment claimed the wrong one and a reviewer refuted
 * it. A stage that never reaches terminal leaves `current` uncleared, so the
 * extraction pane shows a finished transcription as a permanently running job
 * labelled `extracting`; and `isTerminalExtraction` never fires, so the queue
 * board is never re-read and the Documents header keeps saying "1 extracting
 * or queued" with a live Stop button, forever.
 *
 * What it did **not** cost, because this is the claim that was wrong: the
 * transcript row appearing in the listing does not depend on this. A finished
 * perception executes `StoreDerivedText` against the `Corpus` aggregate, every
 * `Corpus` event is pushed generically as a `Corpus` frame, and
 * `useDocumentRefresh` invalidates the listing on *any* corpus frame for the
 * project -- before the terminal frame, in fact, since the save precedes it.
 * The row would have appeared regardless. */
export const TERMINAL: readonly string[] = ['consolidated', 'failed', 'perceived']

export const createExtractionStore = ({
  extractions,
  projectId,
}: {
  extractions: ExtractionRepository
  projectId: ProjectId
}) =>
  create<ExtractionState>((set, get) => {
    const fold = (frames: readonly ExtractionFrame[]): Extraction | null =>
      frames.reduce<Extraction | null>(
        (extraction, frame) =>
          applyNote(
            // A new source restarts, here as on the live path: the buffer is
            // single-source today, but folding two documents' stages into one
            // list is the same misattribution either way.
            extraction && extraction.sourceId === frame.sourceId
              ? extraction
              : emptyExtraction(frame.sourceId),
            frame,
          ),
        null,
      )

    return {
      current: null,
      last: null,

      handleFrame(raw) {
        // Two checks, not one. `isExtractionFrame` is the cheap channel test;
        // the parse is what makes the fields trustworthy, since this arrives
        // off an unvalidated socket.
        if (!isExtractionFrame(raw)) return
        const frame = readExtractionFrame(raw)
        if (!frame) return
        if (frame.projectId !== projectId) return

        const running = get().current
        // A different document means the last one is over: keeping its stages
        // under the new source would attribute one document's work to another.
        const base =
          running && running.sourceId === frame.sourceId ? running : emptyExtraction(frame.sourceId)
        const next = applyNote(base, frame)

        if (TERMINAL.includes(frame.stage)) set({ current: null, last: next })
        else set({ current: next })
      },

      async catchUp() {
        const { current, last } = await extractions.on(projectId)
        set({ current: fold(current), last: fold(last) })
      },
    }
  })
