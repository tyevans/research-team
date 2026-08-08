import type { TopicId } from '@domain/shared/identifier.ts'

/** Where one topic stands in the research queue. */
export type TopicStatus = 'open' | 'investigating' | 'answered' | 'not_pursuing' | 'superseded'

/** The statuses that mean this topic will not move again on its own.
 *
 * Named apart from `TopicStatus` because "closed" is a fact `byUrgency` and
 * the list both need and neither should derive twice — a topic dropped from
 * this list is one they would silently disagree about. */
export const CLOSED_STATUSES: readonly TopicStatus[] = ['not_pursuing', 'superseded']

/** One row of the topic queue: what a reader ranks and skims on, not the
 *  topic's own page. */
export interface TopicView {
  readonly topicId: TopicId
  readonly question: string
  readonly status: TopicStatus
  readonly sources: number
  readonly findings: number
  readonly openSubQuestions: number
  readonly triggers: readonly string[]
  readonly needsAttention: boolean
  readonly isBlocked: boolean
}

export const isClosed = (topic: TopicView): boolean => CLOSED_STATUSES.includes(topic.status)

/** Which slice of the queue a reader is looking at.
 *
 * Four named slices rather than a status dropdown listing all five statuses,
 * because the question somebody scanning a queue asks is not "which topics are
 * `superseded`" -- it is "what needs me", "what is live", "what is done with".
 * `attention` deliberately spans two wire fields: a blocked topic and a
 * flagged one are both things waiting on a person, and splitting them would
 * make the reader check two slices to answer one question.
 */
export type TopicFocus = 'all' | 'attention' | 'live' | 'closed'

export const inFocus = (topic: TopicView, focus: TopicFocus): boolean => {
  switch (focus) {
    case 'attention':
      return topic.isBlocked || topic.needsAttention
    case 'live':
      return !isClosed(topic)
    case 'closed':
      return isClosed(topic)
    default:
      return true
  }
}

/** Whether a topic survives the queue's filter.
 *
 * The text is matched against the triggers as well as the question, because a
 * trigger is *why* a topic is flagged -- "contested", say -- and somebody
 * hunting the reason a queue has stalled is searching for that word, not for
 * whatever the question happens to be phrased as. Matching the question alone
 * would return nothing for the search most worth making.
 */
export const matchesTopic = (topic: TopicView, focus: TopicFocus, search: string): boolean => {
  if (!inFocus(topic, focus)) return false
  const needle = search.trim().toLowerCase()
  if (!needle) return true
  return (
    topic.question.toLowerCase().includes(needle) ||
    topic.triggers.some((trigger) => trigger.toLowerCase().includes(needle))
  )
}

/** How many topics sit in each slice, counted over the whole queue.
 *
 * Counted before filtering and shown on the controls themselves: a slice that
 * is empty should say so before it is chosen, so a reader is never left
 * wondering whether they picked the wrong filter or the queue really has
 * nothing waiting on them.
 */
export const focusCounts = (topics: readonly TopicView[]): Record<TopicFocus, number> => ({
  all: topics.length,
  attention: topics.filter((topic) => inFocus(topic, 'attention')).length,
  live: topics.filter((topic) => inFocus(topic, 'live')).length,
  closed: topics.filter((topic) => inFocus(topic, 'closed')).length,
})

export interface SubQuestion {
  readonly key: string
  readonly question: string
  readonly answer: string | null
  readonly resolved: boolean
}

/** One topic's own page: the row plus what the queue leaves out.
 *
 * `findings` carries the same count `TopicView` does, and `findingNotes`
 * carries the prose behind that count — two fields rather than one, because
 * the wire response spells them with two different keys (`findings` and
 * `finding_notes`) for exactly this reason: a page rendering a topic's own
 * findings wants both the number and what they say, and neither should have
 * to be reconstructed from the other.
 */
export interface TopicDetail {
  readonly topicId: TopicId
  readonly question: string
  readonly status: TopicStatus
  readonly sources: number
  readonly findings: number
  readonly openSubQuestions: number
  readonly triggers: readonly string[]
  readonly needsAttention: boolean
  readonly isBlocked: boolean
  readonly rationale: string
  readonly scope: string
  readonly subQuestions: readonly SubQuestion[]
  readonly sourceIds: readonly string[]
  readonly findingNotes: readonly string[]
  readonly contested: boolean
}

/** The queue's own order: blocked first, then flagged, then live, then
 *  closed, ties broken by question text.
 *
 * `isBlocked` and `needsAttention` are not exclusive on the wire, so they are
 * ranked rather than merged into one boolean — a blocked topic is worse than
 * a merely flagged one and must sort above it even though both would pass a
 * plain "needs attention" test. The question tiebreak is not cosmetic: two
 * rows at the same urgency have no natural order, and sorting by arrival
 * would swap them on every poll the moment the server's own ordering shifts,
 * which is unreadable in a list that is read top to bottom.
 */
export const byUrgency = (a: TopicView, b: TopicView): number => {
  const rank = (topic: TopicView): number => {
    if (topic.isBlocked) return 0
    if (topic.needsAttention) return 1
    if (!isClosed(topic)) return 2
    return 3
  }

  const delta = rank(a) - rank(b)
  return delta !== 0 ? delta : a.question.localeCompare(b.question)
}
