import { create } from 'zustand'

import { errorMessage } from '@application/ports/errors.ts'
import { emptyTimeline, type Timeline } from '@domain/knowledge/timeline.ts'
import type { ProjectId } from '@domain/shared/identifier.ts'

import type { TimelineRepository } from '../ports/repositories.ts'

/** One project's timeline: the bands, and which type of entity is on show.
 *
 * Project-keyed for the same reason `graph-store` is: the graph is
 * tenant-scoped by project, and a store shared across projects would draw one
 * project's events on another's page the moment two tabs were open.
 */
export interface TimelineState {
  readonly timeline: Timeline
  /** The entity type filter, or `null` for every type.
   *
   * Held here rather than in the pane because changing it refetches -- the
   * filter is pushed to the server, not applied to bands already in hand, so
   * it is part of what the store last asked for rather than a view setting.
   */
  readonly entityType: string | null
  /** Every entity type an unfiltered load has seen, sorted.
   *
   * Kept here rather than derived from `timeline.bands`, and the reason is a
   * defect this shipped with: the filter is pushed to the *server*, so
   * choosing `event` makes the response all events, and a list derived from
   * the bands in hand would then offer `All` and `event` alone -- the reader
   * would have to go back to `All` to reach `person`. `graph-store`'s
   * `knownTypes` exists for exactly this and is the shape copied.
   *
   * Populated only from an unfiltered load, not accumulated across filtered
   * ones: an unfiltered response is by definition the whole roster, so
   * accumulating would add nothing and would let a type that has since been
   * merged away linger on offer.
   */
  readonly knownTypes: readonly string[]
  readonly loading: boolean
  readonly error: string | null

  load(): Promise<void>
  setEntityType(entityType: string | null): Promise<void>
}

export const createTimelineStore = ({
  timelines,
  projectId,
}: {
  timelines: TimelineRepository
  projectId: ProjectId
}) =>
  create<TimelineState>((set, get) => ({
    timeline: emptyTimeline,
    entityType: null,
    knownTypes: [],
    loading: false,
    error: null,

    async load() {
      const entityType = get().entityType
      set({ loading: true, error: null })
      try {
        // Spread rather than `{ entityType: entityType ?? undefined }`:
        // `exactOptionalPropertyTypes` treats an explicit `undefined` as a
        // different thing from an absent key, and the port's window means
        // "absent" by absence.
        const timeline = await timelines.timeline(projectId, {
          ...(entityType === null ? {} : { entityType }),
        })
        set({
          timeline,
          loading: false,
          // Read off the response only when nothing was filtered; a filtered
          // response is a subset and would narrow the roster to itself.
          ...(entityType === null
            ? {
                knownTypes: [...new Set(timeline.bands.map((band) => band.entityType))].sort(),
              }
            : {}),
        })
      } catch (error) {
        // The timeline is replaced with an empty one rather than left stale:
        // a failed refresh showing the previous bands beside an error message
        // invites the reader to trust bands that may be arbitrarily old.
        set({ timeline: emptyTimeline, loading: false, error: errorMessage(error) })
      }
    },

    async setEntityType(entityType: string | null) {
      set({ entityType })
      await get().load()
    },
  }))
