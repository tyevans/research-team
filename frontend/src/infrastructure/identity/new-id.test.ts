import { afterEach, describe, expect, it } from 'vitest'

import { newId } from './new-id.ts'

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/

/** Hide one `crypto` method for one test, the way a plain-http origin does.
 *
 * `delete crypto.randomUUID` does nothing -- the methods live on
 * `Crypto.prototype`, not the instance, and a probe asserting the deletion
 * took effect failed on exactly that. So shadow the name with an own property
 * holding `undefined` and remove the shadow afterwards. That is not quite what
 * an insecure origin does (there the property is absent from the prototype
 * too), but it is what the module's `typeof ... === 'function'` guards
 * actually read, so the branch under test is the one that runs. */
const hide = (name: 'randomUUID' | 'getRandomValues'): (() => void) => {
  Object.defineProperty(crypto, name, { value: undefined, configurable: true })
  return () => Reflect.deleteProperty(crypto, name)
}

describe('newId', () => {
  const undo: Array<() => void> = []
  afterEach(() => {
    while (undo.length > 0) undo.pop()?.()
  })

  it('answers a v4 uuid where crypto.randomUUID exists', () => {
    expect(newId()).toMatch(UUID)
  })

  /** The whole point of the module: it fails with the fallback removed. The
   *  ask page threw here rather than on the first question, because `AskView`
   *  builds its chat id during render. */
  it('answers a v4 uuid on an origin with no crypto.randomUUID', () => {
    undo.push(hide('randomUUID'))
    expect(newId()).toMatch(UUID)
  })

  it('answers a v4 uuid with no web crypto at all', () => {
    undo.push(hide('randomUUID'), hide('getRandomValues'))
    expect(newId()).toMatch(UUID)
  })

  it('does not repeat itself without randomUUID', () => {
    undo.push(hide('randomUUID'))
    const ids = new Set(Array.from({ length: 500 }, newId))
    expect(ids.size).toBe(500)
  })
})
