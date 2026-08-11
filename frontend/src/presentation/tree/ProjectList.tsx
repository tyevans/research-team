import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useMemo, useState, type RefObject } from 'react'

import { notify } from '@application/notifications/toast-store.ts'
import { errorMessage } from '@application/ports/errors.ts'
import { queryKeys } from '@application/queries/keys.ts'
import { useContainer } from '@app/container-context.tsx'
import { isHeld, type Project } from '@domain/project/project.ts'
import {
  currentSession,
  matches,
  recencyOf,
  rollups,
  type ProjectRollup,
  type Recency,
} from '@domain/project/landing.ts'
import { shortId, type ProjectId } from '@domain/shared/identifier.ts'

import { Confirm } from '../common/Confirm.tsx'
import { Button, Chip, Disclosure, EmptyState, ErrorBox } from '../common/primitives.tsx'
import { Tooltip } from '../common/Tooltip.tsx'
import { VirtualList } from '../common/VirtualList.tsx'
import { fullTime, plural, relativeTime } from '../formatting/format.ts'
import { courseHref, researchHref, sessionHref } from '../routing/routes.ts'
import { navigate } from '../routing/use-route.ts'
import { ActivityChip, useProjectActivity } from './ProjectActivity.tsx'
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
        openIds={open}
        onToggle={toggle}
        onTakeOver={(project) => setPending({ kind: 'takeOver', project })}
        onDelete={(project) => setPending({ kind: 'delete', project })}
        onOpen={(project) => join.mutate({ id: project.id, takeOver: false })}
        busy={join.isPending || remove.isPending}
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

type Item =
  | { readonly kind: 'heading'; readonly recency: Recency; readonly count: number }
  | { readonly kind: 'project'; readonly rollup: ProjectRollup }

const HEADINGS: Readonly<Record<Recency, string>> = {
  today: 'Today',
  week: 'This week',
  older: 'Older',
  empty: 'Nothing in them yet',
}

/** The ranked list with its recency headings folded into it.
 *
 * One flat array rather than a list of groups because the whole thing is
 * virtualized: a virtualizer counts rows, and a nested structure would have to
 * be flattened for it anyway — at which point it may as well be flattened once,
 * here, where the ordering is decided.
 */
const withHeadings = (shown: readonly ProjectRollup[], now: number): readonly Item[] => {
  const items: Item[] = []
  let current: Recency | null = null
  for (const rollup of shown) {
    const recency = recencyOf(rollup, now)
    if (recency !== current) {
      current = recency
      items.push({
        kind: 'heading',
        recency,
        count: shown.filter((other) => recencyOf(other, now) === recency).length,
      })
    }
    items.push({ kind: 'project', rollup })
  }
  return items
}

const PROJECT_ROW_HEIGHT = 108
const HEADING_HEIGHT = 30

/** What identifies a row to React *and* to the virtualizer's measurement cache.
 *
 * The second is the one that bites. Measurements are cached against whatever
 * key the virtualizer is given, and its default is the array index -- so when
 * the projects query answers and every row shifts down by a heading, index 3
 * keeps the height measured for whatever used to be at index 3. That is not
 * theoretical: it put a project row's 155px against a 33px heading and left a
 * 122px hole in the middle of the list. Keying by identity means a measurement
 * follows its row. */
const itemKey = (item: Item): string =>
  item.kind === 'heading' ? `h-${item.recency}` : String(item.rollup.project.id)

const ProjectRows = ({
  items,
  scrollRef,
  openIds,
  onToggle,
  onTakeOver,
  onDelete,
  onOpen,
  busy,
}: {
  items: readonly Item[]
  scrollRef: RefObject<HTMLElement | null>
  openIds: ReadonlySet<ProjectId>
  onToggle: (id: ProjectId) => void
  onTakeOver: (project: Project) => void
  onDelete: (project: Project) => void
  onOpen: (project: Project) => void
  busy: boolean
}) => {
  return (
    <VirtualList
      items={items}
      scrollRef={scrollRef}
      className="rows"
      getKey={(row) => itemKey(row)}
      estimate={(index) => (items[index]?.kind === 'heading' ? HEADING_HEIGHT : PROJECT_ROW_HEIGHT)}
      overscan={4}
    >
      {(row, position) => (
        <li
          ref={position.measure}
          data-index={position.index}
          className="rows-item"
          style={{
            position: 'absolute',
            top: 0,
            left: 0,
            right: 0,
            // `top` is already corrected for where this list sits inside the
            // scroll container; `VirtualList` takes its own offset back off.
            transform: `translateY(${position.top}px)`,
          }}
        >
          {row.kind === 'heading' ? (
            <h3 className="rows-heading">
              {HEADINGS[row.recency]}
              <span className="rows-heading-count">{row.count}</span>
            </h3>
          ) : (
            <ProjectRow
              rollup={row.rollup}
              open={openIds.has(row.rollup.project.id)}
              onToggle={() => onToggle(row.rollup.project.id)}
              onTakeOver={() => onTakeOver(row.rollup.project)}
              onDelete={() => onDelete(row.rollup.project)}
              onOpen={() => onOpen(row.rollup.project)}
              busy={busy}
            />
          )}
        </li>
      )}
    </VirtualList>
  )
}

/** One project: what state it is in, and every way into it.
 *
 * All four of the console's routes are one click from here. That is the point
 * of the row — the research view previously had no entry point on the landing
 * page at all, because the one button that said "Research" navigated to the
 * course page.
 */
const ProjectRow = ({
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
  const { project, sessions, sessionCount, fileCount, lastActivity } = rollup
  const current = currentSession(rollup)
  const [menuOpen, setMenuOpen] = useState(false)
  const activity = useProjectActivity(project.id, true)

  return (
    <div className="project">
      <div className="project-head">
        <span className="project-name">{project.name}</span>
        <WorkflowChip project={project} />
        {project.activeSessionId ? (
          <Tooltip explanation={`held by session ${project.activeSessionId}`}>
            <Chip tone="held">held by {shortId(project.activeSessionId)}</Chip>
          </Tooltip>
        ) : (
          <Chip tone="ok">free</Chip>
        )}
        <ActivityChip label={activity.label} />
      </div>

      <div className="project-stats">
        <span>{plural(sessionCount, 'session')}</span>
        <span>{plural(fileCount, 'file')}</span>
        {/* Both of these show an abbreviation of something exact — a relative
            time over a timestamp, eight characters over a full id — so the
            tooltip is not a duplicate of the visible text and cannot simply be
            deleted. Neither span is interactive, so the wrapper trigger costs
            two tab stops per project row and buys the exact value for a reader
            who never had it. */}
        <Tooltip
          explanation={lastActivity ? fullTime(lastActivity) : 'nothing has run in this project'}
        >
          {lastActivity ? relativeTime(lastActivity) : 'no sessions yet'}
        </Tooltip>
        <Tooltip explanation={project.id} className="project-id">
          {shortId(project.id)}
        </Tooltip>
      </div>

      <div className="node-actions">
        {/* A held project offers two honest choices instead of one that
            fails: go to whoever holds it, or end that session and take
            the project on. "Join" was only ever right for a free one. */}
        {project.activeSessionId ? (
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
        )}

        <span className="node-actions-gap" />

        {/* Disabled with the server's own reason rather than relabelled and
            sent elsewhere. A project chooses its workflow once, at creation,
            and `get_course` 409s with exactly this sentence for one that chose
            none — so a button that said "Research" and went to the course page
            was hiding a permanent fact behind a wrong word. */}
        {/* `aria-disabled`, not `disabled`, and for the same reason as the
            dispatch button in `TopicQueue`: the sentence this carries when it
            is off is the *permanent* reason it is off, and a `disabled`
            element cannot be focused, so the tooltip holding it would open for
            nobody. The click is guarded below instead. */}
        <Tooltip
          asChild
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
              navigate(courseHref(project.id))
            }}
          >
            Course
          </Button>
        </Tooltip>
        <Tooltip asChild explanation="Topics, documents and the knowledge graph for this project">
          <Button small onClick={() => navigate(researchHref(project.id))}>
            Research
          </Button>
        </Tooltip>

        {/* Destructive things behind one more click, so the row's default
            reading is "ways in" rather than "ways to lose things". */}
        <Disclosure
          className="menu"
          label={<span aria-label={`More actions for ${project.name}`}>⋯</span>}
          open={menuOpen}
          onToggle={() => setMenuOpen(!menuOpen)}
        >
          <Tooltip asChild explanation="Retire this project">
            <Button small tone="danger" disabled={busy} onClick={onDelete}>
              Delete
            </Button>
          </Tooltip>
        </Disclosure>
      </div>

      {/* One session, not a list of them. Which one is the question a landing
          page exists to answer -- "where was I" -- so it is the session holding
          the project when one does, and the newest otherwise. Expanding gives
          the full forest, where fork lineage is the structure and worth the
          space; collapsed, that lineage is a `forked @` chip on one row.

          The preview gives way to the forest rather than sitting above it: the
          current session is *in* that forest, and showing it twice reads as a
          duplicated row rather than as a summary of the list below it. */}
      {current && !open ? (
        <SessionRow session={current} held={current.id === project.activeSessionId} />
      ) : null}

      {sessionCount > 1 ? (
        <Disclosure
          className="project-sessions"
          label={open ? `sessions (${sessionCount})` : `all ${sessionCount} sessions`}
          open={open}
          onToggle={onToggle}
        >
          <SessionForest nodes={sessions} heldBy={project.activeSessionId} />
        </Disclosure>
      ) : null}

      {/* Only when there is nothing at all. A project with one session shows it
          above and needs no note, and a fold offering no more than the row
          already displays is a click that changes nothing. */}
      {sessionCount === 0 ? (
        <p className="project-no-sessions">Nothing has run in this project yet.</p>
      ) : null}
    </div>
  )
}

/** One chip, showing the preset and how far through it this project is.
 *
 * "4 of 15" rather than the stage id alone: the id is precise and says nothing
 * about progress, which is the thing a list is being scanned for. */
const WorkflowChip = ({ project }: { project: Project }) => {
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
