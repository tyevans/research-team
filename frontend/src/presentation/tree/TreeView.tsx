import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useRef, useState } from 'react'

import { notify } from '@application/notifications/toast-store.ts'
import { errorMessage } from '@application/ports/errors.ts'
import { queryKeys } from '@application/queries/keys.ts'
import { useContainer } from '@app/container-context.tsx'

import { Button } from '../common/primitives.tsx'
import { sessionHref } from '../routing/routes.ts'
import { navigate } from '../routing/use-route.ts'
import { DriftBanner } from './DriftBanner.tsx'
import { NewProjectForm } from './NewProjectForm.tsx'
import { ProjectList } from './ProjectList.tsx'
import { LooseSessions, useSessionForest } from './SessionTree.tsx'

/** The console's landing page: projects, with their sessions inside them.
 *
 * One sentence of purpose, one primary action, then the projects. The page
 * this replaces led with `<h1>Sessions</h1>` at the largest type size in the
 * console and put projects under an `<h2>` below it — the durable unit beneath
 * the ephemeral one, which is backwards: sessions are minted by every
 * `/project use`, every take-over and every fork, while a project is the only
 * thing work outlives a conversation in.
 */
export const TreeView = () => {
  const { sessions, projects } = useContainer()
  const queryClient = useQueryClient()
  const scrollRef = useRef<HTMLElement>(null)
  const searchRef = useRef<HTMLInputElement>(null)
  const [search, setSearch] = useState('')
  const [creating, setCreating] = useState(false)

  const projectsQuery = useQuery({
    queryKey: queryKeys.projects(),
    queryFn: () => projects.list(),
  })
  const { all: sessionRows, isPending: sessionsPending } = useSessionForest()

  // `/` focuses search, the way it does in every other list-shaped tool. Only
  // when the reader is not already typing somewhere: a `/` in the search box,
  // or in the project-name field, is a character and not a shortcut.
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== '/' || event.metaKey || event.ctrlKey || event.altKey) return
      const active = document.activeElement
      if (active instanceof HTMLInputElement || active instanceof HTMLTextAreaElement) return
      event.preventDefault()
      searchRef.current?.focus()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  const create = useMutation({
    mutationFn: () => sessions.create(),
    onSuccess: (id) => navigate(sessionHref(id)),
    onError: (error) => notify(`Could not create session: ${errorMessage(error)}`, 'bad'),
    onSettled: () => queryClient.invalidateQueries({ queryKey: queryKeys.tree() }),
  })

  /** Nothing exists at all — so the whole page becomes the answer, rather than
   *  two empty boxes under two headings saying different things. Both reads
   *  have to have answered: an empty page shown while the queries are still in
   *  flight would tell a returning user their work is gone. */
  const firstRun =
    !projectsQuery.isPending &&
    !projectsQuery.isError &&
    projectsQuery.data.length === 0 &&
    !sessionsPending &&
    sessionRows.length === 0

  if (firstRun) return <FirstRun onNewSession={() => create.mutate()} busy={create.isPending} />

  return (
    <section className="view view-home" ref={scrollRef}>
      {/* The scroll container is the section, so the virtualizers measure
          against the whole page; the width lives on the wrapper inside it. */}
      <div className="home-inner">
        {/* Not dismissible. It costs one line, and it is the only thing on the
          page telling somebody who did not build this what they are looking
          at. The sentence it replaces — "Forks branch from an event index" —
          is true and parses only if you have already read the README. */}
        <p className="purpose">
          An agent whose whole session is one event log. A project is where that work outlives one
          conversation — a filesystem and a knowledge graph its sessions share.
        </p>

        <div className="actions">
          <Button tone="accent" onClick={() => setCreating(!creating)} aria-expanded={creating}>
            + New project
          </Button>
          <input
            ref={searchRef}
            type="search"
            className="input actions-search"
            placeholder="search projects and sessions  ( / )"
            aria-label="Search projects and sessions"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
          />
          {/* Quiet, and deliberately so. A bare session has no filesystem
            lineage, no knowledge graph, no course and no topic queue, and
            cannot be given any of them later — so it is the right tool for
            trying a prompt and a dead end for everything else. */}
          <Button tone="quiet" disabled={create.isPending} onClick={() => create.mutate()}>
            New session
          </Button>
        </div>

        {creating ? <NewProjectForm onCreated={() => setCreating(false)} /> : null}

        <h2 className="section">Projects</h2>
        <ProjectList scrollRef={scrollRef} search={search} />

        <h2 className="section">Sessions outside any project</h2>
        {/* In the page, not only as a badge in the topbar. This is the one page
            whose entire content is that list, so "the list may be lying"
            belongs where the list is. */}
        <DriftBanner />
        <LooseSessions scrollRef={scrollRef} />
      </div>
    </section>
  )
}

/** The empty database, as a page rather than as two empty boxes.
 *
 * What somebody who has just cloned this and typed `uv run web.py` needs, in
 * order: that it is alive and connected (the topbar's badge, already correct),
 * a sentence saying what this is, and one action. Creating a project is that
 * action rather than creating a session, because a session created here can
 * never be given a project, a course or a topic queue — the aggregate refuses
 * a second choice — so it is a dead end for every feature this console has.
 */
const FirstRun = ({ onNewSession, busy }: { onNewSession: () => void; busy: boolean }) => (
  <section className="view view-home view-first-run">
    <div className="first-run">
      <p className="purpose">
        An agent whose whole session is one event log: every message, tool call and file write, in
        order. Scrub it back, fork it, and pick it up later.
      </p>
      <p className="purpose">
        A project is where work outlives one conversation — a filesystem and a knowledge graph its
        sessions share.
      </p>

      <NewProjectForm />

      {/* Kept from the empty state this replaces, which had the right instinct
          in the wrong place: the CLI genuinely is faster for a first prompt,
          and both front ends share one database. It belongs on the page for
          somebody who has nothing yet, not buried under a list. */}
      <p className="first-run-aside">
        Only trying a prompt?{' '}
        <button type="button" className="linkish" disabled={busy} onClick={onNewSession}>
          Start a bare session
        </button>{' '}
        · or run <code>uv run main.py</code> in a terminal — both front ends share one database.
      </p>
    </div>
  </section>
)
