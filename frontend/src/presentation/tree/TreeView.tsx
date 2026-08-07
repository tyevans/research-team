import { useMutation, useQueryClient } from '@tanstack/react-query'

import { notify } from '@application/notifications/toast-store.ts'
import { errorMessage } from '@application/ports/errors.ts'
import { queryKeys } from '@application/queries/keys.ts'
import { useContainer } from '@app/container-context.tsx'

import { Button } from '../common/primitives.tsx'
import { sessionHref } from '../routing/routes.ts'
import { navigate } from '../routing/use-route.ts'
import { NewProjectForm } from './NewProjectForm.tsx'
import { ProjectList } from './ProjectList.tsx'
import { SessionTree } from './SessionTree.tsx'

export const TreeView = () => {
  const { sessions } = useContainer()
  const queryClient = useQueryClient()

  const create = useMutation({
    mutationFn: () => sessions.create(),
    onSuccess: (id) => navigate(sessionHref(id)),
    onError: (error) => notify(`Could not create session: ${errorMessage(error)}`, 'bad'),
    onSettled: () => queryClient.invalidateQueries({ queryKey: queryKeys.tree() }),
  })

  return (
    <section className="view view-tree">
      <div className="view-head">
        <div>
          <h1>Sessions</h1>
          <p className="sub">Every session is an event log. Forks branch from an event index.</p>
        </div>
        <div className="view-head-actions">
          <Button tone="accent" disabled={create.isPending} onClick={() => create.mutate()}>
            New session
          </Button>
        </div>
      </div>
      <div className="tree-wrap">
        <SessionTree />
      </div>

      <div className="view-head">
        <div>
          <h2>Projects</h2>
          <p className="sub">
            A project is a shared filesystem and knowledge graph. One session holds it at a time.
          </p>
        </div>
        <NewProjectForm />
      </div>
      <div className="tree-wrap">
        <ProjectList />
      </div>
    </section>
  )
}
