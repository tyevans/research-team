import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'

import { notify } from '@application/notifications/toast-store.ts'
import { errorMessage } from '@application/ports/errors.ts'
import { queryKeys } from '@application/queries/keys.ts'
import { useContainer } from '@app/container-context.tsx'

import { Button } from '../common/primitives.tsx'

/** Creating a project: a name, and nothing else to decide.
 *
 * **There was a workflow `<select>` here, and a paragraph under it.** The
 * paragraph rendered the server's `preset_label` for whatever was chosen, or
 * `NO_WORKFLOW_COST` -- a sentence naming what a project without a preset gave
 * up -- and it earned its place while the choice was permanent and made here.
 * With the workflow system gone there is nothing to give up and nothing to
 * choose, so the paragraph is deleted rather than replaced with a "next steps"
 * blurb: a form that explains itself where there is no decision to make is
 * chrome, and the next action belongs on the project page the reader reaches a
 * second later.
 *
 * **Creation is one server call now, and the failure mode that split went with
 * it.** It used to be `projects.create` and then `projects.chooseWorkflow`, the
 * second able to fail on its own with the project already created -- which is
 * why the old mutation reported the two halves separately, so somebody told
 * "creation failed" did not retry into a duplicate-name 409. One call has one
 * outcome and needs no such care.
 */
export const NewProjectForm = ({ onCreated }: { onCreated?: () => void }) => {
  const { projects } = useContainer()
  const queryClient = useQueryClient()
  const [name, setName] = useState('')

  const create = useMutation({
    mutationFn: async () => {
      await projects.create(name.trim())
      return name.trim()
    },
    onSuccess: (created) => {
      setName('')
      notify(`Created project ${created}.`, 'good')
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
        // Enter submits, because this form is one control and a person who has
        // typed a name has already made every decision it asks for.
        onKeyDown={(event) => {
          if (event.key === 'Enter') submit()
        }}
      />
      <div className="new-project-actions">
        <Button tone="accent" disabled={create.isPending} onClick={submit}>
          Create project
        </Button>
      </div>
    </div>
  )
}
