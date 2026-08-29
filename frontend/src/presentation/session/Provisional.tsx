import clsx from 'clsx'

import { activityContent, type ActivityEntry } from '@domain/activity/activity.ts'

import { Markdown } from '../common/content.tsx'

/** One provisional entry, wherever provisional content is shown.
 *
 * There are two places: the live tail at the foot of a running conversation,
 * and the fold under a failed turn in the timeline. Both rendered this markup
 * by hand until 2026-08-28, which is how the live tail came to be the only
 * prose in the console that was *not* rendered as markdown -- a streaming
 * assistant turn showed its raw `##` and `*` until it committed, and then
 * silently reflowed into a formatted message. The two copies could not drift
 * if there was only ever one, so now there is.
 *
 * `tag` is a prop, and `null` is one of its values. The live tail's entry has
 * not been recorded *yet* and says so on every bubble, because there is
 * nothing else on screen that would. The timeline's are already inside a fold
 * labelled "discarded — not recorded", so a per-bubble tag there is the same
 * sentence twice — and it would carry the pulsing dot, which claims a turn is
 * in flight that ended before the reader opened the fold.
 */
export const ProvisionalBubble = ({
  entry,
  tag = 'in progress — not yet recorded',
}: {
  entry: ActivityEntry
  tag?: string | null
}) => {
  const content = activityContent(entry)

  return (
    <div className={clsx('provisional', `provisional-${entry.kind}`)}>
      {tag === null ? null : <div className="provisional-tag">{tag}</div>}
      {/* Empty is a real state and it is the first one: a delta accumulator
          starts at "" and a whole-message entry can carry only calls. It gets
          no body element at all rather than an empty one, because `Markdown`
          answers an empty source with "(empty file)" -- correct for the file
          viewer it was written for, nonsense under a turn that has simply not
          said anything yet. */}
      {content.text ? (
        content.form === 'prose' ? (
          <Markdown className="provisional-body" source={content.text} />
        ) : (
          <div className="provisional-body mono">{content.text}</div>
        )
      ) : null}
    </div>
  )
}

/** The turn in flight, as the last items in the transcript.
 *
 * Presentational: the caller decides whether a turn is running at all, because
 * the rule for that ("`sending` in the tab that sent it, `watching` in a tab
 * that only watches, and neither once it commits") belongs with the store and
 * was previously restated inside this component, where the drawer and the
 * session route each reached it by a different route.
 */
export const LiveTail = ({ entries }: { entries: readonly ActivityEntry[] }) => {
  if (entries.length === 0) return null

  return (
    <>
      {entries.map((entry) => (
        <ProvisionalBubble key={entry.messageId} entry={entry} />
      ))}
    </>
  )
}
