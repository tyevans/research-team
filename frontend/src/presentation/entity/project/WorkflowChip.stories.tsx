import type { Meta, StoryObj } from '@storybook/react-vite'

import type { Project } from '@domain/project/project.ts'
import { ProjectId } from '@domain/shared/identifier.ts'

import { WorkflowChip } from './WorkflowChip.tsx'

/** The badge the landing page puts in `ProjectCard`'s `badges` slot.
 *
 * Three states rather than two, and the third is the reason this has a story
 * at all: a project can name a workflow this build does not ship, which is not
 * "no workflow" and must not read as one.
 */
const meta: Meta = {
  title: 'entity/WorkflowChip',
}

export default meta

type Story = StoryObj

const project = (over: Partial<Project> = {}): Project => ({
  id: ProjectId('3f2a1b9c-1111-2222-3333-444444444444'),
  name: 'apollo',
  activeSessionId: null,
  tipAtEvent: 128,
  workflow: null,
  stage: null,
  ...over,
})

/** Chose a preset, and is four stages into it. "4/15" rather than the stage id
 *  alone: the id is precise and says nothing about progress, which is what a
 *  list is being scanned for. */
export const InProgress: Story = {
  render: () => (
    <WorkflowChip
      project={project({
        workflow: { id: 'hybrid', name: 'hybrid', version: 1 },
        stage: { id: 's4', name: 'design', index: 4, of: 15 },
      })}
    />
  ),
}

/** Chose none, permanently — a project picks its workflow once, at creation. */
export const None: Story = {
  render: () => <WorkflowChip project={project()} />,
}

/** Named a preset this build does not have, so there is no stage list to place
 *  it in. The chip says the workflow's name and the explanation says why there
 *  is no progress beside it, rather than guessing at one. */
export const UnknownPreset: Story = {
  render: () => (
    <WorkflowChip project={project({ workflow: { id: 'legacy', name: 'legacy', version: 1 } })} />
  ),
}
