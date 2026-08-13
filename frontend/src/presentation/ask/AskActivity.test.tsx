/** `activityName` narrows an `unknown` payload rather than casting it, because
 *  the fold stores stream frames without interpreting them and a frame whose
 *  shape changes server-side must degrade rather than throw inside a render. */
import { expect, it } from 'vitest'

import { activityName } from './AskActivity.tsx'
import { activity } from './ask-fixtures.ts'

it('names a frame by the tool it carries', () => {
  expect(activityName(activity({ payload: { name: 'read_source' } }))).toBe('read_source')
})

it('falls back to the frame kind when the payload names nothing', () => {
  // Not a cast: a payload that is a string, a null, or an object with a
  // non-string `name` all reach here, and each would throw on a cast.
  expect(activityName(activity({ payload: 'surprise', kind: 'tool' }))).toBe('tool')
  expect(activityName(activity({ payload: null, kind: 'assistant' }))).toBe('assistant')
  expect(activityName(activity({ payload: { name: 42 }, kind: 'tool' }))).toBe('tool')
  expect(activityName(activity({ payload: { name: '' }, kind: 'tool' }))).toBe('tool')
})
