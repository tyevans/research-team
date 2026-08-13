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

import { activityName } from './AskActivity.tsx'
import { activity } from './ask-fixtures.ts'

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
