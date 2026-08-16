/** `activityName` narrows an `unknown` payload rather than casting it, because
 *  the fold stores stream frames without interpreting them and a frame whose
 *  shape changes server-side must degrade rather than throw inside a render.
 *
 *  The payload shape asserted here is langchain's `message_to_dict` output,
 *  `{type, data}` -- the shape the server actually sends -- not a flat
 *  `{name}`. A flat fixture is what let this exact function pass its test
 *  while reading `item.kind` in production; the case below (a genuine
 *  server-shaped payload) is the one that would have caught it. */
import { expect, it } from 'vitest'

import { activityName, activityRows } from './AskActivity.tsx'
import { activity, assistantCall, toolResult } from './ask-fixtures.ts'

it('names a tool frame by the tool it carried, nested under data.name', () => {
  expect(activityName(activity({ payload: { type: 'tool', data: { name: 'read_source' } } }))).toBe(
    'read_source',
  )
})

it('names an assistant frame by its first tool call, with an argument preview', () => {
  expect(
    activityName(
      activity({
        kind: 'assistant',
        payload: {
          type: 'ai',
          data: { tool_calls: [{ name: 'search_findings', args: { query: 'spaced review' } }] },
        },
      }),
    ),
  ).toBe('search_findings(query=spaced review)')
})

it('falls back to the frame kind when the payload names nothing', () => {
  // Not a cast: a payload that is a string, a null, an object with no `data`,
  // a `data` with a non-string `name`, or empty tool_calls all reach here,
  // and each would throw on a cast.
  expect(activityName(activity({ payload: 'surprise', kind: 'tool' }))).toBe('tool')
  expect(activityName(activity({ payload: null, kind: 'assistant' }))).toBe('assistant')
  expect(activityName(activity({ payload: { type: 'tool' }, kind: 'tool' }))).toBe('tool')
  expect(
    activityName(activity({ payload: { type: 'tool', data: { name: 42 } }, kind: 'tool' })),
  ).toBe('tool')
  expect(
    activityName(activity({ payload: { type: 'tool', data: { name: '' } }, kind: 'tool' })),
  ).toBe('tool')
  expect(
    activityName(
      activity({ payload: { type: 'ai', data: { tool_calls: [] } }, kind: 'assistant' }),
    ),
  ).toBe('assistant')
})

it('joins a result to the call that asked for it, on one row', () => {
  // The defect this function exists to fix: two rows per call, the second of
  // them the bare tool name and therefore worth nothing to a reader.
  const rows = activityRows([
    assistantCall({ name: 'graph_search', args: { query: 'Imperial Cult' }, id: 'c1' }),
    toolResult({
      name: 'graph_search',
      callId: 'c1',
      content: 'Imperial cult (concept) -- 12 rel',
    }),
  ])

  expect(rows).toHaveLength(1)
  expect(rows[0]?.name).toBe('graph_search(query=Imperial Cult)')
  expect(rows[0]?.result).toBe('Imperial cult (concept) -- 12 rel')
})

it('shows every call an assistant frame dispatched, not just the first', () => {
  // Would pass against the old `calls[0]` reading if it asserted one row, so
  // it asserts both names.
  const rows = activityRows([
    activity({
      messageId: 'm1',
      kind: 'assistant',
      payload: {
        type: 'ai',
        data: {
          tool_calls: [
            { name: 'list_sources', args: {}, id: 'c1' },
            { name: 'read_source', args: { source_id: 'wiki-cult' }, id: 'c2' },
          ],
        },
      },
    }),
  ])

  expect(rows.map((row) => row.name)).toEqual(['list_sources', 'read_source(source_id=wiki-cult)'])
})

it('summarises a multi-line result by its first line and a count of the rest', () => {
  const rows = activityRows([
    assistantCall({ name: 'list_sources', id: 'c1' }),
    toolResult({
      name: 'list_sources',
      callId: 'c1',
      content: '3 source(s) in the corpus:\n  a -- 10 chars\n\n  b -- 20 chars',
    }),
  ])

  // Blank lines are not counted: they are formatting, and a reader counting
  // sources would be told the wrong number.
  expect(rows[0]?.result).toBe('3 source(s) in the corpus:  +2 lines')
})

it('truncates a long first line rather than letting one row wrap the fold', () => {
  const rows = activityRows([
    assistantCall({ name: 'read_source', id: 'c1' }),
    toolResult({ name: 'read_source', callId: 'c1', content: 'x'.repeat(200) }),
  ])

  expect(rows[0]?.result).toHaveLength(80)
  expect(rows[0]?.result?.endsWith('…')).toBe(true)
})

it('keeps a result whose call was never seen, rather than dropping it', () => {
  // A turn caught mid-flight, or a call frame lost to a reconnect: the result
  // is the only trace of the tool run that exists, so it gets its own row.
  const rows = activityRows([
    toolResult({ name: 'grep', callId: 'orphan', content: 'No matches.' }),
  ])

  expect(rows).toHaveLength(1)
  expect(rows[0]?.name).toBe('grep')
  expect(rows[0]?.result).toBe('No matches.')
})

it('leaves a call with no result yet showing as a call', () => {
  const rows = activityRows([
    assistantCall({ name: 'graph_search', args: { query: 'x' }, id: 'c1' }),
  ])

  expect(rows).toHaveLength(1)
  expect(rows[0]?.result).toBe(null)
})

it("carries the result frame's error onto the row the call is on", () => {
  // The chip lives on the joined row now, and the frame that knows about the
  // failure is the result -- the call frame that dispatched it is not marked.
  const rows = activityRows([
    assistantCall({ name: 'read_source', args: { source_id: 'nope' }, id: 'c1' }),
    toolResult({ name: 'read_source', callId: 'c1', content: 'No source', isError: true }),
  ])

  expect(rows[0]?.isError).toBe(true)
})

it('degrades to a named row when a frame carries no calls and no result', () => {
  expect(activityRows([activity({ payload: 'surprise', kind: 'tool' })])).toEqual([
    { key: 'm1', name: 'tool', result: null, isError: false },
  ])
})
