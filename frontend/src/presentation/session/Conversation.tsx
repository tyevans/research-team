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
}: {
  view: SessionProjection | null
  error: string | null
  historicalAt: number | null
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
    <div className="pane-body" ref={box} onScroll={onScroll}>
      {error ? (
        <ErrorBox title="Unavailable" message={error} />
      ) : messages.length === 0 ? (
        <EmptyState
          title="No conversation yet."
          detail={
            historicalAt !== null
              ? `Nothing had been said by event ${historicalAt}.`
              : 'Send the first turn below.'
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
