import clsx from 'clsx'
import type { ReactNode } from 'react'

import type { TopicView } from '@domain/research/topic.ts'
import { isClosed } from '@domain/research/topic.ts'

import { EntityStatus } from '../EntityStatus.tsx'

/** Affordances a topic row can be given, by the view that knows why.
 *
 * Named slots rather than `children`, so a story can enumerate "row with
 * dispatch" against "row with nothing", and so a type error catches a row
 * rendering a verb it was not given.
 *
 * **Two, and the ceiling is four.** The design's own tripwire: more than four
 * named slots means the density set is wrong rather than the slot set, and the
 * correction at that point is a fifth density, not a sixth slot. Recording the
 * count here is what makes that checkable later instead of aspirational.
 */
export interface TopicRowSlots {
  /** The one verb this row offers — today a dispatch button. The view owns it
   *  because the view owns the reason it is disabled: R-F3.4's single disabled
   *  control is carefully reasoned about at its call site, and a row that
   *  decided its own disabled-ness would have to re-derive that reasoning. */
  primary: ReactNode
  /** Verbs behind a menu. A list rather than a node so the row can decide
   *  whether one item deserves a menu at all — "a menu holding a single item
   *  is a click in front of a button", which the existing row says in a
   *  comment and then has to re-decide every time a verb is added. */
  overflow: readonly ReactNode[]
}

/** The `Row` density: a uniform-height member of a scanned list.
 *
 * **Its defining property is that its height is a function of its kind, not of
 * its content**, and that is not decoration — it is the contract a virtualizer
 * relies on. L-F8 is what it costs when the contract is broken: measurements
 * cached against an array index "followed the wrong row and left a **122px
 * hole** at three projects". So this row clamps its question to one line
 * rather than wrapping, and carries no disclosure. A topic that needs to show
 * more than this is a `TopicDetail`, not a taller row.
 *
 * Extracted rather than invented: `TopicList.tsx:293` is already exactly this
 * component, already props-only, and merely not exported. What changes is that
 * its status goes through `EntityStatus` instead of a fourth
 * `.replace('_', ' ')`, its navigation is an `href` instead of an `onClick`,
 * and its verbs arrive as slots instead of two callbacks.
 */
export const TopicRow = ({
  topic,
  href,
  selected = false,
  slots = {},
}: {
  topic: TopicView
  href?: string | undefined
  selected?: boolean
  slots?: Partial<TopicRowSlots>
}) => (
  <li
    className={clsx(
      'ent-topic-row',
      topic.isBlocked && 'is-blocked',
      !topic.isBlocked && topic.needsAttention && 'needs-attention',
      !topic.isBlocked && !topic.needsAttention && isClosed(topic) && 'is-closed',
      selected && 'is-selected',
    )}
    data-topic={topic.topicId}
    aria-current={selected ? 'true' : undefined}
  >
    {/* The question is the row's name and its link. A whole-row click target
        was considered and rejected: it makes the row's verbs harder to reach
        by keyboard, because every one of them then sits inside the link. */}
    <div className="ent-topic-question">
      {href === undefined ? topic.question : <a href={href}>{topic.question}</a>}
    </div>

    <div className="ent-topic-meta">
      <EntityStatus status={topic.status} />

      {/* Counts, not percentages, and each says what it counts. `findings` is
          an `int` here and `findingNotes` is a list of strings on the detail —
          two different fields the wire spells with two different keys, which a
          props contract mapping both onto `findings` would turn into a bug
          that typechecks. */}
      <span className="ent-topic-count">{topic.sources} sources</span>
      <span className="ent-topic-count">{topic.findings} findings</span>
      {topic.openSubQuestions > 0 ? (
        <span className="ent-topic-count">{topic.openSubQuestions} open</span>
      ) : null}

      {slots.primary}
      {slots.overflow !== undefined && slots.overflow.length > 0 ? (
        <span className="ent-topic-overflow">{slots.overflow}</span>
      ) : null}
    </div>
  </li>
)
