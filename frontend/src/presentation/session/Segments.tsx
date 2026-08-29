import clsx from 'clsx'

import {
  argDetail,
  contentText,
  summariseArgs,
  truncate,
  type Message,
} from '@domain/conversation/message.ts'
import {
  segmentHasError,
  tallyTools,
  type TranscriptSegment,
} from '@domain/conversation/transcript.ts'

import { Chip, Disclosure } from '../common/primitives.tsx'
import { Markdown } from '../common/content.tsx'
import { plural } from '../formatting/format.ts'
import { ToolResult } from './shapes/ToolResult.tsx'

export const Segments = ({
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
      {calls.map((call, position) => {
        const preview = summariseArgs(call.args)
        const argsKey = `args:${index}:${position}`
        const head = (
          <span className="call">
            <b>{call.name || 'tool'}</b>
            {preview ? <span className="arg">{`  ${preview}`}</span> : null}
          </span>
        )
        // A call that took nothing has nothing to open, and a disclosure over
        // an empty body is a control that punishes the reader for trying it.
        return preview ? (
          <Disclosure
            key={position}
            className="call-args"
            open={open.has(argsKey)}
            onToggle={() => onToggle(argsKey)}
            label={head}
          >
            {/* Bounded, and the bound is the point: `remember` takes 20,000
                characters of `text`, which is more than the conversation
                around it. */}
            <pre className="call-detail">{argDetail(call.args)}</pre>
          </Disclosure>
        ) : (
          <div key={position} className="call">
            <b>{call.name || 'tool'}</b>
          </div>
        )
      })}
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
        ) : message.role === 'tool' ? (
          // A tool result is drawn from its artifact where it has one, and from
          // this exact markup where it does not — which is every message
          // written before artifacts existed, so the fallback is the common
          // case on real history rather than an error path.
          <div className="stream">
            <ToolResult
              message={message}
              phase="settled"
              fallback={<div className="msg-body mono">{truncate(text, 4000)}</div>}
            />
          </div>
        ) : (
          <div className="msg-body">{text}</div>
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
