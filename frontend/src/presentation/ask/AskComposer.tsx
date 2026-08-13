import { useState, type FormEvent } from 'react'

import { Button } from '../common/primitives.tsx'

/** The question box.
 *
 * Not `Composer.tsx`, which is bound to a session's `TurnState` and to the
 * cancel/recheck/jump controls a session turn has and this one does not.
 * Ctrl+Enter is kept, because it is the same gesture on the same kind of
 * control and a reader who learned it on the session page should not have to
 * learn a second one here.
 */
export const AskComposer = ({
  asking,
  onAsk,
}: {
  asking: boolean
  onAsk: (question: string) => void
}) => {
  const [draft, setDraft] = useState('')

  const submit = (event: FormEvent) => {
    event.preventDefault()
    // The store refuses an empty or concurrent send too; refusing here as well
    // is what stops the draft being cleared for a question that never went.
    if (asking || !draft.trim()) return
    onAsk(draft)
    setDraft('')
  }

  return (
    // `ask-composer` is a selector hook for `AskView.browser.test.tsx`, which
    // needs a name more specific than `form`. Full-bleed against the page
    // edge and bordered on top, so it reads as the floor of the page rather
    // than as a card sitting on it -- while its contents stay on
    // `ask-measure`, lined up with the prose above. That alignment is what
    // the browser test measures. `border-0` before `border-t`: `border-solid`
    // sets `border-style: solid` on all four sides, and a side with a style
    // but no explicit width falls back to the browser's `medium` (~3px)
    // rather than 0 -- the same defect `AskTurn.tsx` and `AskHead.tsx`
    // document, all three caught by the same screenshot.
    <form
      className="ask-composer shrink-0 border-0 border-t border-solid border-line bg-bg-panel px-5 py-3"
      onSubmit={submit}
    >
      {/* `ask-measure` carries no rules of its own -- see `AskThread.tsx` --
          so the cap is the utilities beside it. */}
      <div className="ask-measure mx-auto flex w-full max-w-[72ch] flex-col gap-2">
        {/* `focus:`, not `focus-visible:`: a pointer user clicking into a
            field wants the same confirmation a keyboard user gets. */}
        <textarea
          className="max-h-[180px] min-h-[52px] w-full resize-y rounded-md border border-solid border-line bg-bg px-3 py-3 font-sans text-md leading-[1.5] text-fg focus:border-accent-dim focus:outline-none disabled:opacity-55"
          rows={2}
          placeholder="Ask about this project…  (Ctrl+Enter)"
          aria-label="Question"
          value={draft}
          disabled={asking}
          onChange={(event) => setDraft(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === 'Enter' && (event.ctrlKey || event.metaKey)) submit(event)
          }}
        />
        <div className="flex items-center justify-between gap-3">
          {/* Said again here, at the moment somebody is about to type
              something they may want back. */}
          <span className="min-w-0 overflow-hidden text-xs text-ellipsis whitespace-nowrap text-fg-faint">
            Not saved — this conversation goes when you leave.
          </span>
          <Button tone="accent" type="submit" disabled={asking || !draft.trim()}>
            Ask
          </Button>
        </div>
      </div>
    </form>
  )
}
