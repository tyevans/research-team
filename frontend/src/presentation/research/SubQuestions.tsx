import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useId, useState } from 'react'
import clsx from 'clsx'

import { notify } from '@application/notifications/toast-store.ts'
import { errorMessage } from '@application/ports/errors.ts'
import { queryKeys } from '@application/queries/keys.ts'
import { useContainer } from '@app/container-context.tsx'
import type { TopicDetail } from '@domain/research/topic.ts'
import type { ProjectId } from '@domain/shared/identifier.ts'

import { Button } from '../common/primitives.tsx'

/** A label, a field and a button on one wrapping line.
 *
 * `.sub-question-resolve` and `.sub-question-add` were one grouped rule and are
 * one constant, which is the same saving in the same place. **The slice plan
 * lists `sub-question-resolve` as one of the four names that "have no rule and
 * never did"; it is wrong about that one.** It is the first selector of the
 * pair at `research.css:306`, so it was fully dressed, and translating it as
 * bare would have flattened both rows. Worth saying rather than fixing
 * silently: the four-item list was built by grepping for `^\.name {`, and a
 * grouped selector's second-and-later members do not match that shape. */
const FIELD_ROW = 'mt-[4px] flex flex-wrap items-center gap-[6px] text-xs text-fg-dim'

/** A topic's own breakdown: the sub-questions it has been split into, and the
 *  means to add one or settle one.
 *
 * Lives inside `TopicManagePane` rather than the topic list, because a
 * sub-question is detail a reader only wants once they have already opened a
 * topic to manage it -- the queue row already carries the count.
 */
export const SubQuestions = ({
  projectId,
  topic,
}: {
  projectId: ProjectId
  topic: TopicDetail
}) => {
  const { topics } = useContainer()
  const queryClient = useQueryClient()

  const invalidate = () => {
    // Both keys: the count on the queue row and the detail this dialog reads
    // both come from the same sub-question set, and only invalidating one
    // would leave the other showing a stale count until something else
    // happened to refetch it.
    void queryClient.invalidateQueries({ queryKey: queryKeys.topic(projectId, topic.topicId) })
    void queryClient.invalidateQueries({ queryKey: queryKeys.topics(projectId) })
  }

  const [key, setKey] = useState('')
  const [question, setQuestion] = useState('')

  const add = useMutation({
    mutationFn: () => topics.addSubQuestion(projectId, topic.topicId, key.trim(), question.trim()),
    onSuccess: () => {
      setKey('')
      setQuestion('')
      invalidate()
    },
    onError: (error) => notify(errorMessage(error), 'bad'),
  })

  /** Resolving lives here rather than in the row it draws.
   *
   * The row is a label, an input and a button — nothing about it needs a
   * repository, and while it held one it could not be rendered, story-booked or
   * tested without a container and a query client behind it. Which row is busy
   * comes off the mutation's own `variables` instead of a second `useState`,
   * because react-query already knows what is in flight and a duplicate would
   * be a second thing to keep in step.
   *
   * This changes no behaviour a test can see: the suite below drives resolution
   * through `SubQuestions` and passes either way. */
  const resolve = useMutation({
    mutationFn: ({ key: subKey, answer }: { key: string; answer: string }) =>
      topics.resolveSubQuestion(projectId, topic.topicId, subKey, answer),
    onSuccess: invalidate,
    onError: (error) => notify(errorMessage(error), 'bad'),
  })

  const keyId = useId()
  const questionId = useId()

  return (
    // `border-0` and then one edge, both halves: `border-solid` styles all four
    // sides at once, and this build imports no preflight, so a directional
    // width with no zero leaves the other three at the browser's `medium`
    // (~3px) and draws a box where a rule was written.
    <div className="border-0 border-t border-solid border-line pt-[12px]">
      <ul className="m-0 mb-[10px] flex list-none flex-col gap-[8px] p-0">
        {topic.subQuestions.map((sub) => (
          <SubQuestionRow
            key={sub.key}
            sub={sub}
            busy={resolve.isPending && resolve.variables?.key === sub.key}
            onResolve={(answer) => resolve.mutate({ key: sub.key, answer })}
          />
        ))}
      </ul>

      <div className={FIELD_ROW}>
        <label htmlFor={keyId}>Key</label>
        <input
          id={keyId}
          className="input"
          value={key}
          onChange={(event) => setKey(event.target.value)}
          placeholder="a short slug"
        />
        <label htmlFor={questionId}>Question</label>
        <input
          id={questionId}
          className="input"
          value={question}
          onChange={(event) => setQuestion(event.target.value)}
          placeholder="what is being asked"
        />
        <Button
          small
          disabled={!key.trim() || !question.trim() || add.isPending}
          onClick={() => add.mutate()}
        >
          {add.isPending ? 'Adding…' : 'Add'}
        </Button>
      </div>
    </div>
  )
}

/** One sub-question, and the means to settle it if it is open.
 *
 * Props only: it is handed what to draw and one callback, and the typed answer
 * is the single piece of state it owns because nothing outside the row reads
 * it. Nothing clears that box on success — the successful case refetches the
 * topic, the sub comes back `resolved`, and the branch holding the input stops
 * rendering, so clearing it would only be visible in a render that does not
 * happen. */
const SubQuestionRow = ({
  sub,
  busy,
  onResolve,
}: {
  sub: TopicDetail['subQuestions'][number]
  busy: boolean
  onResolve: (answer: string) => void
}) => {
  const [answer, setAnswer] = useState('')
  const answerId = useId()

  return (
    <li
      // The left edge again, and the same two halves. `sub-question-resolved`
      // dimmed the whole row and is a `text-fg-dim` on the branch instead —
      // there is nothing here for a descendant selector to reach that the two
      // children below do not already set for themselves.
      className={clsx(
        'border-0 border-l-2 border-solid border-l-line bg-bg-panel-2 px-[8px] py-[6px]',
        sub.resolved && 'text-fg-dim',
      )}
    >
      <div className="text-sm">{sub.question}</div>
      {sub.resolved ? (
        <div className="mt-[3px] text-xs text-fg-dim">{sub.answer}</div>
      ) : (
        <div className={FIELD_ROW}>
          <label htmlFor={answerId}>Answer</label>
          <input
            id={answerId}
            className="input"
            value={answer}
            onChange={(event) => setAnswer(event.target.value)}
          />
          <Button small disabled={!answer.trim() || busy} onClick={() => onResolve(answer.trim())}>
            {busy ? 'Resolving…' : 'Resolve'}
          </Button>
        </div>
      )}
    </li>
  )
}
