declare const brand: unique symbol

/** A 1-based position in a session's event log.
 *
 * 1-based because that is what the REPL prints and what the API's `/at/{n}`
 * route expects; branding it stops the array offsets used to render the same
 * list from being passed where a log position is meant.
 */
export type EventIndex = number & { readonly [brand]: 'EventIndex' }

export const EventIndex = (raw: number): EventIndex => raw as EventIndex

export const isEventIndex = (value: unknown): value is EventIndex =>
  typeof value === 'number' && Number.isInteger(value) && value >= 1
