import { describe, expect, it } from 'vitest'

import type { Message } from './message.ts'
import { segmentTranscript, tallyTools } from './transcript.ts'

const message = (over: Partial<Message>): Message => ({
  role: 'assistant',
  content: '',
  toolCalls: [],
  isError: false,
  ...over,
})

const call = (name: string) => ({ name, args: {} })

describe('segmentTranscript', () => {
  it('collapses consecutive machinery into one run', () => {
    const segments = segmentTranscript([
      message({ role: 'user', content: 'go' }),
      message({ toolCalls: [call('Read')] }),
      message({ role: 'tool', content: 'contents' }),
      message({ content: 'Here is what I found.' }),
    ])

    expect(segments.map((s) => s.kind)).toEqual(['message', 'toolRun', 'message'])
    expect(segments[1]).toMatchObject({ kind: 'toolRun', at: 1 })
  })

  it('never folds a message that also said something', () => {
    const segments = segmentTranscript([
      message({ content: 'Reading the file now.', toolCalls: [call('Read')] }),
    ])
    expect(segments).toHaveLength(1)
    expect(segments[0]!.kind).toBe('message')
  })

  it('offsets segment positions so they stay stable across a compaction split', () => {
    const segments = segmentTranscript([message({ role: 'user', content: 'hi' })], 12)
    expect(segments[0]!.at).toBe(12)
  })

  it('leaves an empty conversation with no segments', () => {
    expect(segmentTranscript([])).toEqual([])
  })
})

describe('tallyTools', () => {
  it('counts repeats and keeps first-run order', () => {
    const tally = tallyTools([
      message({ toolCalls: [call('Read'), call('Read')] }),
      message({ toolCalls: [call('Bash'), call('Read')] }),
    ])
    expect(tally.total).toBe(4)
    expect(tally.label).toBe('Read ×3, Bash')
  })

  it('is empty for a run with no calls in it at all', () => {
    expect(tallyTools([message({ role: 'tool', content: 'x' })])).toEqual({ total: 0, label: '' })
  })
})
