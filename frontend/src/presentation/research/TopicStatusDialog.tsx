import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useEffect, useId, useRef, useState } from 'react'

import { notify } from '@application/notifications/toast-store.ts'
import { errorMessage } from '@application/ports/errors.ts'
import { queryKeys } from '@application/queries/keys.ts'
import { useContainer } from '@app/container-context.tsx'
import { CLOSED_STATUSES, type TopicDetail, type TopicStatus } from '@domain/research/topic.ts'
import type { ProjectId } from '@domain/shared/identifier.ts'

import { Button } from '../common/primitives.tsx'
import { SubQuestions } from './SubQuestions.tsx'

/** The statuses this build offers, in queue order rather than the wire's --
 *  a reader picking a next status wants "not pursuing"/"superseded" grouped
 *  apart from the live ones, the same split `byUrgency` makes for the list. */
const ALL_STATUSES: readonly TopicStatus[] = [
  'open',
  'investigating',
  'answered',
  'not_pursuing',
  'superseded',
]

/** Descendants a keyboard user can land on, queried fresh on every keypress --
 *  mirrors `WorkerDrawer`'s `FOCUSABLE_SELECTOR`. This dialog's body grows a
 *  sub-question row every time one is added, so a list captured once at mount
 *  would go stale exactly the way the drawer's transcript would. */
const FOCUSABLE_SELECTOR =
  'a[href], button:not([disabled]), input, textarea, select, [tabindex]:not([tabindex="-1"])'

/** Change a topic's status, with the sub-question breakdown alongside it.
 *
 * One dialog rather than two, because both concerns act on the same
 * `TopicDetail` and closing one to open the other for a related edit would
 * cost a reader a click for no reason. Re-selecting the topic's own current
 * status is left off the choices entirely rather than offered and rejected
 * with the 409 the domain answers for a no-op transition -- a control that
 * is not there cannot be clicked by mistake, and there is nothing useful to
 * tell a user who tries to set a topic to what it already is.
 *
 * A justification is required to submit *any* status: the aggregate treats
 * an unexplained change as invalid (422 for blank or whitespace-only), so
 * the Save control mirrors that here rather than letting a submit round-trip
 * to the server just to be told no. Trimmed before both the disabled check
 * and the request, so three spaces do not count as an explanation either.
 */
export const TopicStatusDialog = ({
  projectId,
  topic,
  onClose,
}: {
  projectId: ProjectId
  topic: TopicDetail
  onClose: () => void
}) => {
  const { topics } = useContainer()
  const queryClient = useQueryClient()
  const dialogRef = useRef<HTMLDivElement>(null)
  const closeButtonRef = useRef<HTMLButtonElement>(null)
  const justificationId = useId()

  const [chosen, setChosen] = useState<TopicStatus | null>(null)
  const [justification, setJustification] = useState('')

  const choices = ALL_STATUSES.filter((status) => status !== topic.status)

  const save = useMutation({
    mutationFn: () => {
      if (!chosen) throw new Error('no status chosen')
      return topics.setStatus(projectId, topic.topicId, chosen, justification.trim())
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.topic(projectId, topic.topicId) })
      void queryClient.invalidateQueries({ queryKey: queryKeys.topics(projectId) })
      onClose()
    },
    onError: (error) => notify(errorMessage(error), 'bad'),
  })

  const canSave = chosen !== null && justification.trim().length > 0 && !save.isPending

  // Move focus in on open, and give it back to whatever had it on close --
  // see `WorkerDrawer`'s doc comment on the same pair of effects for why the
  // close button is the target and why the previously-focused element is
  // re-checked for DOM membership before being restored.
  useEffect(() => {
    const previouslyFocused = document.activeElement
    closeButtonRef.current?.focus()
    return () => {
      if (previouslyFocused instanceof HTMLElement && document.contains(previouslyFocused)) {
        previouslyFocused.focus()
      }
    }
  }, [])

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        onClose()
        return
      }

      if (event.key !== 'Tab' || !dialogRef.current) return

      const focusable = Array.from(
        dialogRef.current.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR),
      )
      const first = focusable[0]
      const last = focusable[focusable.length - 1]
      if (!first || !last) return

      const active = document.activeElement
      if (event.shiftKey) {
        if (active === first || !dialogRef.current.contains(active)) {
          event.preventDefault()
          last.focus()
        }
      } else if (active === last || !dialogRef.current.contains(active)) {
        event.preventDefault()
        first.focus()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  return (
    <div className="drawer-backdrop" onClick={onClose}>
      <aside
        className="drawer topic-dialog"
        role="dialog"
        aria-modal="true"
        aria-label={`Manage ${topic.question}`}
        ref={dialogRef}
        onClick={(event) => event.stopPropagation()}
      >
        <header className="drawer-head">
          <h3 className="drawer-title">{topic.question}</h3>
          <span className="drawer-spacer" />
          <button type="button" className="btn btn-sm" ref={closeButtonRef} onClick={onClose}>
            Close
          </button>
        </header>

        <div className="drawer-body">
          <div className="topic-status-current">
            Currently <strong>{topic.status.replace('_', ' ')}</strong>
            {CLOSED_STATUSES.includes(topic.status) ? ' -- reopening is allowed.' : ''}
          </div>

          <div className="topic-status-choices">
            {choices.map((status) => (
              <button
                key={status}
                type="button"
                className={
                  chosen === status
                    ? 'btn btn-sm topic-status-choice topic-status-choice-active'
                    : 'btn btn-sm topic-status-choice'
                }
                aria-pressed={chosen === status}
                onClick={() => setChosen(status)}
              >
                {status.replace('_', ' ')}
              </button>
            ))}
          </div>

          <label htmlFor={justificationId}>Justification</label>
          <textarea
            id={justificationId}
            className="input topic-status-justification"
            value={justification}
            onChange={(event) => setJustification(event.target.value)}
            placeholder="why this change"
          />

          <div className="topic-status-actions">
            <Button tone="accent" disabled={!canSave} onClick={() => save.mutate()}>
              {save.isPending ? 'Saving…' : 'Save'}
            </Button>
          </div>

          <SubQuestions projectId={projectId} topic={topic} />
        </div>
      </aside>
    </div>
  )
}
