import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'

import { notify } from '@application/notifications/toast-store.ts'
import { errorMessage } from '@application/ports/errors.ts'
import { queryKeys } from '@application/queries/keys.ts'
import { useContainer } from '@app/container-context.tsx'

import { Button } from '../common/primitives.tsx'

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
