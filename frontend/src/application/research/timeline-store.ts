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
    loading: false,
    error: null,

    async load() {
      set({ loading: true, error: null })
      try {
        const timeline = await timelines.timeline(projectId, get().entityType ?? undefined)
        set({ timeline, loading: false })
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
