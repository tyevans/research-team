import type { ProjectId, SessionId } from '../shared/identifier.ts'

/** A shared filesystem and knowledge graph. One session holds it at a time.
 *
 * The holder is part of the model rather than looked up separately, because it
 * decides what the project can *offer*: a held project has two honest choices
 * (open the holder, or end it and take over) where a free one has one. A list
 * that could not see the holder would show a single "join" button and no way to
 * know that pressing it will fail.
 */
export interface ProjectDetail {
  readonly id: ProjectId
  readonly name: string
  readonly activeSessionId: SessionId | null
  readonly tipAtEvent: number
}

/** A listing row, which is now the same shape as the detail.
 *
 * The two came apart because the listing carried a project's workflow and its
 * stage and the detail did not. Both columns are gone with the workflow system,
 * so this is an alias rather than an extension -- kept as a name because `list()`
 * and `project()` answer different questions and a reader tracing either wants
 * the question named at the port. It goes back to being an `interface` the day
 * the listing carries a column the detail does not.
 */
export type Project = ProjectDetail

export const isHeld = (project: Project): boolean => project.activeSessionId !== null
