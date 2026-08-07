import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'

import { notify } from '@application/notifications/toast-store.ts'
import { errorMessage } from '@application/ports/errors.ts'
import { queryKeys } from '@application/queries/keys.ts'
import { useContainer } from '@app/container-context.tsx'
import { isHeld, type Project } from '@domain/project/project.ts'
import { shortId, type ProjectId } from '@domain/shared/identifier.ts'

import { Button, Chip, EmptyState, ErrorBox, Loading } from '../common/primitives.tsx'
import { courseHref, sessionHref } from '../routing/routes.ts'
import { navigate } from '../routing/use-route.ts'

/** Projects: list, create, join, retire. No graph visualisation here — this is
 *  a control surface, and the graph's contents are the agent's business. */
export const ProjectList = () => {
  const { projects } = useContainer()
  const queryClient = useQueryClient()
  const invalidate = () => queryClient.invalidateQueries({ queryKey: queryKeys.projects() })

  const query = useQuery({ queryKey: queryKeys.projects(), queryFn: () => projects.list() })

  const join = useMutation({
    mutationFn: ({ id, takeOver }: { id: ProjectId; takeOver: boolean }) =>
      projects.join(id, takeOver),
    onSuccess: (result) => {
      if (result.warning) notify(`Joined, but ${result.warning}`, 'bad')
      navigate(sessionHref(result.sessionId))
    },
    onError: (error) => notify(`Could not join project: ${errorMessage(error)}`, 'bad'),
    onSettled: invalidate,
  })

  const remove = useMutation({
    mutationFn: ({ project }: { project: Project }) =>
      projects.delete(project.id, isHeld(project)),
    onSuccess: (_result, { project }) => notify(`Deleted project ${project.name}.`, 'good'),
    onError: (error) => notify(`Could not delete project: ${errorMessage(error)}`, 'bad'),
    onSettled: invalidate,
  })

  if (query.isPending) return <Loading what="projects" />
  if (query.isError) {
    return (
      <ErrorBox
        title="Could not load projects"
        message={errorMessage(query.error)}
        onRetry={() => void query.refetch()}
      />
    )
  }
  if (query.data.length === 0) {
    return (
      <EmptyState
        title="No projects yet."
        detail="Create one to share a filesystem and knowledge graph across sessions."
      />
    )
  }

  /** Taking over ends somebody else's session, so it asks first — and says what
   *  it will do, since "end that and start fresh" is not obviously the same
   *  thing as "join". The holder's work is not lost: releasing is exactly what
   *  advances the project's tip, which the new session inherits. */
  const confirmTakeOver = (project: Project): boolean =>
    window.confirm(
      `End session ${shortId(project.activeSessionId)} and start a new one in ${project.name}?\n\n` +
        'Its files carry over to the new session. Its conversation does not.',
    )

  /** "Delete" in most tools means the work goes too, and here it does not — so
   *  the confirmation says what survives. */
  const confirmDelete = (project: Project): boolean => {
    const lines = [`Delete project "${project.name}"?`, '']
    if (project.activeSessionId) {
      lines.push(
        `Session ${shortId(project.activeSessionId)} is still holding it and will be ended first.`,
      )
    }
    lines.push('Its sessions keep their own logs, files and history — they just')
    lines.push("cannot rejoin. The knowledge graph's contents are left in place.")
    return window.confirm(lines.join('\n'))
  }

  return (
    <ul className="tree">
      {query.data.map((project) => (
        <li key={project.id}>
          <div className="node">
            <div className="node-top">
              <span className="node-id">{project.name}</span>
              <span className="node-msg empty">{shortId(project.id)}</span>
              {project.activeSessionId ? (
                <Chip tone="held" title={`held by session ${project.activeSessionId}`}>
                  held by {shortId(project.activeSessionId)}
                </Chip>
              ) : (
                <Chip>free</Chip>
              )}
              <WorkflowChip project={project} />
            </div>
            <div className="node-actions">
              {/* A held project offers two honest choices instead of one that
                  fails: go to whoever holds it, or end that session and take
                  the project on. "Join" was only ever right for a free one. */}
              {project.activeSessionId ? (
                <>
                  <Button
                    small
                    title="Open the session currently holding this project"
                    onClick={() => navigate(sessionHref(project.activeSessionId!))}
                  >
                    Resume
                  </Button>
                  <Button
                    small
                    tone="accent"
                    disabled={join.isPending}
                    title="End the holding session, then start a new one from its work"
                    onClick={() => {
                      if (confirmTakeOver(project)) join.mutate({ id: project.id, takeOver: true })
                    }}
                  >
                    New session
                  </Button>
                </>
              ) : (
                <Button
                  small
                  tone="accent"
                  disabled={join.isPending}
                  onClick={() => join.mutate({ id: project.id, takeOver: false })}
                >
                  Open
                </Button>
              )}
              {/* A run is about the topic queue and not the workflow, so the
                  page is worth opening either way — the label says which of the
                  two things is actually on it. */}
              <Button
                small
                title={
                  project.workflow
                    ? 'Every stage of this workflow, and every artifact it owes'
                    : "Run research over this project's topic queue"
                }
                onClick={() => navigate(courseHref(project.id))}
              >
                {project.workflow ? 'Course' : 'Research'}
              </Button>
              <Button
                small
                tone="danger"
                disabled={remove.isPending}
                title="Retire this project"
                onClick={() => {
                  if (confirmDelete(project)) remove.mutate({ project })
                }}
              >
                Delete
              </Button>
            </div>
          </div>
        </li>
      ))}
    </ul>
  )
}

/** One chip, showing the preset and how far through it this project is.
 *
 * "4 of 15" rather than the stage id alone: the id is precise and says nothing
 * about progress, which is the thing a list is being scanned for. */
const WorkflowChip = ({ project }: { project: Project }) => {
  if (!project.workflow) {
    return (
      <Chip title="No workflow selected. Projects choose one when they are created.">
        no workflow
      </Chip>
    )
  }
  const { stage, workflow } = project
  return (
    <Chip
      title={
        stage
          ? `Stage ${stage.index} of ${stage.of}: ${stage.name} (${stage.id})`
          : // No stage means the preset is not one this build ships, so there is
            // no stage list to place the project in. Say that rather than guess.
            `Workflow ${workflow.id} is not available in this build`
      }
    >
      {stage ? `${workflow.name} · ${stage.index}/${stage.of}` : workflow.name}
    </Chip>
  )
}

/** Creating a project, with its workflow chosen in the same row.
 *
 * The choice sits here because a project may only make it once — the aggregate
 * refuses a second selection, since a run's audit trail is gated by one
 * preset's stage list. Creation is therefore the moment the choice is free, and
 * offering it later would mostly be offering something that will be refused. */
export const NewProjectForm = () => {
  const { projects } = useContainer()
  const queryClient = useQueryClient()
  const [name, setName] = useState('')
  const [presetId, setPresetId] = useState('')

  const presets = useQuery({
    queryKey: queryKeys.presets(),
    queryFn: () => projects.presets(),
    // A failure here costs the choice, not the page: creating a project without
    // a workflow stays legal, and the select keeps its one option.
    retry: false,
  })

  const create = useMutation({
    mutationFn: async () => {
      const id = await projects.create(name.trim())
      if (!presetId) return { name: name.trim(), workflow: null as string | null }
      // Two calls, and the second can fail on its own. The project still exists
      // when it does, which is why this reports the halves separately: a user
      // told creation failed would try again and hit the duplicate-name 409.
      const workflow = await projects.chooseWorkflow(id, presetId)
      return { name: name.trim(), workflow }
    },
    onSuccess: (result) => {
      setName('')
      notify(
        result.workflow
          ? `Created project ${result.name} running ${result.workflow}.`
          : `Created project ${result.name}.`,
        'good',
      )
    },
    onError: (error) => notify(`Could not create project: ${errorMessage(error)}`, 'bad'),
    onSettled: () => queryClient.invalidateQueries({ queryKey: queryKeys.projects() }),
  })

  return (
    <div className="view-head-actions">
      <input
        type="text"
        id="project-name"
        className="input"
        placeholder="project name"
        value={name}
        onChange={(event) => setName(event.target.value)}
      />
      {/* Option text is the server's own label, not the preset name: what a
          preset produces and where it stops is the actual choice, and a bare
          list of methodology names only means something to somebody who has
          read the research. */}
      <select
        id="project-workflow"
        className="input"
        title="Workflow this project runs"
        value={presetId}
        onChange={(event) => setPresetId(event.target.value)}
      >
        <option value="">no workflow</option>
        {(presets.data ?? []).map((preset) => (
          <option key={preset.id} value={preset.id} title={preset.description}>
            {preset.label}
          </option>
        ))}
      </select>
      <Button
        disabled={create.isPending}
        onClick={() => {
          if (!name.trim()) {
            notify('Enter a project name first.', 'bad')
            return
          }
          create.mutate()
        }}
      >
        Create project
      </Button>
    </div>
  )
}
