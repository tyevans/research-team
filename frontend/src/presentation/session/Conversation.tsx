import { useEffect, useMemo, useRef, useState } from 'react'

import { segmentTranscript } from '@domain/conversation/transcript.ts'
import { compactedThrough, type SessionProjection } from '@domain/session/session.ts'

import { EmptyState, ErrorBox } from '../common/primitives.tsx'
import { Compaction } from './Compaction.tsx'
import { Segments } from './Segments.tsx'

/** Everything said, in order, with the machinery folded.
 *
 * The pane sticks to the bottom only when it was already near it: a reader who
 * has scrolled up to follow something is reading, and yanking them back down
 * when a frame arrives is the fastest way to make a live view unusable. */
export const Conversation = ({
  view,
  error,
  historicalAt,
  emptyDetail = 'Send the first turn below.',
}: {
  view: SessionProjection | null
  error: string | null
  historicalAt: number | null
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

  useEffect(() => {
    if (stick.current && box.current) box.current.scrollTop = box.current.scrollHeight
  }, [messages])

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
        <ErrorBox title="Unavailable" message={error} />
      ) : messages.length === 0 ? (
        <EmptyState
          title="No conversation yet."
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
        </div>
      )}
    </div>
  )
}
