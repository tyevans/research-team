import { expect, it } from 'vitest'

import { installId, newBrowserSessionId } from './install-identity.ts'

const storage = (): Storage => {
  const map = new Map<string, string>()
  return {
    getItem: (key) => map.get(key) ?? null,
    setItem: (key, value) => void map.set(key, value),
    removeItem: (key) => void map.delete(key),
    clear: () => map.clear(),
    key: () => null,
    length: 0,
  }
}

it('mints an install id once and remembers it', () => {
  /** The only thing that lets a count say "on nine separate days" rather than
   *  "in nine separate tabs". */
  const store = storage()

  const first = installId(store)
  const second = installId(store)

  expect(first).toBe(second)
})

it('survives junk left by an older build', () => {
  /** The preference store's reasoning applies here too: storage outlives the
   *  code that wrote it. */
  const store = storage()
  store.setItem('research-team.install-id', 'not-a-uuid')

  expect(installId(store)).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/)
})

it('still returns an id when storage throws', () => {
  /** localStorage throws in private mode and where it is disabled. An install
   *  id that cannot persist is worth more than a console that cannot load. */
  const hostile = {
    getItem: () => {
      throw new Error('denied')
    },
    setItem: () => {
      throw new Error('denied')
    },
  } as unknown as Storage

  expect(installId(hostile)).toHaveLength(36)
})

it('gives every page load its own browser session id', () => {
  expect(newBrowserSessionId()).not.toBe(newBrowserSessionId())
})
