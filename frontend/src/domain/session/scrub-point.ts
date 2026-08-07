import type { EventIndex } from './event-index.ts'

/** Where in the log the console is currently reading from.
 *
 * The single most load-bearing concept in this application: every pane —
 * workspace, conversation, file contents — is a projection of the log at one
 * point, and "live" is a distinct case rather than "the last index", because
 * the log grows underneath a live reader and does not underneath a historical
 * one.
 *
 * Modelled as a closed union with a constructor per case so that `null meaning
 * HEAD` — which the previous implementation carried in nine separate places —
 * cannot be misread as "not loaded yet".
 */
export type ScrubPoint =
  { readonly kind: 'head' } | { readonly kind: 'historical'; readonly at: EventIndex }

const HEAD: ScrubPoint = Object.freeze({ kind: 'head' as const })

export const ScrubPoint = {
  /** Following the log as it grows. */
  head: (): ScrubPoint => HEAD,

  /** Pinned to one event, with the log folded to that moment. */
  at: (index: EventIndex): ScrubPoint => ({ kind: 'historical', at: index }),

  /** The wire/route representation: a number, or null for HEAD. */
  fromNullable: (at: number | null | undefined): ScrubPoint =>
    typeof at === 'number' && Number.isFinite(at) && at >= 1
      ? { kind: 'historical', at: at as EventIndex }
      : HEAD,

  toNullable: (point: ScrubPoint): number | null => (point.kind === 'historical' ? point.at : null),

  isHistorical: (point: ScrubPoint): point is { kind: 'historical'; at: EventIndex } =>
    point.kind === 'historical',

  equals: (a: ScrubPoint, b: ScrubPoint): boolean =>
    a.kind === b.kind && (a.kind !== 'historical' || a.at === (b as typeof a).at),
} as const
