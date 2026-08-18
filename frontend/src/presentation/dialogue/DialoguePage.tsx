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
  concluded: concludedFromStore,
  endedByReader,
  onStart,
  onReply,
  onEnd,
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
  /** Whether the store has learned the dialogue is over -- see
   *  `dialogue-store.ts` for why that is a 409 on reply and nothing else. */
  concluded: boolean
  /** Whether *this reader, in this session*, ended it -- see `dialogue-store.ts`
   *  for why that is separate from `concluded` and why it does not survive a
   *  refresh (B120). Only the wording below reads it. */
  endedByReader: boolean
  onStart: (topic: string) => void
  onReply: (reply: string) => void
  onEnd: () => void
}) => {
  // Either source, because neither covers both cases. The transcript's flag is
  // what a LIVE dialogue has -- `concluded` travels on the `prompt` frame that
  // closes a turn, so the newest turn is the only one that can carry it. The
  // store's is what a RESUMED one has, where a 409 on the reader's first reply
  // is the only signal and there are no turns to read a flag off at all
  // (B120). A page that picked one shows a composer to a returning reader
  // whose dialogue has finished. The test that fails if the store half is
  // dropped is `shows the finished state from the store even with no turns to
  // read it off`.
  const concluded = concludedFromStore || (transcript[transcript.length - 1]?.concluded ?? false)

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
        // Two sentences, and the default is the one that says the thing worked.
        // "This dialogue has ended" would be true either way and was refused for
        // exactly that: it is the one line on this page that tells a reader they
        // got there. The cost, stated rather than hidden: `endedByReader` is
        // store state and does not survive a refresh, so a reader who ended a
        // dialogue and comes back is told it reached its goal. Not for want of
        // the reason on the server -- `_dialogue_view` already sends
        // `concludedReason` (`app.py:3720`); nothing in the browser fetches one
        // dialogue whole. That is B120, and it is a client-side gap only.
        //
        // "You ended this dialogue", never "abandoned": `reason="abandoned"` is
        // stored because it is accurate about why it ended, and it is not what a
        // reader should read about themselves.
        <p className="dlg-concluded" role="status">
          {endedByReader ? 'You ended this dialogue.' : 'This dialogue has reached its goal.'}
        </p>
      ) : (
        <DialogueComposer
          started={dialogueId !== null}
          busy={dialogueId === null ? starting : replying}
          onSubmit={dialogueId === null ? onStart : onReply}
          onEnd={onEnd}
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
  onEnd,
}: {
  started: boolean
  busy: boolean
  onSubmit: (text: string) => void
  /** Ends the dialogue. Drawn here rather than in the framing header because
   *  this is where the reader already is when they decide they are done, and
   *  only inside this branch because a concluded dialogue has nothing to end --
   *  a button rendered unconditionally would sit under the "reached its goal"
   *  line and 409 on every click. The store, not this component, guards the
   *  case where no dialogue has been started yet. */
  onEnd: () => void
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
          {/* `tone="quiet"` and `type="button"`: quiet because stopping is not
              the action this surface is encouraging, and `type="button"`
              because a default-typed button inside a form submits it -- which
              here would send the draft and end the dialogue on one click. */}
          <Button tone="quiet" type="button" onClick={onEnd}>
            End this dialogue
          </Button>
          <Button tone="accent" type="submit" disabled={busy || !draft.trim()}>
            {started ? 'Answer' : 'Start'}
          </Button>
        </div>
      </div>
    </form>
  )
}
