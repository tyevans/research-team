import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useId, useState } from 'react'

import { notify } from '@application/notifications/toast-store.ts'
import { errorMessage } from '@application/ports/errors.ts'
import { queryKeys } from '@application/queries/keys.ts'
import { useContainer } from '@app/container-context.tsx'
import { statusLabel } from '@domain/entity/status.ts'
import { CLOSED_STATUSES, type TopicDetail, type TopicStatus } from '@domain/research/topic.ts'
import type { ProjectId } from '@domain/shared/identifier.ts'

import { Drawer } from '../common/Drawer.tsx'
import { Button } from '../common/primitives.tsx'
import { SubQuestions } from './SubQuestions.tsx'
import { TopicDocuments } from './TopicDocuments.tsx'

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
 *
 * **The dialog shell is `Drawer`'s now.** This file used to render its own
 * `.drawer-backdrop`, its own `role="dialog"` aside, its own focus-in/restore
 * pair and its own Tab trap over a `FOCUSABLE_SELECTOR` re-queried per
 * keypress -- a copy of what `Drawer` held, which `Drawer`'s comment predicted
 * would happen and which this file then did. All of it is deleted. The trap in
 * particular was a *simulation* of confinement: it cycled Tab among its own
 * children and could say nothing about the agent dock painting on top of it,
 * which it did. `Overlay` marks the page `inert` instead, which is the
 * platform confining the pointer, the keyboard and a screen reader's virtual
 * cursor at once.
 *
 * The two suppressions that sat on the old markup went with it, and that is
 * the tell worth keeping: they were there because a `div` with an `onClick`
 * and no key handler is not an interactive element, which was true, and the
 * honest fix was never a comment.
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

  return (
    /* `label` is "Manage <question>" while `title` is the question alone: the
       heading sits under a visible "Manage" affordance, but an accessible name
       has no such context and "Where the audit trail lives" alone does not say
       that this is the thing that changes it. The two props exist to differ. */
    <Drawer heading={topic.question} label={`Manage ${topic.question}`} onClose={onClose}>
      <div className="topic-status-current">
        Currently <strong>{statusLabel(topic.status)}</strong>
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
            {statusLabel(status)}
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

      {/* Last, and inside this dialog rather than as a fifth pane: what a
          dispatch wrote is the answer to the question this topic asks, so it
          belongs behind the topic rather than beside the graph. That this
          section arrives late and grows used to matter to the trap above it,
          which re-queried its focusable children per keypress to keep up;
          `inert` confines a subtree rather than a list, so a body that grows
          is no longer a thing the dialog has to keep track of. */}
      <section className="topic-documents-section">
        <h3 className="topic-section-heading">Documents</h3>
        <TopicDocuments projectId={projectId} topicId={topic.topicId} />
      </section>
    </Drawer>
  )
}
