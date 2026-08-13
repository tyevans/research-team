import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useMemo, useState, type RefObject } from 'react'

import { notify } from '@application/notifications/toast-store.ts'
import { errorMessage } from '@application/ports/errors.ts'
import { queryKeys } from '@application/queries/keys.ts'
import { useContainer } from '@app/container-context.tsx'
import { isHeld, type Project } from '@domain/project/project.ts'
import { currentSession, matches, rollups, type ProjectRollup } from '@domain/project/landing.ts'
import { shortId, type ProjectId } from '@domain/shared/identifier.ts'

import { Confirm } from '../common/Confirm.tsx'
import { Menu, MenuItem, MenuTrigger } from '../common/Menu.tsx'
import { Button, EmptyState, ErrorBox } from '../common/primitives.tsx'
import { Tooltip } from '../common/Tooltip.tsx'
import { ProjectCard, projectSessionsId } from '../entity/project/ProjectCard.tsx'
import { WorkflowChip } from '../entity/project/WorkflowChip.tsx'
// `plural` is gone from this file with `ProjectRow`: the card counts its own
// sessions and files, and its `3 sessions` / `1 session` is character-for-
// character what `plural` produced — `ProjectCard.test.tsx` pins both forms.
import { fullTime, relativeTime } from '../formatting/format.ts'
import { projectHref, sessionHref } from '../routing/routes.ts'
import { navigate } from '../routing/use-route.ts'
import { ActivityChip, useProjectActivity } from './ProjectActivity.tsx'
import { ProjectRows, withHeadings } from './ProjectRows.tsx'
import { SessionForest, SessionRow } from './SessionRow.tsx'
import { useSessionForest } from './SessionTree.tsx'
import { SkeletonRows } from './Skeletons.tsx'

/** Projects, and their sessions inside them.
 *
 * The inversion this page is for. Sessions used to be the document and
 * projects a list underneath it, which had the durable unit below the
 * ephemeral one: sessions are minted by every `/project use`, every take-over
 * and every fork, while projects are what work outlives a conversation in. A
 * returning reader's question is "where was I", and the answer is a project.
 */
export const ProjectList = ({
  scrollRef,
  search,
}: {
  scrollRef: RefObject<HTMLElement | null>
  search: string
}) => {
  const { projects, now } = useContainer()
  const queryClient = useQueryClient()
  const invalidate = () => queryClient.invalidateQueries({ queryKey: queryKeys.projects() })

  const query = useQuery({ queryKey: queryKeys.projects(), queryFn: () => projects.list() })
  const { all: sessions } = useSessionForest()

  /** Which projects have their full session list open. None, to begin with.
   *
   * The most recent project's list used to be expanded on load. It made the
   * page longer than it was useful: sessions accumulate far faster than
   * projects -- every `/project use`, every take-over and every fork mints one
   * -- so one project's history could push every other project off the screen,
   * and what a returning reader wants is the *project*, not an inventory of
   * it. Each row shows its current session instead, which is the one line of
   * that list anybody was actually reading. */
  const [open, setOpen] = useState<ReadonlySet<ProjectId>>(new Set())
  const [pending, setPending] = useState<Confirmation | null>(null)

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
    mutationFn: ({ project }: { project: Project }) => projects.delete(project.id, isHeld(project)),
    onSuccess: (_result, { project }) => notify(`Deleted project ${project.name}.`, 'good'),
    onError: (error) => notify(`Could not delete project: ${errorMessage(error)}`, 'bad'),
    onSettled: invalidate,
  })

  const ranked = useMemo(() => rollups(query.data ?? [], sessions), [query.data, sessions])
  const shown = useMemo(() => ranked.filter((rollup) => matches(rollup, search)), [ranked, search])
  // The clock comes from the container, not from `Date.now()` in render: the
  // headings are derived from it, so a test that wants a row under "This week"
  // has to be able to say when now is.
  const items = useMemo(() => withHeadings(shown, now()), [shown, now])

  if (query.isPending) return <SkeletonRows count={4} />
  if (query.isError) {
    return (
      <ErrorBox
        heading="Could not load projects"
        message={errorMessage(query.error)}
        onRetry={() => void query.refetch()}
      />
    )
  }
  if (ranked.length === 0) {
    // Reached only when sessions exist — a database with neither is the
    // first-run page, which `TreeView` renders instead of this list. So these
    // are sessions written before a session had to belong to a project, and
    // there is nowhere on this page they can appear: saying that is better
    // than an empty box that reads as "nothing has ever run here".
    return (
      <EmptyState
        heading="No projects yet."
        detail="Any sessions in this database predate projects and cannot be reached from here. Create a project to start work that successive sessions share a filesystem and a knowledge graph with."
      />
    )
  }
  if (shown.length === 0) {
    return <EmptyState heading={`Nothing matches “${search.trim()}”.`} />
  }

  const toggle = (id: ProjectId) => {
    const next = new Set(open)
    if (!next.delete(id)) next.add(id)
    setOpen(next)
  }

  return (
    <>
      <ProjectRows
        items={items}
        scrollRef={scrollRef}
        renderProject={(rollup) => (
          <ProjectListRow
            rollup={rollup}
            open={open.has(rollup.project.id)}
            onToggle={() => {
              toggle(rollup.project.id)
            }}
            onTakeOver={() => setPending({ kind: 'takeOver', project: rollup.project })}
            onDelete={() => setPending({ kind: 'delete', project: rollup.project })}
            onOpen={() => join.mutate({ id: rollup.project.id, takeOver: false })}
            busy={join.isPending || remove.isPending}
          />
        )}
      />
      {pending ? (
        <Confirm
          {...confirmCopy(pending)}
          onCancel={() => setPending(null)}
          onConfirm={() => {
            if (pending.kind === 'takeOver') {
              join.mutate({ id: pending.project.id, takeOver: true })
            } else {
              remove.mutate({ project: pending.project })
            }
            setPending(null)
          }}
        />
      ) : null}
    </>
  )
}

interface Confirmation {
  readonly kind: 'takeOver' | 'delete'
  readonly project: Project
}

/** The two sentences this page must not lose.
 *
 * Kept word for word from the `window.confirm` calls they replace. "Take over"
 * and "delete" both do something a reader will assume is worse than it is —
 * one ends a session without losing its files, the other retires a project
 * without touching the work done in it — and these are the sentences that say
 * so. Only the box around them changed.
 */
const confirmCopy = ({ kind, project }: Confirmation) => {
  if (kind === 'takeOver') {
    return {
      heading: `End session ${shortId(project.activeSessionId)} and start a new one in ${project.name}?`,
      lines: ['Its files carry over to the new session. Its conversation does not.'],
      confirmLabel: 'End it and start a new session',
      tone: 'accent' as const,
    }
  }
  const lines = []
  if (project.activeSessionId) {
    lines.push(
      `Session ${shortId(project.activeSessionId)} is still holding it and will be ended first.`,
    )
  }
  lines.push(
    'Its sessions keep their own logs, files and history — they just cannot rejoin. ' +
      "The knowledge graph's contents are left in place.",
  )
  return {
    heading: `Delete project "${project.name}"?`,
    lines,
    confirmLabel: 'Delete project',
    tone: 'danger' as const,
  }
}

/** One drawn row: everything that has to be fetched or decided, and nothing
 *  that is drawn.
 *
 * All four of the console's routes are one click from here. That is the point
 * of the row — the research view previously had no entry point on the landing
 * page at all, because the one button that said "Research" navigated to the
 * course page.
 *
 * **This is a container, not a card.** It renders no markup of its own: the
 * drawing is `ProjectCard`, which is props-only and therefore has a story and
 * a test that need neither a query client nor a container. What is left here
 * is the three things a card may not know — what is running (a fetch), which
 * verb a held project offers (a branch over what taking over *means*), and the
 * menu's open state.
 *
 * **Why the hook is still per row, and what that did and did not buy.** A hook
 * cannot be called in a loop, and `VirtualList`'s children argument is a
 * render callback rather than a component, so "one `useProjectActivity` per
 * drawn row" has to be a component per drawn row — this one. The request count
 * is therefore **unchanged**: still two per drawn row, still only for rows the
 * virtualizer has actually drawn. What changed is where the cost is visible.
 * It is now one call in one container, so §2.7(c)'s `activity` on
 * `/api/projects` becomes a prop swap here rather than a rewrite of the card.
 */
const ProjectListRow = ({
  rollup,
  open,
  onToggle,
  onTakeOver,
  onDelete,
  onOpen,
  busy,
}: {
  rollup: ProjectRollup
  open: boolean
  onToggle: () => void
  onTakeOver: () => void
  onDelete: () => void
  onOpen: () => void
  busy: boolean
}) => {
  const { project, sessions, sessionCount, lastActivity } = rollup
  const current = currentSession(rollup)
  const [menuOpen, setMenuOpen] = useState(false)
  const activity = useProjectActivity(project.id, true)

  return (
    <ProjectCard
      rollup={rollup}
      open={open}
      slots={{
        badges: <WorkflowChip project={project} />,
        activity: <ActivityChip label={activity.label} />,

        /* The disclosure's control, at the head rather than under the row.
           `Disclosure` cannot be used here: it renders its button and its body
           as one element, and the card puts the two in different places -- the
           control beside the name, the contents below everything else. So
           `aria-expanded`, `aria-controls` and the caret are reproduced by
           hand, and the two ARIA attributes are deliberately on the *same*
           element: split across two, the DOM reads correct and a screen reader
           announces a button that expands nothing.

           `projectSessionsId` rather than a string written twice. The id is
           the contract between a slot the view builds and a region the card
           draws, and the failure mode of two spellings is silent -- an IDREF
           that resolves to nothing announces exactly as much as no IDREF at
           all.

           Both labels are kept word for word, because they are what a reader
           and a test both find this control by. */
        toggle:
          sessionCount > 1 ? (
            <Button
              small
              tone="quiet"
              aria-expanded={open}
              aria-controls={projectSessionsId(project.id)}
              onClick={onToggle}
            >
              <span className="disc-caret" aria-hidden="true">
                {open ? '▾' : '▸'}
              </span>
              {open ? `sessions (${sessionCount})` : `all ${sessionCount} sessions`}
            </Button>
          ) : null,

        /* Both of these show an abbreviation of something exact — a relative
           time over a timestamp, eight characters over a full id — so the
           tooltip is not a duplicate of the visible text and cannot simply be
           deleted. Neither span is interactive, so the wrapper trigger costs
           two tab stops per project row and buys the exact value for a reader
           who never had it.

           They are the view's words rather than the card's on purpose:
           `lastActivity` is the newest session *start*, not the last turn, and
           "no sessions yet" against "nothing has run in this project" is this
           page choosing what it can honestly claim. */
        meta: (
          <>
            <Tooltip
              explanation={
                lastActivity ? fullTime(lastActivity) : 'nothing has run in this project'
              }
            >
              {lastActivity ? relativeTime(lastActivity) : 'no sessions yet'}
            </Tooltip>
            <Tooltip explanation={project.id} className="project-id">
              {shortId(project.id)}
            </Tooltip>
          </>
        ),

        /* A held project offers two honest choices instead of one that
           fails: go to whoever holds it, or end that session and take
           the project on. "Join" was only ever right for a free one.

           This branch is the reason `primary` is a slot: deciding it requires
           knowing what taking over *means*, which is a fact about this page's
           mutations rather than about a project. */
        primary: project.activeSessionId ? (
          <>
            <Tooltip asChild explanation="Open the session currently holding this project">
              <Button small onClick={() => navigate(sessionHref(project.activeSessionId!))}>
                Resume {shortId(project.activeSessionId)}
              </Button>
            </Tooltip>
            <Tooltip
              asChild
              explanation="End the holding session, then start a new one from its work"
            >
              <Button small tone="accent" disabled={busy} onClick={onTakeOver}>
                New session
              </Button>
            </Tooltip>
          </>
        ) : (
          <Button small tone="accent" disabled={busy} onClick={onOpen}>
            Open
          </Button>
        ),

        overflow: [
          /* Pushes the two navigation buttons away from the two that start
             something, so the row reads as two groups rather than four
             adjacent choices. */
          <span className="node-actions-gap" key="gap" />,

          /* Disabled with the server's own reason rather than relabelled and
             sent elsewhere. A project chooses its workflow once, at creation,
             and `get_course` 409s with exactly this sentence for one that
             chose none — so a button that said "Research" and went to the
             course page was hiding a permanent fact behind a wrong word.

             `aria-disabled`, not `disabled`, and for the same reason as the
             dispatch button in `TopicQueue`: the sentence this carries when it
             is off is the *permanent* reason it is off, and a `disabled`
             element cannot be focused, so the tooltip holding it would open
             for nobody. The click is guarded instead. */
          <Tooltip
            asChild
            key="course"
            explanation={
              project.workflow
                ? 'Every stage of this workflow, and every artifact it owes'
                : 'this project runs no workflow'
            }
          >
            <Button
              small
              aria-disabled={!project.workflow}
              onClick={() => {
                if (!project.workflow) return
                navigate(projectHref(project.id))
              }}
            >
              Course
            </Button>
          </Tooltip>,
          <Tooltip
            asChild
            key="research"
            explanation="Topics, documents and the knowledge graph for this project"
          >
            <Button
              small
              onClick={() => navigate(projectHref(project.id, { facet: 'entity', id: null }))}
            >
              Research
            </Button>
          </Tooltip>,

          /* Destructive things behind one more click, so the row's default
             reading is "ways in" rather than "ways to lose things".

             **Was a `Disclosure` wearing menu chrome**, which is what
             `tree.css` said it was and what it should not have been: a
             disclosure announces `aria-expanded` over a region, and everything
             else a menu owes -- `role="menu"`, Up and Down between items,
             Escape closing it, focus coming back to the button -- was simply
             absent. A keyboard reader tabbed in, tabbed straight through into
             the rest of the row, and had no route back.

             The `Tooltip` that wrapped Delete is deleted rather than moved.
             "Retire this project" beside an item that says *Delete* is the
             third of the three cases phase 3 sorted `title` attributes into --
             an explanation that repeats the text next to it -- and a tooltip
             inside a menu item is two floating layers arguing over one
             keypress. The item's own label is the explanation.

             `disabled` while busy rather than `aria-disabled`: unlike the
             dispatch button in `TopicQueue`, this carries no sentence that
             exists *because* it is off, so there is nothing a reader needs to
             reach it to hear. Radix skips a disabled item in the arrow-key
             order, which is the behaviour wanted. */
          <Menu
            key="more"
            label={`More actions for ${project.name}`}
            open={menuOpen}
            onOpenChange={setMenuOpen}
            trigger={<MenuTrigger aria-label={`More actions for ${project.name}`} />}
          >
            <MenuItem tone="danger" disabled={busy} onSelect={onDelete}>
              Delete
            </MenuItem>
          </Menu>,
        ],

        /* One session, not a list of them. Which one is the question a landing
           page exists to answer -- "where was I" -- so it is the session
           holding the project when one does, and the newest otherwise.
           Expanding gives the full forest, where fork lineage is the structure
           and worth the space; collapsed, that lineage is a `forked @` chip on
           one row.

           The note takes the same slot because the two are alternatives: a
           project with no sessions has nothing to preview and nothing to
           expand, so it is the only case where this says something instead of
           showing something. A project with one session shows it and needs no
           note. */
        preview: current ? (
          <SessionRow session={current} held={current.id === project.activeSessionId} />
        ) : sessionCount === 0 ? (
          <p className="project-no-sessions">Nothing has run in this project yet.</p>
        ) : null,

        sessions: <SessionForest nodes={sessions} heldBy={project.activeSessionId} />,
      }}
    />
  )
}
