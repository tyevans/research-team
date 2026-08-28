import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useEffect, useRef, useState } from 'react'

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
  const field = useRef<HTMLInputElement>(null)

  /** The caret goes in the field the moment the field exists.
   *
   * The form is opened by a button and is one control long, so a reader who
   * pressed "+ New project" has already said what they want to do; without
   * this they press it, the form appears, and they click a second time to
   * type. That second click is the entire cost of making creation a
   * disclosure, and it bought nothing.
   *
   * `autoFocus` is what this would obviously be and the repo's lint forbids it
   * outright (`jsx-a11y/no-autofocus`), on the general grounds that a page
   * which moves focus on load takes it from a reader who was doing something
   * else. That objection does not apply to an element which does not exist
   * until somebody asks for it — the effect runs on *mount*, and this mounts
   * on a click — so the behaviour is kept and the mechanism is an effect,
   * which is also the form the rule's own documentation recommends.
   *
   * On the first-run page there is no disclosure and this component is on
   * screen from the start, so the focus does land on load there. That is the
   * one page where it is unambiguously right: the field is the only control
   * and creating a project is the only thing to do.
   */
  useEffect(() => {
    field.current?.focus()
  }, [])

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
        ref={field}
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
