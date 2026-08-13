import type { Project } from '@domain/project/project.ts'

import { Chip } from '../../common/primitives.tsx'
import { Tooltip } from '../../common/Tooltip.tsx'

/** One chip, showing the preset and how far through it this project is.
 *
 * "4 of 15" rather than the stage id alone: the id is precise and says nothing
 * about progress, which is the thing a list is being scanned for.
 *
 * Ported here from `ProjectList.tsx` with `ProjectRow`. It is props-only and
 * always was — it takes a `Project` and reads three fields — so the only thing
 * that kept it in a view file was that only one view drew a project. Now that
 * `ProjectCard` is the drawing, this belongs beside it: it goes into that
 * card's `badges` slot, and a second list of projects would otherwise have
 * reached into `tree/` for it or written a fourth spelling of `no workflow`.
 *
 * It stays a *slot* filler rather than something `ProjectCard` renders itself,
 * for the reason the slot's docstring gives: which facts about a project are
 * worth a chip is an editorial decision belonging to the page, not to the
 * card.
 */
export const WorkflowChip = ({ project }: { project: Project }) => {
  if (!project.workflow) {
    return (
      <Tooltip explanation="No workflow selected. Projects choose one when they are created.">
        <Chip>no workflow</Chip>
      </Tooltip>
    )
  }
  const { stage, workflow } = project
  return (
    <Tooltip
      explanation={
        stage
          ? `Stage ${stage.index} of ${stage.of}: ${stage.name} (${stage.id})`
          : // No stage means the preset is not one this build ships, so there is
            // no stage list to place the project in. Say that rather than guess.
            `Workflow ${workflow.id} is not available in this build`
      }
    >
      <Chip>{stage ? `${workflow.name} · ${stage.index}/${stage.of}` : workflow.name}</Chip>
    </Tooltip>
  )
}
