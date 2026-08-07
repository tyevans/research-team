import clsx from 'clsx'
import { useEffect, useMemo, useRef, useState } from 'react'

import {
  contentText,
  safeJson,
  summariseArgs,
  truncate,
  type Message,
} from '@domain/conversation/message.ts'
import {
  segmentHasError,
  segmentTranscript,
  tallyTools,
  type TranscriptSegment,
} from '@domain/conversation/transcript.ts'
import { compactedThrough, type SessionProjection } from '@domain/session/session.ts'

import { Chip, Disclosure, EmptyState, ErrorBox } from '../common/primitives.tsx'
import { Markdown } from '../common/content.tsx'
import { plural } from '../formatting/format.ts'

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

const Segments = ({
  segments,
  open,
  onToggle,
}: {
  segments: readonly TranscriptSegment[]
  open: ReadonlySet<string>
  onToggle: (key: string) => void
}) => (
  <>
    {segments.map((segment) =>
      segment.kind === 'message' ? (
        <MessageBubble
          key={`m${segment.at}`}
          message={segment.message}
          index={segment.at}
          open={open}
          onToggle={onToggle}
        />
      ) : (
        <ToolRun
          key={`r${segment.at}`}
          messages={segment.messages}
          index={segment.at}
          open={open}
          onToggle={onToggle}
        />
      ),
    )}
  </>
)

/** Collapsed is the default: a run is machinery, and the prose around it is
 *  what the conversation is actually saying. */
const ToolRun = ({
  messages,
  index,
  open,
  onToggle,
}: {
  messages: readonly Message[]
  index: number
  open: ReadonlySet<string>
  onToggle: (key: string) => void
}) => {
  const key = `run:${index}`
  const tally = tallyTools(messages)
  // Results arrive as their own messages, so a run with no calls in it at all
  // is possible on a replay that starts mid-turn. Count messages instead.
  const count = tally.total || messages.length

  return (
    <Disclosure
      className="run"
      open={open.has(key)}
      onToggle={() => onToggle(key)}
      label={
        <span className="run-label">
          <b>{plural(count, 'tool call')}</b>
          {tally.label ? <span className="run-names"> · {tally.label}</span> : null}
          {segmentHasError(messages) ? <Chip tone="fail">error</Chip> : null}
        </span>
      }
    >
      <div className="run-msgs">
        {messages.map((message, offset) => (
          <MessageBubble
            key={index + offset}
            message={message}
            index={index + offset}
            open={open}
            onToggle={onToggle}
            insideRun
          />
        ))}
      </div>
    </Disclosure>
  )
}

const MessageBubble = ({
  message,
  index,
  open,
  onToggle,
  insideRun = false,
}: {
  message: Message
  index: number
  open: ReadonlySet<string>
  onToggle: (key: string) => void
  insideRun?: boolean
}) => {
  const text = contentText(message.content)
  const calls = message.toolCalls
  const callsKey = `calls:${index}`

  const callList = (
    <div className="calls">
      {calls.map((call, position) => (
        <div key={position} className="call" title={safeJson(call.args)}>
          <b>{call.name || 'tool'}</b>
          {summariseArgs(call.args) ? (
            <span className="arg">{`  ${summariseArgs(call.args)}`}</span>
          ) : null}
        </div>
      ))}
    </div>
  )

  return (
    <div className={clsx('msg', `msg-${message.role}`, message.isError && 'errored')}>
      <div className="msg-head">
        <span>{message.role}</span>
        {message.isError ? <Chip tone="fail">error</Chip> : null}
      </div>

      {text ? (
        // The model writes markdown, so assistant turns render as markdown.
        // Tool results do not: they are data, and their value is being shown
        // byte-for-byte. User messages stay literal for the same reason — what
        // was typed is what was sent. An errored turn stays literal too, since
        // a raw failure is easier to read than a half-parsed one.
        message.role === 'assistant' && !message.isError ? (
          <div className="msg-body">
            <Markdown source={text} />
          </div>
        ) : (
          <div className={clsx('msg-body', message.role === 'tool' && 'mono')}>
            {message.role === 'tool' ? truncate(text, 4000) : text}
          </div>
        )
      ) : calls.length === 0 ? (
        <div className="msg-body mono">(no content)</div>
      ) : null}

      {calls.length > 0 ? (
        // A message that also said something keeps its own fold, so the prose is
        // what you see first. Inside a run the fold is already above us.
        insideRun || !text ? (
          callList
        ) : (
          <Disclosure
            open={open.has(callsKey)}
            onToggle={() => onToggle(callsKey)}
            label={
              <span className="run-label">
                <b>{plural(calls.length, 'tool call')}</b>
                {tallyTools([message]).label ? (
                  <span className="run-names"> · {tallyTools([message]).label}</span>
                ) : null}
              </span>
            }
          >
            {callList}
          </Disclosure>
        )
      ) : null}
    </div>
  )
}

/** Nothing was deleted — the log still holds every message, and so does this
 *  pane. What changed is what the *model* is shown: a summary standing in for
 *  everything above the boundary. That distinction is the visible idea here. */
const Compaction = ({
  summary,
  hidden,
  through,
  open,
  onToggle,
}: {
  summary: string
  hidden: readonly Message[]
  through: number
  open: ReadonlySet<string>
  onToggle: (key: string) => void
}) => (
  <section className="compaction" aria-label="compacted context">
    <div className="compaction-head">
      <span className="compaction-mark" aria-hidden="true" />
      <span className="compaction-title">
        context compacted — the model sees a summary of the first {plural(through, 'message')}
      </span>
    </div>

    {summary ? (
      <Disclosure
        label="summary shown to the model"
        open={!open.has('compaction:summary:closed')}
        onToggle={() => onToggle('compaction:summary:closed')}
      >
        <div className="compaction-summary">{summary}</div>
      </Disclosure>
    ) : (
      <div className="compaction-note">no summary text was returned with this session.</div>
    )}

    <Disclosure
      label={`${plural(through, 'superseded message')} — still in the log, not sent to the model`}
      open={open.has('compaction:messages')}
      onToggle={() => onToggle('compaction:messages')}
    >
      <div className="compaction-msgs">
        <Segments segments={segmentTranscript(hidden, 0)} open={open} onToggle={onToggle} />
      </div>
    </Disclosure>

    <div className="compaction-boundary">
      <span>context boundary · everything below is sent verbatim</span>
    </div>
  </section>
)
