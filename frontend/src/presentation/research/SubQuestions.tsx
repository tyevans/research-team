import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useId, useState } from 'react'

import { notify } from '@application/notifications/toast-store.ts'
import { errorMessage } from '@application/ports/errors.ts'
import { queryKeys } from '@application/queries/keys.ts'
import { useContainer } from '@app/container-context.tsx'
import type { TopicDetail } from '@domain/research/topic.ts'
import type { ProjectId } from '@domain/shared/identifier.ts'

import { Button } from '../common/primitives.tsx'

/** A topic's own breakdown: the sub-questions it has been split into, and the
 *  means to add one or settle one.
 *
 * Lives inside `TopicStatusDialog` rather than the topic list, because a
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

  const keyId = useId()
  const questionId = useId()

  return (
    <div className="sub-questions">
      <ul className="sub-question-list">
        {topic.subQuestions.map((sub) => (
          <SubQuestionRow
            key={sub.key}
            projectId={projectId}
            topic={topic}
            sub={sub}
            onDone={invalidate}
          />
        ))}
      </ul>

      <div className="sub-question-add">
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

const SubQuestionRow = ({
  projectId,
  topic,
  sub,
  onDone,
}: {
  projectId: ProjectId
  topic: TopicDetail
  sub: TopicDetail['subQuestions'][number]
  onDone: () => void
}) => {
  const { topics } = useContainer()
  const [answer, setAnswer] = useState('')
  const answerId = useId()

  const resolve = useMutation({
    mutationFn: () => topics.resolveSubQuestion(projectId, topic.topicId, sub.key, answer.trim()),
    onSuccess: () => {
      setAnswer('')
      onDone()
    },
    onError: (error) => notify(errorMessage(error), 'bad'),
  })

  return (
    <li className={sub.resolved ? 'sub-question sub-question-resolved' : 'sub-question'}>
      <div className="sub-question-text">{sub.question}</div>
      {sub.resolved ? (
        <div className="sub-question-answer">{sub.answer}</div>
      ) : (
        <div className="sub-question-resolve">
          <label htmlFor={answerId}>Answer</label>
          <input
            id={answerId}
            className="input"
            value={answer}
            onChange={(event) => setAnswer(event.target.value)}
          />
          <Button
            small
            disabled={!answer.trim() || resolve.isPending}
            onClick={() => resolve.mutate()}
          >
            {resolve.isPending ? 'Resolving…' : 'Resolve'}
          </Button>
        </div>
      )}
    </li>
  )
}
