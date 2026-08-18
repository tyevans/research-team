import { useState, type FormEvent } from 'react'

import type { DialogueProgress } from '@application/ports/repositories.ts'
import type { DialogueTranscript } from '@domain/dialogue/conversation.ts'
import type { DocumentBlock } from '@domain/lesson/document.ts'
import type { ProjectId } from '@domain/shared/identifier.ts'

import { Button } from '../common/primitives.tsx'
import { DialogueThread } from './DialogueThread.tsx'

/** The dialogue page, as a pure function of props -- `AskPage`'s split, for
 *  `AskPage`'s reason: a store here would put a container and a fake
 *  repository between anyone and the first pixel.
 *
 * What it does not share with `AskPage` is the direction. `blocks` is the
 * dialogue's utterance and `reply` is the reader's, which is the inverse of an
 * ask, and a page that reused `AskTurn` would draw every dialogue with the
 * speakers swapped and still read as a conversation. `DialogueExchange` exists
 * for that reason alone; `LessonDocument`, `AskActivityFold` and
 * `CitationList` are reused, because blocks are blocks and activity is
 * activity.
 */
export const DialoguePage = ({
  projectId,
  transcript,
  goal,
  stoppingCondition,
  openingBlocks,
  dialogueId,
  progress,
  replying,
  starting,
  error,
  progressUnavailable,
  onStart,
  onReply,
}: {
  projectId: ProjectId
  transcript: DialogueTranscript
  goal: string
  stoppingCondition: string
  /** The question that opened the dialogue, off the dialogue row.
   *
   * `pendingBlocks` from the store is deliberately not taken: per
   * `app.py:3117` it is "the question being answered, not the one about to be
   * asked", so it duplicates a question already on screen one exchange stale.
   * See `DialogueThread` for the chronology this props list follows. */
  openingBlocks: readonly DocumentBlock[]
  // Null until `start` returns the server-minted id -- see `dialogue-store.ts`
  // for why this surface cannot mint one in the browser.
  dialogueId: string | null
  /** What this reader has already had marked here, keyed `turn/{position}`.
   *
   * A prop rather than a fetch inside the thread, for this page's whole
   * reason: the page stays a pure function of its props, so a test can draw a
   * resumed dialogue with three answered widgets and no repository at all. */
  progress: DialogueProgress
  replying: boolean
  starting: boolean
  error: string | null
  /** Whether the marked answers could not be loaded -- see `dialogue-store.ts`
   *  for why this is a flag and not the `error` above. */
  progressUnavailable: boolean
  onStart: (topic: string) => void
  onReply: (reply: string) => void
}) => {
  // Read off the newest turn rather than the page: `concluded` travels on the
  // `prompt` frame that closes a turn, so the last one is the only one that
  // can be true. False on every frame a live server sends today -- nothing
  // writes `SocraticDialogueConcluded` until Plan 4 -- and rendered now so
  // that plan does not have to come back to this file.
  const concluded = transcript[transcript.length - 1]?.concluded ?? false

  return (
    <section className="dlg flex min-h-0 flex-1 flex-col overflow-hidden">
      {/* The framing, and the one thing that separates this surface from a
          quiz: a reader who disagrees with where the dialogue is taking them
          should be able to see that before spending twenty minutes on it.
          Above the thread rather than inside it, because it is not a turn --
          a transcript that held it would draw it as something to answer. */}
      <div className="dlg-framing">
        <p className="dlg-goal">{goal ? goal : 'Pick something to work through.'}</p>
        {stoppingCondition ? <p className="dlg-condition">Done when: {stoppingCondition}</p> : null}
      </div>

      {error ? (
        <div className="error-box mx-5 mt-4 shrink-0" role="alert">
          <strong>That did not go through.</strong>
          {error}
        </div>
      ) : null}

      {/* One quiet line, and deliberately neither a banner nor a toast: the
          load that failed is not the reader's action, so dressing it as an
          error blames their last answer for a request they did not make. It
          is here at all because the silent version is indistinguishable from
          the defect this route exists to fix -- a dialogue that forgot. It
          costs a line the reader can do nothing about; the alternative cost
          nothing on screen and hid a broken route for a whole plan.
          `role="status"`, not `alert`: it is not interrupting anyone. */}
      {progressUnavailable ? (
        <p className="dlg-progress-lost" role="status">
          Your earlier answers could not be loaded.
        </p>
      ) : null}

      <DialogueThread
        projectId={projectId}
        transcript={transcript}
        openingBlocks={openingBlocks}
        dialogueId={dialogueId}
        progress={progress}
        concluded={concluded}
      />

      {concluded ? (
        <p className="dlg-concluded" role="status">
          This dialogue has reached its goal.
        </p>
      ) : (
        <DialogueComposer
          started={dialogueId !== null}
          busy={dialogueId === null ? starting : replying}
          onSubmit={dialogueId === null ? onStart : onReply}
        />
      )}
    </section>
  )
}

/** One box that asks for two different things.
 *
 * Two labels rather than one, and the label is the whole point: before a
 * dialogue exists the reader is naming a topic, and afterwards they are
 * answering a question. A single "Message" placeholder would leave the first
 * reader guessing what is wanted of them, which on this surface is the moment
 * the whole thing is decided -- the topic is what the framing model is given.
 */
const DialogueComposer = ({
  started,
  busy,
  onSubmit,
}: {
  started: boolean
  busy: boolean
  onSubmit: (text: string) => void
}) => {
  const [draft, setDraft] = useState('')
  const label = started ? 'Your answer' : 'Topic'

  const submit = (event: FormEvent) => {
    event.preventDefault()
    // The store refuses an empty or concurrent send too; refusing here as well
    // is what stops the draft being cleared for a reply that never went.
    if (busy || !draft.trim()) return
    onSubmit(draft)
    setDraft('')
  }

  return (
    <form
      className="dlg-composer shrink-0 border-0 border-t border-solid border-line bg-bg-panel px-5 py-3"
      onSubmit={submit}
    >
      <div className="mx-auto flex w-full max-w-[72ch] flex-col gap-2">
        {/* `focus:`, not `focus-visible:` -- `AskComposer` says why: a pointer
            user clicking into a field wants the confirmation a keyboard user
            gets. */}
        <textarea
          className="max-h-[180px] min-h-[52px] w-full resize-y rounded-md border border-solid border-line bg-bg px-3 py-3 font-sans text-md leading-[1.5] text-fg focus:border-accent-dim focus:outline-none disabled:opacity-55"
          rows={2}
          placeholder={
            started ? 'Answer in your own words…  (Ctrl+Enter)' : 'What do you want to work out?'
          }
          aria-label={label}
          value={draft}
          disabled={busy}
          onChange={(event) => setDraft(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === 'Enter' && (event.ctrlKey || event.metaKey)) submit(event)
          }}
        />
        <div className="flex items-center justify-end gap-3">
          <Button tone="accent" type="submit" disabled={busy || !draft.trim()}>
            {started ? 'Answer' : 'Start'}
          </Button>
        </div>
      </div>
    </form>
  )
}
