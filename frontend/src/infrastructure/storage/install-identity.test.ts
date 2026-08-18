import { afterEach, expect, it } from 'vitest'

import { installId, newBrowserSessionId } from './install-identity.ts'

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/

/** `crypto.randomUUID` is unavailable outside a secure context, so this is
 *  what a console served over plain http on a LAN actually runs.
 *
 *  Shadowed with `defineProperty` rather than deleted: `randomUUID` lives on
 *  `Crypto.prototype`, so `Reflect.deleteProperty(crypto, ...)` removes an own
 *  property that was never there and the real function is still reached
 *  through the prototype. That silently ran the whole test against the
 *  *secure* path, which is a test that cannot fail. */
const withoutRandomUUID = (body: () => void) => {
  const real = crypto.randomUUID.bind(crypto)
  Object.defineProperty(crypto, 'randomUUID', { value: undefined, configurable: true })
  try {
    body()
  } finally {
    Object.defineProperty(crypto, 'randomUUID', { value: real, configurable: true })
  }
}

afterEach(() => {
  expect(typeof crypto.randomUUID).toBe('function')
})

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

it('mints an id it will accept again on the next load without randomUUID', () => {
  /** The fallback mint built 12-4-4-4-12 groups, which `UUID_PATTERN` rejects.
   *  The id was stored, rejected as malformed on the next load, and re-minted
   *  -- so `install_id` changed on every page load in exactly the context the
   *  fallback exists for, which is the one thing the field must not do. It
   *  did not fail ingest, so nothing was loud about it.
   *
   *  Proved red against the old mint: received
   *  `01a013736a70-0000-4000-8000-9e6b2dec` -- 12 hex digits in the first
   *  group, 32 in total. The stability assertion below never ran, because the
   *  shape assertion fails first; it is there because the shape is only the
   *  mechanism and re-minting is the actual defect. */
  withoutRandomUUID(() => {
    const store = storage()

    const first = installId(store)

    expect(first).toMatch(UUID)
    expect(installId(store)).toBe(first)
  })
})

it('gives every page load its own browser session id', () => {
  expect(newBrowserSessionId()).not.toBe(newBrowserSessionId())
})
