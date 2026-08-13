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
    <form className="composer ask-composer" onSubmit={submit}>
      <textarea
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
      <div className="composer-row">
        <span className="composer-hint">
          {/* Said again here, at the moment somebody is about to type
              something they may want back. */}
          <span className="txt">Not saved — this conversation goes when you leave.</span>
        </span>
        <div className="composer-actions">
          <Button tone="accent" type="submit" disabled={asking || !draft.trim()}>
            Ask
          </Button>
        </div>
      </div>
    </form>
  )
}
