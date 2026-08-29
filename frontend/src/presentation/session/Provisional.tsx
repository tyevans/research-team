import clsx from 'clsx'

import { activityContent, activityMessage, type ActivityEntry } from '@domain/activity/activity.ts'

import { Markdown } from '../common/content.tsx'
import { ToolResult } from './shapes/ToolResult.tsx'
import type { Phase } from './shapes/parts.tsx'

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
 *
 * **A tool result goes through `ToolResult`, which is the same call the
 * committed transcript makes.** That is the property "phase is position"
 * rests on: a `search_sources` answer is one shape drawn once, with `phase`
 * saying which end of the stream it is at, so the card does not visibly
 * re-lay-out at the instant the turn commits. Where the entry carries no
 * artifact — every entry written before this work, and every tool nobody has
 * converted — `fallback` is this component's own markup, unchanged, so the
 * common case on real history renders exactly as it renders now.
 */
export const ProvisionalBubble = ({
  entry,
  tag = 'in progress — not yet recorded',
  phase = 'live',
}: {
  entry: ActivityEntry
  tag?: string | null
  /** Which end of the stream this entry is at, for the shape inside it.
   *
   * Defaults to `live` because the live tail is the reason this component
   * exists. The timeline's discarded fold passes `settled` for the same
   * reason it passes `tag={null}`: that turn ended before the reader opened
   * the fold, and a pulsing glyph there claims content is still arriving.
   */
  phase?: Phase
}) => {
  const content = activityContent(entry)

  // This component's own body markup, kept exactly as it is so that handing it
  // to `ToolResult` as the fallback changes nothing about an entry with no
  // artifact. Empty is a real state and it is the first one: a delta
  // accumulator starts at "" and a whole-message entry can carry only calls.
  // It gets no body element at all rather than an empty one, because
  // `Markdown` answers an empty source with "(empty file)" -- correct for the
  // file viewer it was written for, nonsense under a turn that has simply not
  // said anything yet.
  const body = content.text ? (
    content.form === 'prose' ? (
      <Markdown className="provisional-body" source={content.text} />
    ) : (
      <div className="provisional-body mono">{content.text}</div>
    )
  ) : null

  return (
    <div className={clsx('provisional', `provisional-${entry.kind}`)}>
      {tag === null ? null : <div className="provisional-tag">{tag}</div>}
      <ToolResult message={activityMessage(entry)} phase={phase} fallback={body} />
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
