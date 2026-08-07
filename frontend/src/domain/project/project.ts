import type { ProjectId, SessionId } from '../shared/identifier.ts'

/** A shared filesystem and knowledge graph. One session holds it at a time.
 *
 * The holder is part of the model rather than looked up separately, because it
 * decides what the project can *offer*: a held project has two honest choices
 * (open the holder, or end it and take over) where a free one has one. A list
 * that could not see the holder would show a single "join" button and no way to
 * know that pressing it will fail.
 */
export interface Project {
  readonly id: ProjectId
  readonly name: string
  readonly activeSessionId: SessionId | null
  readonly tipAtEvent: number
  readonly workflow: WorkflowRef | null
  readonly stage: StageRef | null
}

/** The preset a project runs. `name` may equal `id` when this build does not
 *  ship that preset — the id is then the only honest thing to say. */
export interface WorkflowRef {
  readonly id: string
  readonly name: string
  readonly version: string | number | null
}

export interface StageRef {
  readonly id: string
  readonly name: string
  readonly index: number
  readonly of: number
}

export const isHeld = (project: Project): boolean => project.activeSessionId !== null

/** A project whose preset this build does not ship reports a workflow and no
 *  stage: resolving a position needs the stage list, and inventing one would be
 *  worse than admitting the gap. */
export const hasResolvedStage = (project: Project): boolean =>
  project.workflow !== null && project.stage !== null

/** A preset on offer, as a choice rather than as a name.
 *
 * `terminatesAt` is the field that earns this: a preset stopping below spine
 * position 8 has no production half, so it yields a design and not materials —
 * and discovering that at the end of a long run is exactly what surfacing it up
 * front prevents.
 */
export interface WorkflowPreset {
  readonly id: string
  readonly name: string
  readonly version: string | number | null
  readonly description: string
  readonly produces: string
  readonly stageCount: number
  readonly terminatesAt: { readonly id: string; readonly name: string; readonly spine: number }
  readonly hasValueFilter: boolean
  /** The server's own one-line wording. Used verbatim in the picker: a bare
   *  list of methodology names only means something to somebody who has read
   *  the research. */
  readonly label: string
}
