/** Who and which tab, for counting distinct days rather than distinct loads.
 *
 * A module rather than a port: unlike preferences there is one
 * implementation, and the storage failure modes are handled here for the same
 * reasons `LocalPreferenceStore` handles them -- storage throws in private
 * mode, and a browser carries junk written by an older build.
 *
 * In `infrastructure/storage` beside `LocalPreferenceStore`, not in
 * `application/interaction-log` where it started. Skipping the port is a fair
 * call for one implementation; putting the `localStorage` touch in the
 * application layer is not, and the two were being justified by one argument.
 * The layer is about which code may reach the browser, not about how many
 * implementations there are.
 */

const INSTALL_KEY = 'research-team.install-id'

const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/

const hex = (length: number): string => {
  let out = ''
  while (out.length < length) out += Math.random().toString(16).slice(2)
  return out.slice(0, length)
}

/** Not cryptographic, and does not need to be: this identifies an install for
 *  counting and nothing trusts it.
 *
 *  **The groups have to be 8-4-4-4-12, and the first version of this was
 *  12-4-4-4-12.** `crypto.randomUUID` is absent on a plain-`http` LAN origin
 *  -- a case this repo has already shipped a fix for -- so the fallback is
 *  exactly the path a non-localhost console takes, and its output failed
 *  `UUID_PATTERN`. The value was written to `localStorage` and rejected as
 *  malformed on the very next load, so `install_id` changed on every page
 *  load in the one context the fallback exists for, defeating the field's
 *  sole purpose ("on nine separate days" rather than "in nine separate
 *  tabs"). It did not fail ingest -- Python's `UUID` accepts 32 hex digits
 *  regardless of dash placement -- so the failure was silent and statistical,
 *  the worst shape. `install-identity.test.ts` round-trips a minted id
 *  through `UUID_PATTERN` with `randomUUID` removed. */
const mint = (): string =>
  typeof crypto !== 'undefined' && crypto.randomUUID
    ? crypto.randomUUID()
    : `${hex(8)}-${hex(4)}-4${hex(3)}-8${hex(3)}-${hex(12)}`

/** The install, across restarts.
 *
 * Pseudonymous, and the exact thing that becomes real identity if this
 * product grows past one user -- named so that growth is a decision.
 *
 * An unreadable or malformed value is replaced rather than trusted: it
 * reaches a UUID column, and a stored non-uuid would fail at ingest for
 * every event forever, which would look like the feature not working.
 */
export const installId = (storage: Storage | undefined = safeStorage()): string => {
  try {
    const stored = storage?.getItem(INSTALL_KEY)
    if (stored && UUID_PATTERN.test(stored)) return stored
    const minted = mint()
    storage?.setItem(INSTALL_KEY, minted)
    return minted
  } catch {
    // Private mode, or storage disabled. An id that does not persist still
    // groups one session's events; refusing to return one would break the
    // console over telemetry, which is the wrong trade.
    return mint()
  }
}

export const newBrowserSessionId = (): string => mint()

const safeStorage = (): Storage | undefined => {
  try {
    return window.localStorage
  } catch {
    return undefined
  }
}
