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
  type ItemProgress,
  type Verdict,
} from '@domain/lesson/attempt.ts'
import type { ComponentBlock } from '@domain/lesson/document.ts'
import type { ScrubPoint } from '@domain/session/scrub-point.ts'
import type { FilePath } from '@domain/shared/file-path.ts'
import type { ComponentId, SessionId } from '@domain/shared/identifier.ts'

/** One shared empty map, so "this learner has edited nothing" is a stable
 *  identity and not a new object every render. */
const EMPTY: ReadonlyMap<ComponentId, AttemptState> = new Map()

export interface AttemptsApi {
  readonly stateFor: (block: ComponentBlock) => AttemptState
  readonly update: (block: ComponentBlock, change: Partial<AttemptState>) => void
  readonly submit: (block: ComponentBlock, response: AttemptResponse) => Promise<void>
  readonly reset: (block: ComponentBlock) => void
  readonly saveChecklist?: (block: ComponentBlock, checked: readonly number[]) => void
  readonly mcqResponse: typeof mcqResponse
}

/** What one caller of the shared machine supplies: how to read history, and
 *  the one call that changes anything on the server.
 *
 * `stored` is a value, not a function, because the two callers differ in
 * exactly this: a lesson has a query behind it that resolves after the first
 * render, and an ask has nothing to fetch at all. Handing the machine a
 * derived value rather than a fetcher means the ask caller passes `null` once
 * and is done, instead of writing a query that always answers the same empty
 * map. */
interface AttemptPorts {
  /** What this reader has already done, or null where nothing is recorded.
   *  The ask surface passes null: an ask records no attempt, so there is no
   *  history to fold in and a loader would be a request that always answers
   *  the same empty map. */
  readonly stored: ReadonlyMap<ComponentId, ItemProgress> | null
  readonly submit: (block: ComponentBlock, response: AttemptResponse) => Promise<Verdict>
  /** Absent where checklists cannot persist. A widget whose save is a no-op
   *  should not offer one, so `Checklist` reads this to decide. */
  readonly saveChecklist?: (block: ComponentBlock, checked: readonly number[]) => Promise<void>
}

/** Every widget's state for one document, and the calls that change it on the
 *  server.
 *
 * Scoped to a document on purpose. Answers typed into the document being
 * closed are not answers to the next one, and a stale verdict shown against a
 * different document would be worse than losing the attempt — so this resets
 * when `documentKey` changes rather than accumulating across a session.
 *
 * Nothing here grades. `submit` posts and renders what comes back; the browser
 * was never given the key.
 *
 * Exported for `useAskAttempts` alone — `useAttempts` below and it are the
 * two callers, and both close over the effects this needs rather than
 * exposing them to a third. Nothing else in the tree should reach for this
 * directly; go through one of the two.
 */
export const useAttemptMachine = (documentKey: string, ports: AttemptPorts): AttemptsApi => {
  /** Only what this learner has typed *here*, stamped with the document it was
   *  typed against.
   *
   * Carrying the key rather than clearing the map in an effect is what makes
   * "a different document is a different set of answers" true on the render
   * that changes documents, instead of one render later — the effect version
   * painted the previous document's answers against the new one first, and
   * only then blanked them. */
  const [edits, setEdits] = useState<{
    key: string
    byComponent: ReadonlyMap<ComponentId, AttemptState>
  }>({ key: documentKey, byComponent: EMPTY })

  /** Two halves of one rule. The guard makes the new document blank on the
   *  render that changes documents; the reset throws the old map away rather
   *  than leaving it to be found again.
   *
   * Without the reset, closing a document and reopening it restored answers —
   * but only if no third document had been touched in between, since the map
   * holds one key at a time. Arbitrary is worse than either answer, so this
   * picks the one the learner was already told: those answers are gone. */
  const mine = edits.key === documentKey ? edits.byComponent : EMPTY
  if (edits.key !== documentKey) setEdits({ key: documentKey, byComponent: EMPTY })

  /** The server's record of a component, as an attempt state.
   *
   * Read at the point of use rather than merged into state when it arrives. The
   * merge had an ordering bug in it: history can be fetched, so it can land
   * after the learner has already started answering, and folding it in at that
   * moment overwrote what they had just typed. Derived, the local edit simply
   * wins. */
  const storedAttempt = useCallback(
    (id: ComponentId) => {
      const record = ports.stored?.get(id)
      return record ? withStoredProgress(freshAttempt(), record) : freshAttempt()
    },
    [ports.stored],
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
      if (stateFor(block).busy) return Promise.resolve()
      write(block.id, (previous) => ({ ...previous, busy: true, error: null }))
      return ports
        .submit(block, response)
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
    [ports, stateFor, write],
  )

  /** Sends the whole set of ticks, not the one that changed.
   *
   * Absolute state means a dropped request costs one stale render rather than a
   * box that is ticked in the log and clear on the screen forever — and the
   * next tick repairs it. The failure is surfaced rather than swallowed,
   * because a checklist that says "saved as you go" and did not is worse than
   * one that never promised.
   *
   * Undefined, not a no-op, when `ports.saveChecklist` is absent — see
   * `AttemptsApi.saveChecklist`'s own comment. */
  const persistChecklist = ports.saveChecklist
  const saveChecklist = persistChecklist
    ? (block: ComponentBlock, checked: readonly number[]) => {
        void persistChecklist(block, checked)
          .then(() => write(block.id, (previous) => ({ ...previous, saveError: null })))
          .catch((error: unknown) =>
            write(block.id, (previous) => ({ ...previous, saveError: errorMessage(error) })),
          )
      }
    : undefined

  return {
    stateFor,
    update: useCallback(
      (block, change) => write(block.id, (previous) => ({ ...previous, ...change })),
      [write],
    ),
    submit,
    reset: useCallback((block) => write(block.id, clearAttempt), [write]),
    // Spread rather than assigned, because `exactOptionalPropertyTypes` treats
    // an explicit `undefined` differently from an omitted key -- omitting is
    // what "absent" means to `AttemptsApi.saveChecklist`.
    ...(saveChecklist ? { saveChecklist } : {}),
    mcqResponse,
  }
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

  const documentKey = `${sessionId}:${path?.value ?? ''}`

  const api = useAttemptMachine(documentKey, {
    stored: progress.data ?? null,
    // `path` is read at call time, not captured when these ports were built —
    // an in-flight submit from the file that was just closed must not post
    // against the one that replaced it. The null case never reaches here: see
    // the wrapping below, which is where "no file open" stayed a silent no-op.
    submit: (block, response) =>
      lessons.submitAttempt(sessionId, { path: path!, componentId: block.id, response, at }),
    saveChecklist: (block, checked) =>
      lessons.saveChecklist(sessionId, { path: path!, componentId: block.id, checked, at }),
  })

  // The original hook did nothing at all when no file was open — no busy
  // flag, no error, not even a rejected promise for a caller to catch. That
  // has to be preserved outside the shared machine, which has no concept of
  // "no document" to begin with; an ask always has a turn.
  return {
    ...api,
    submit: (block, response) => (path ? api.submit(block, response) : Promise.resolve()),
    saveChecklist: (block, checked) => {
      if (path) api.saveChecklist?.(block, checked)
    },
  }
}
