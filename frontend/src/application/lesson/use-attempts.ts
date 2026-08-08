import { useQuery } from '@tanstack/react-query'
import { useCallback, useState } from 'react'

import { errorMessage } from '@application/ports/errors.ts'
import { queryKeys } from '@application/queries/keys.ts'
import { useContainer } from '@app/container-context.tsx'
import {
  freshAttempt,
  mcqResponse,
  resetAttempt as clearAttempt,
  withStoredProgress,
  type AttemptResponse,
  type AttemptState,
} from '@domain/lesson/attempt.ts'
import type { ComponentBlock } from '@domain/lesson/document.ts'
import type { ScrubPoint } from '@domain/session/scrub-point.ts'
import type { FilePath } from '@domain/shared/file-path.ts'
import type { ComponentId, SessionId } from '@domain/shared/identifier.ts'

/** One shared empty map, so "this learner has edited nothing" is a stable
 *  identity and not a new object every render. */
const EMPTY: ReadonlyMap<ComponentId, AttemptState> = new Map()

export interface AttemptsApi {
  stateFor(block: ComponentBlock): AttemptState
  update(block: ComponentBlock, change: Partial<AttemptState>): void
  submit(block: ComponentBlock, response: AttemptResponse): void
  reset(block: ComponentBlock): void
  saveChecklist(block: ComponentBlock, checked: readonly number[]): void
  mcqResponse: typeof mcqResponse
}

/** Every widget's state for one open file, and the two calls that change it on
 *  the server.
 *
 * Scoped to a file on purpose. Answers typed into the file being closed are not
 * answers to the next one, and a stale verdict shown against a different
 * document would be worse than losing the attempt — so this resets when the
 * path changes rather than accumulating across a session.
 *
 * Nothing here grades. `submit` posts and renders what comes back; the browser
 * was never given the key.
 */
export const useAttempts = (
  sessionId: SessionId,
  path: FilePath | null,
  at: ScrubPoint,
): AttemptsApi => {
  const { lessons } = useContainer()

  /** Only what this learner has typed *here*, stamped with the document it was
   *  typed against.
   *
   * Carrying the key rather than clearing the map in an effect is what makes
   * "a different document is a different set of answers" true on the render
   * that changes documents, instead of one render later — the effect version
   * painted the previous file's answers against the new file first, and only
   * then blanked them. */
  const documentKey = `${sessionId}:${path?.value ?? ''}`
  const [edits, setEdits] = useState<{
    key: string
    byComponent: ReadonlyMap<ComponentId, AttemptState>
  }>({ key: documentKey, byComponent: EMPTY })

  /** Two halves of one rule. The guard makes the new document blank on the
   *  render that changes documents; the reset throws the old map away rather
   *  than leaving it to be found again.
   *
   * Without the reset, closing a file and reopening it restored answers — but
   * only if no third file had been touched in between, since the map holds one
   * key at a time. Arbitrary is worse than either answer, so this picks the one
   * the learner was already told: those answers are gone. */
  const mine = edits.key === documentKey ? edits.byComponent : EMPTY
  if (edits.key !== documentKey) setEdits({ key: documentKey, byComponent: EMPTY })

  /** What this learner has already done, folded back in.
   *
   * Fetched beside the parse rather than after it, because they are one render:
   * sequencing them would flash an unanswered document before filling in
   * answers the learner already gave. A failure costs nothing — the lesson is
   * perfectly readable, the answers just start blank. */
  const progress = useQuery({
    queryKey: path ? queryKeys.lessonProgress(sessionId, path) : ['lesson-progress', 'none'],
    queryFn: () => lessons.progress(sessionId, path!),
    enabled: path !== null,
    retry: false,
  })

  /** The server's record of a component, as an attempt state.
   *
   * Read at the point of use rather than merged into state when it arrives. The
   * merge had an ordering bug in it: progress is fetched, so it can land after
   * the learner has already started answering, and folding it in at that moment
   * overwrote what they had just typed. Derived, the local edit simply wins. */
  const storedAttempt = useCallback(
    (id: ComponentId) => {
      const record = progress.data?.get(id)
      return record ? withStoredProgress(freshAttempt(), record) : freshAttempt()
    },
    [progress.data],
  )

  const stateFor = useCallback(
    (block: ComponentBlock) => mine.get(block.id) ?? storedAttempt(block.id),
    [mine, storedAttempt],
  )

  const write = useCallback(
    (id: ComponentId, change: (previous: AttemptState) => AttemptState) => {
      setEdits((current) => {
        const base = current.key === documentKey ? current.byComponent : EMPTY
        const next = new Map(base)
        next.set(id, change(base.get(id) ?? storedAttempt(id)))
        return { key: documentKey, byComponent: next }
      })
    },
    [documentKey, storedAttempt],
  )

  const submit = useCallback(
    (block: ComponentBlock, response: AttemptResponse) => {
      if (!path) return
      if (stateFor(block).busy) return
      write(block.id, (previous) => ({ ...previous, busy: true, error: null }))
      void lessons
        .submitAttempt(sessionId, { path, componentId: block.id, response, at })
        .then((verdict) => {
          write(block.id, (previous) => ({
            ...previous,
            busy: false,
            verdict,
            // The server counts attempts, not the client: a reload, a second
            // tab and a retry all go through it, and a client-side tally would
            // disagree with the log the moment any of those happened.
            attempts: verdict.progress?.attempts ?? previous.attempts,
            previouslyCorrect: verdict.progress?.correct ?? previous.previouslyCorrect,
          }))
        })
        .catch((error: unknown) => {
          write(block.id, (previous) => ({
            ...previous,
            busy: false,
            error: `Could not check that answer: ${errorMessage(error)}`,
          }))
        })
    },
    [at, lessons, path, sessionId, stateFor, write],
  )

  /** Sends the whole set of ticks, not the one that changed.
   *
   * Absolute state means a dropped request costs one stale render rather than a
   * box that is ticked in the log and clear on the screen forever — and the
   * next tick repairs it. The failure is surfaced rather than swallowed,
   * because a checklist that says "saved as you go" and did not is worse than
   * one that never promised. */
  const saveChecklist = useCallback(
    (block: ComponentBlock, checked: readonly number[]) => {
      if (!path) return
      void lessons
        .saveChecklist(sessionId, { path, componentId: block.id, checked, at })
        .then(() => write(block.id, (previous) => ({ ...previous, saveError: null })))
        .catch((error: unknown) =>
          write(block.id, (previous) => ({ ...previous, saveError: errorMessage(error) })),
        )
    },
    [at, lessons, path, sessionId, write],
  )

  return {
    stateFor,
    update: useCallback(
      (block, change) => write(block.id, (previous) => ({ ...previous, ...change })),
      [write],
    ),
    submit,
    reset: useCallback((block) => write(block.id, clearAttempt), [write]),
    saveChecklist,
    mcqResponse,
  }
}
