import { useEffect, useMemo, useRef, useState } from 'react'

import type { ActivityEntry } from '@domain/activity/activity.ts'
import { segmentTranscript } from '@domain/conversation/transcript.ts'
import { compactedThrough, type SessionProjection } from '@domain/session/session.ts'

import { EmptyState, ErrorBox } from '../common/primitives.tsx'
import { Compaction } from './Compaction.tsx'
import { LiveTail } from './Provisional.tsx'
import { Segments } from './Segments.tsx'

/** Everything said, in order, with the machinery folded.
 *
 * **Including what is being said right now.** The turn in flight used to be a
 * sibling of this component — its own box, with its own scroller and its own
 * `max-height: 50%`, pinned below the transcript. That split the pane into
 * "what has been said" and "what is being said" as two *regions*, and the
 * reader paid for it twice: a session with nothing recorded yet showed "No
 * conversation yet" over a tray that was visibly streaming, and the
 * stick-to-bottom ref below governed the half that was not moving. Live
 * entries are now the last items in this list, and they say they are live by
 * how they are drawn rather than by where they sit.
 *
 * The pane sticks to the bottom only when it was already near it: a reader who
 * has scrolled up to follow something is reading, and yanking them back down
 * when a frame arrives is the fastest way to make a live view unusable. */
export const Conversation = ({
  view,
  error,
  historicalAt,
  activity = [],
  emptyDetail = 'Send the first turn below.',
}: {
  view: SessionProjection | null
  error: string | null
  historicalAt: number | null
  /** The turn in flight, already gated on whether one is running.
   *
   * Empty when nothing is streaming, which is also what a caller with no live
   * channel at all passes — a story, or a historical fold. */
  activity?: readonly ActivityEntry[]
  /** What an empty transcript means, worded for whoever is looking at it.
   *
   * Defaults to the session route's wording, which assumes a composer sits
   * below this pane — true there, but not for every caller. `WorkerDrawer`
   * reuses this component read-only, with no composer anywhere in it, so
   * the default would tell a reader to do something they cannot do. Callers
   * without a composer must say so explicitly rather than inherit a
   * prompt to act that their view can't fulfil. */
  emptyDetail?: string
}) => {
  const box = useRef<HTMLDivElement | null>(null)
  const stick = useRef(true)
  const [open, setOpen] = useState<ReadonlySet<string>>(new Set())

  const messages = useMemo(() => view?.messages ?? [], [view?.messages])

  // `activity` as well as `messages`: streaming frames are the case this
  // scroll behaviour exists for, and while the live tail was a separate
  // scroller they were the one thing that never triggered it.
  useEffect(() => {
    if (stick.current && box.current) box.current.scrollTop = box.current.scrollHeight
  }, [messages, activity])

  const onScroll = () => {
    const element = box.current
    if (!element) return
    stick.current = element.scrollHeight - element.scrollTop - element.clientHeight < 80
  }

  const toggle = (key: string) =>
    setOpen((current) => {
      const next = new Set(current)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })

  const through = compactedThrough(view?.compactedThrough, messages.length)

  return (
    // Its own class rather than `.pane-body`, which was the last thing in the
    // console still borrowing the old pane stylesheet's name for a box that is
    // not a pane body. This *is* the scroller -- the ref is on it so the view
    // can stick to the bottom -- and it sits inside a `Pane` whose own body is
    // `scroll="regions"` and therefore does not scroll. Two elements with one
    // class name meaning two different things is how `.pane-body` came to be
    // re-specified in three stylesheets.
    <div className="conv-scroll" ref={box} onScroll={onScroll}>
      {error ? (
        <ErrorBox heading="Unavailable" message={error} />
      ) : messages.length === 0 && activity.length === 0 ? (
        <EmptyState
          heading="No conversation yet."
          detail={
            historicalAt !== null ? `Nothing had been said by event ${historicalAt}.` : emptyDetail
          }
        />
      ) : (
        <div className="conv">
          {through > 0 ? (
            <Compaction
              summary={view?.compactionSummary ?? ''}
              hidden={messages.slice(0, through)}
              through={through}
              open={open}
              onToggle={toggle}
            />
          ) : null}
          <Segments
            segments={segmentTranscript(messages.slice(through), through)}
            open={open}
            onToggle={toggle}
          />
          <LiveTail entries={activity} />
        </div>
      )}
    </div>
  )
}
