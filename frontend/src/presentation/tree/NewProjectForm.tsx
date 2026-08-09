import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'

import { notify } from '@application/notifications/toast-store.ts'
import { errorMessage } from '@application/ports/errors.ts'
import { queryKeys } from '@application/queries/keys.ts'
import { useContainer } from '@app/container-context.tsx'

import { Button } from '../common/primitives.tsx'

/** What a project without a workflow gives up, said where the choice is made.
 *
 * `no workflow` is a legal and sometimes right answer, and it is permanent —
 * so the cost belongs beside the option rather than in a 409 three screens
 * later. */
const NO_WORKFLOW_COST = 'No course view for this project. Research and sessions still work.'

/** Creating a project, with its workflow chosen in the same form.
 *
 * The choice sits here because a project may only make it once — the aggregate
 * refuses a second selection, since a run's audit trail is gated by one
 * preset's stage list. Creation is therefore the moment the choice is free, and
 * offering it later would mostly be offering something that will be refused.
 *
 * Two things changed about how that choice is put. The server's `preset_label`
 * — a whole function whose job is to say what a preset produces and where it
 * stops — is rendered *visibly*, under the control, for whatever is currently
 * selected; inside an `<option>` it was invisible until the menu opened and
 * gone the moment it closed. And the default is the first preset rather than
 * `no workflow`, because the old default quietly foreclosed the course view
 * for every project created by someone who did not open the menu.
 * `list_workflows` orders the presets deliberately, so "first" is a decision
 * the server already made.
 */
export const NewProjectForm = ({ onCreated }: { onCreated?: () => void }) => {
  const { projects } = useContainer()
  const queryClient = useQueryClient()
  const [name, setName] = useState('')
  const [chosen, setChosen] = useState<string | null>(null)

  const presets = useQuery({
    queryKey: queryKeys.presets(),
    queryFn: () => projects.presets(),
    // A failure here costs the choice, not the page: creating a project without
    // a workflow stays legal, and the select keeps its one option.
    retry: false,
  })

  /** `null` means "nobody has touched the select", which is not the same as
   *  having picked `no workflow` — the first is a default that should follow
   *  the server's ordering once the presets arrive, the second is a choice. */
  const available = presets.data ?? []
  const presetId = chosen ?? available[0]?.id ?? ''
  const selected = available.find((preset) => preset.id === presetId) ?? null

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
      onCreated?.()
    },
    onError: (error) => notify(`Could not create project: ${errorMessage(error)}`, 'bad'),
    onSettled: () => queryClient.invalidateQueries({ queryKey: queryKeys.projects() }),
  })

  const submit = () => {
    if (!name.trim()) {
      notify('Enter a project name first.', 'bad')
      return
    }
    create.mutate()
  }

  return (
    <div className="new-project">
      <input
        type="text"
        id="project-name"
        className="input"
        placeholder="project name"
        aria-label="Project name"
        value={name}
        onChange={(event) => setName(event.target.value)}
        // Enter submits, because this form is three controls and a person who
        // has typed a name has already made every decision it asks for.
        onKeyDown={(event) => {
          if (event.key === 'Enter') submit()
        }}
      />
      <div className="new-project-workflow">
        <label className="new-project-label" htmlFor="project-workflow">
          Workflow
        </label>
        <select
          id="project-workflow"
          className="input"
          value={presetId}
          onChange={(event) => setChosen(event.target.value)}
        >
          {available.map((preset) => (
            <option key={preset.id} value={preset.id}>
              {preset.name}
            </option>
          ))}
          <option value="">no workflow</option>
        </select>
      </div>
      <p className="new-project-detail">{selected ? selected.label : NO_WORKFLOW_COST}</p>
      <div className="new-project-actions">
        <Button tone="accent" disabled={create.isPending} onClick={submit}>
          Create project
        </Button>
      </div>
    </div>
  )
}
