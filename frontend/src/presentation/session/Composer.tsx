import clsx from 'clsx'
import { useEffect, useState } from 'react'

import { ScrubPoint } from '@domain/session/scrub-point.ts'
import { TurnState, type TurnNote, type TurnRange } from '@domain/session/turn.ts'
import { EventIndex } from '@domain/session/event-index.ts'

import { elapsed, elapsedSince } from '../formatting/format.ts'

interface ComposerProps {
  turn: TurnState
  note: TurnNote | null
  scrub: ScrubPoint
  onSend: (input: string) => void
  onCancel: () => void
  onRecheck: () => void
  onJumpTo: (at: EventIndex) => void
  onTyping: () => void
}

export const Composer = ({
  turn,
  note,
  scrub,
  onSend,
  onCancel,
  onRecheck,
  onJumpTo,
  onTyping,
}: ComposerProps) => {
  const [draft, setDraft] = useState('')
  const busy = TurnState.isBusy(turn)
  const cancelling = TurnState.isCancelRequested(turn)

  const submit = (event: React.FormEvent) => {
    event.preventDefault()
    if (busy || !draft.trim()) return
    onSend(draft)
    setDraft('')
  }

  return (
    <form className="composer" onSubmit={submit}>
      <textarea
        rows={2}
        placeholder="Send a turn…  (Ctrl+Enter)"
        value={draft}
        disabled={busy}
        onChange={(event) => {
          setDraft(event.target.value)
          // Once you start writing the next turn, the last one's outcome is
          // history.
          onTyping()
        }}
        onKeyDown={(event) => {
          if (event.key === 'Enter' && (event.ctrlKey || event.metaKey)) submit(event)
        }}
      />
      <div className="composer-row">
        <Hint turn={turn} note={note} scrub={scrub} onRecheck={onRecheck} onJumpTo={onJumpTo} />
        <div className="composer-actions">
          {busy ? (
            <button
              type="button"
              className="btn btn-quiet"
              disabled={cancelling}
              onClick={onCancel}
            >
              {cancelling ? 'Cancelling…' : 'Cancel turn'}
            </button>
          ) : null}
          <button type="submit" className="btn btn-accent" disabled={busy}>
            {turn.status === 'sending'
              ? 'Running…'
              : turn.status === 'watching'
                ? 'Turn running'
                : 'Send turn'}
          </button>
        </div>
      </div>
    </form>
  )
}

const Hint = ({
  turn,
  note,
  scrub,
  onRecheck,
  onJumpTo,
}: {
  turn: TurnState
  note: TurnNote | null
  scrub: ScrubPoint
  onRecheck: () => void
  onJumpTo: (at: EventIndex) => void
}) => {
  const busy = TurnState.isBusy(turn)
  const now = useTick(busy)
  const historical = ScrubPoint.isHistorical(scrub)
  const tone = busy ? 'busy' : note ? note.tone : historical ? 'warn' : ''

  if (busy) {
    return (
      <span className={clsx('composer-hint', tone)}>
        <span className="spinner" />
        <span className="txt">
          {TurnState.isCancelRequested(turn)
            ? 'cancelling — waiting for the turn to unwind'
            : turn.status === 'sending'
              ? sendingLabel(turn.startedAt, now)
              : watchedLabel(turn, now)}
        </span>
      </span>
    )
  }

  if (note) {
    return (
      <span className={clsx('composer-hint', tone)}>
        <span className="txt">{note.text}</span>
        {note.range ? <RangeChip range={note.range} onJumpTo={onJumpTo} /> : null}
        {note.recheck ? (
          <button type="button" className="turn-range" onClick={onRecheck}>
            re-check
          </button>
        ) : null}
      </span>
    )
  }

  return (
    <span className={clsx('composer-hint', tone)}>
      <span className="txt">
        {historical
          ? 'viewing history — a turn appends to HEAD; fork to branch from here'
          : 'Ctrl+Enter to send · ↑/↓ in the log to scrub'}
      </span>
    </span>
  )
}

/** A turn saves atomically at the end, so *nothing* reaches the event stream
 *  while it runs — every frame lands at once when it commits. There is no
 *  per-tool progress to show, and claiming otherwise would be a lie. Elapsed
 *  time is the one thing that genuinely moves, so that is what is reported. */
const sendingLabel = (startedAt: number, now: number): string => {
  const age = elapsed(startedAt, now)
  return `turn in flight${age ? ` · ${age}` : ''} — events appear when it completes`
}

const watchedLabel = (turn: TurnState, now: number): string => {
  if (turn.status !== 'watching') return 'a turn started elsewhere is running on this session'
  const { turnIndex, startedAt, elapsedSeconds } = turn.turn
  const age = elapsedSince(startedAt, elapsedSeconds, now)
  return [
    typeof turnIndex === 'number' ? `turn ${turnIndex}` : null,
    age === null ? 'running elsewhere' : `started ${age} ago, elsewhere`,
    'events appear when it completes',
  ]
    .filter(Boolean)
    .join(' · ')
}

/** "turn 3 · events 14–21" — clicking scrubs to where the turn began. */
const RangeChip = ({
  range,
  onJumpTo,
}: {
  range: TurnRange
  onJumpTo: (at: EventIndex) => void
}) => (
  <button
    type="button"
    className="turn-range"
    title={`jump to event ${range.from}`}
    onClick={() => onJumpTo(range.from)}
  >
    {typeof range.turnIndex === 'number' ? `turn ${range.turnIndex} · ` : ''}
    {range.from === range.to ? `event ${range.from}` : `events ${range.from}–${range.to}`}
  </button>
)

/** A one-second repaint while a turn runs, so the elapsed label stays honest.
 *  Display only — it issues no requests. */
const useTick = (active: boolean): number => {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    if (!active) return
    const timer = setInterval(() => setNow(Date.now()), 1_000)
    return () => clearInterval(timer)
  }, [active])
  return now
}
