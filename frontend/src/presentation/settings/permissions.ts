import { createContext, useContext } from 'react'

/** May this caller write this key at this scope?
 *
 * **W-B has not shipped and the resolved response carries no capability
 * field.** This is the seam it will fill: one function, defaulting to `() =>
 * true`, consulted before a row renders a live control. When a capability
 * arrives it fills this function and no component changes.
 *
 * The trap this is built against is the one CLAUDE.md records under the
 * interaction log, and it applies exactly: **a permissive default makes "never
 * wired up" and "working" identical to a test.** A test that renders with the
 * default and asserts nothing threw would pass with every call site deleted.
 * So `SettingRow.test.tsx` drives a `canEdit` that answers *no* and asserts
 * the row is read-only and its control is absent from the tab order — that
 * assertion fails if the prop stops being read, which the permissive one
 * cannot.
 *
 * A context rather than a prop threaded from the page, for one reason: it has
 * to reach the secret field and the clear confirm as well as the row's own
 * control, and three props down two levels is three places to forget one.
 */
export type CanEdit = (key: string) => boolean

const ALLOW_ALL: CanEdit = () => true

const CanEditContext = createContext<CanEdit>(ALLOW_ALL)

export const CanEditProvider = CanEditContext.Provider

export const useCanEdit = (): CanEdit => useContext(CanEditContext)

/** Why a row is read-only, in the row's own words.
 *
 * Two spellings and not one, because the two reach a reader at different
 * moments and only one of them is a surprise: `denied` is the answer before
 * anything was pressed, and `forbidden` is a 403 that came back from a `PUT`
 * the page believed would work — which means `canEdit` and the server
 * disagree, and saying so is more useful than repeating the first sentence. */
export const DENIED_COPY = 'You cannot change this setting at this scope.'
export const FORBIDDEN_COPY =
  'The server refused this change (403). Your permissions may have changed — reload to see what you can edit.'
