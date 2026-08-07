import { describe, expect, it } from 'vitest'

import { contentText, isToolActivity, safeJson, summariseArgs, truncate, type Message } from './message.ts'

const message = (over: Partial<Message>): Message => ({
  role: 'assistant',
  content: '',
  toolCalls: [],
  isError: false,
  ...over,
})

describe('contentText', () => {
  it('passes a plain string through', () => {
    expect(contentText('hello')).toBe('hello')
  })

  it('joins langchain’s block list', () => {
    expect(contentText([{ text: 'one' }, { text: 'two' }])).toBe('one\ntwo')
  })

  it('reads either key a block might carry, and skips the ones with neither', () => {
    expect(contentText([{ text: 'a' }, { content: 'b' }, { image: 'x' }, 'c'])).toBe('a\nb\nc')
  })

  it('is empty for nothing', () => {
    expect(contentText(null)).toBe('')
    expect(contentText(undefined)).toBe('')
  })

  it('shows an unrecognised shape as JSON rather than as [object Object]', () => {
    // A shape this does not recognise is still something a reader needs to see.
    expect(contentText({ odd: true })).toContain('"odd"')
  })
})

describe('isToolActivity', () => {
  it('counts a tool result as machinery', () => {
    expect(isToolActivity(message({ role: 'tool', content: 'output' }))).toBe(true)
  })

  it('counts a wordless dispatch as machinery', () => {
    expect(isToolActivity(message({ toolCalls: [{ name: 'Read', args: {} }] }))).toBe(true)
  })

  it('never counts prose as machinery, however many calls came with it', () => {
    // The prose is what the conversation is actually saying, and it is never
    // what gets folded away.
    expect(
      isToolActivity(message({ content: 'Reading it now.', toolCalls: [{ name: 'Read', args: {} }] })),
    ).toBe(false)
  })

  it('does not fold a user message', () => {
    expect(isToolActivity(message({ role: 'user', content: 'go' }))).toBe(false)
  })
})

describe('summariseArgs', () => {
  it('prefers the argument that says what the call acted on', () => {
    expect(summariseArgs({ recursive: true, path: '/a.md' })).toBe('path=/a.md  +1')
  })

  it('falls back to the first key for a tool it does not know', () => {
    expect(summariseArgs({ topic: 'knitting' })).toBe('topic=knitting')
  })

  it('is empty for no arguments at all', () => {
    expect(summariseArgs({})).toBe('')
    expect(summariseArgs(null)).toBe('')
  })

  it('renders a non-string value rather than dropping it', () => {
    expect(summariseArgs({ limit: 20 })).toBe('limit=20')
  })

  it('truncates a long value so the row stays one line', () => {
    expect(summariseArgs({ query: 'x'.repeat(200) })).toContain('…')
  })
})

describe('safeJson', () => {
  it('renders an ordinary value', () => {
    expect(safeJson({ a: 1 })).toBe('{\n  "a": 1\n}')
  })

  it('does not throw on a cycle', () => {
    const cyclic: Record<string, unknown> = {}
    cyclic['self'] = cyclic
    expect(() => safeJson(cyclic)).not.toThrow()
    expect(safeJson(cyclic)).not.toBe('[object Object]')
  })

  it('describes a value JSON drops rather than answering undefined', () => {
    expect(safeJson(undefined)).toBe('')
    expect(safeJson(() => 1)).toContain('Function')
  })
})

describe('truncate', () => {
  it('leaves a short string alone', () => {
    expect(truncate('short', 10)).toBe('short')
  })

  it('marks where it cut', () => {
    expect(truncate('abcdefghij', 5)).toBe('abcd…')
  })

  it('is empty for nothing', () => {
    expect(truncate(null, 10)).toBe('')
  })
})
