import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useVirtualizer } from '@tanstack/react-virtual'
import { useLayoutEffect, useMemo, useRef, useState, type RefObject } from 'react'

import { notify } from '@application/notifications/toast-store.ts'
import { errorMessage } from '@application/ports/errors.ts'
import { queryKeys } from '@application/queries/keys.ts'
import { useContainer } from '@app/container-context.tsx'
import { isHeld, type Project } from '@domain/project/project.ts'
import {
  matches,
  recencyOf,
  rollups,
  type ProjectRollup,
  type Recency,
} from '@domain/project/landing.ts'
import { shortId, type ProjectId } from '@domain/shared/identifier.ts'

import { Confirm } from '../common/Confirm.tsx'
import { Button, Chip, Disclosure, EmptyState, ErrorBox } from '../common/primitives.tsx'
import { fullTime, plural, relativeTime } from '../formatting/format.ts'
import { courseHref, researchHref, sessionHref } from '../routing/routes.ts'
import { navigate } from '../routing/use-route.ts'
import { ActivityChip, useProjectActivity } from './ProjectActivity.tsx'
import { SessionForest } from './SessionRow.tsx'
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

  /** Which project's sessions are open, or `null` for "the most recent one".
   *
   * `null` rather than a set seeded from the data: seeding needs the ranked
   * list, which is not known until both queries have answered, and a fold that
   * ran on the first render would open whichever project happened to be first
   * before the sessions arrived. Deferring it to the render that draws the row
   * keeps "the most recent project is open on load" true without a effect that
   * fights the reader the moment they collapse it. */
  const [open, setOpen] = useState<ReadonlySet<ProjectId> | null>(null)
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
        title="Could not load projects"
        message={errorMessage(query.error)}
        onRetry={() => void query.refetch()}
      />
    )
  }
  if (ranked.length === 0) {
    // Reached only when sessions exist — a database with neither is the
    // first-run page, which `TreeView` renders instead of this list. Somebody
    // has been working in the CLI without `/project new`, and the useful thing
    // to say is what they are missing rather than "No projects yet."
    return (
      <EmptyState
        title="No projects yet — these sessions belong to none."
        detail="A project gives successive sessions one filesystem and one knowledge graph, and is the only thing that can carry a course or a research queue. Sessions keep working without one."
      />
    )
  }
  if (shown.length === 0) {
    return <EmptyState title={`Nothing matches “${search.trim()}”.`} />
  }

  const openIds = open ?? new Set(firstProjectId(shown))
  const toggle = (id: ProjectId) => {
    const next = new Set(openIds)
    if (!next.delete(id)) next.add(id)
    setOpen(next)
  }

  return (
    <>
      <ProjectRows
        items={items}
        scrollRef={scrollRef}
        openIds={openIds}
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

const firstProjectId = (shown: readonly ProjectRollup[]): readonly ProjectId[] => {
  const first = shown[0]
  return first ? [first.project.id] : []
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
      title: `End session ${shortId(project.activeSessionId)} and start a new one in ${project.name}?`,
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
    title: `Delete project "${project.name}"?`,
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
  const listRef = useRef<HTMLUListElement>(null)
  const [listTop, setListTop] = useState(0)

  // Deliberately without a dependency list: what moves this list down the page
  // is everything above it -- the purpose line wrapping, the action bar, the
  // new-project form opening -- and there is no value to depend on that
  // captures "the layout above changed". Re-reading after every render is the
  // honest way to track it, and the update is a no-op when the number has not
  // changed, so React bails out rather than looping.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useLayoutEffect(() => {
    const element = listRef.current
    if (element)
      setListTop((current) => (current === element.offsetTop ? current : element.offsetTop))
  })

  // React Compiler cannot memoize `useVirtualizer`'s returned functions, so it
  // skips this component rather than risk a stale virtualizer — the same trade
  // `DocumentList` documents, and the same reason.
  // eslint-disable-next-line react-hooks/incompatible-library
  const virtualizer = useVirtualizer({
    count: items.length,
    getScrollElement: () => scrollRef.current,
    getItemKey: (index) => itemKey(items[index]!),
    // How far down the scroll container this list starts. The virtualizer
    // works in the scroll element's coordinates, and this list is not at the
    // top of it -- there is a purpose line, an action bar and a heading above.
    // Without this the window of drawn rows is offset by exactly that much,
    // which is invisible at three projects and draws the wrong rows at fifty.
    scrollMargin: listTop,
    // Rows are a fixed height until one is expanded, which is the single
    // variable-height thing on the page — so every row is measured rather than
    // trusted to the estimate, and the estimate only decides how far the
    // scrollbar thinks it has to go before a row has been drawn.
    estimateSize: (index) =>
      items[index]?.kind === 'heading' ? HEADING_HEIGHT : PROJECT_ROW_HEIGHT,
    measureElement: (element) => element.getBoundingClientRect().height || PROJECT_ROW_HEIGHT,
    overscan: 4,
  })

  return (
    <ul
      ref={listRef}
      className="rows"
      style={{ height: virtualizer.getTotalSize(), position: 'relative' }}
    >
      {virtualizer.getVirtualItems().map((item) => {
        const row = items[item.index]
        if (!row) return null
        return (
          <li
            key={itemKey(row)}
            ref={virtualizer.measureElement}
            data-index={item.index}
            className="rows-item"
            style={{
              position: 'absolute',
              top: 0,
              left: 0,
              right: 0,
              // `start` is in the scroll container's coordinates, so the
              // list's own offset comes back off it -- otherwise every row is
              // pushed down the page by the height of everything above.
              transform: `translateY(${item.start - virtualizer.options.scrollMargin}px)`,
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
        )
      })}
    </ul>
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
  const [menuOpen, setMenuOpen] = useState(false)
  const activity = useProjectActivity(project.id, true)

  return (
    <div className="project">
      <div className="project-head">
        <span className="project-name">{project.name}</span>
        <WorkflowChip project={project} />
        {project.activeSessionId ? (
          <Chip tone="held" title={`held by session ${project.activeSessionId}`}>
            held by {shortId(project.activeSessionId)}
          </Chip>
        ) : (
          <Chip tone="ok">free</Chip>
        )}
        <ActivityChip label={activity.label} />
      </div>

      <div className="project-stats">
        <span>{plural(sessionCount, 'session')}</span>
        <span>{plural(fileCount, 'file')}</span>
        <span title={lastActivity ? fullTime(lastActivity) : 'nothing has run in this project'}>
          {lastActivity ? relativeTime(lastActivity) : 'no sessions yet'}
        </span>
        <span className="project-id" title={project.id}>
          {shortId(project.id)}
        </span>
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
              Resume {shortId(project.activeSessionId)}
            </Button>
            <Button
              small
              tone="accent"
              disabled={busy}
              title="End the holding session, then start a new one from its work"
              onClick={onTakeOver}
            >
              New session
            </Button>
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
        <Button
          small
          disabled={!project.workflow}
          title={
            project.workflow
              ? 'Every stage of this workflow, and every artifact it owes'
              : 'this project runs no workflow'
          }
          onClick={() => navigate(courseHref(project.id))}
        >
          Course
        </Button>
        <Button
          small
          title="Topics, documents and the knowledge graph for this project"
          onClick={() => navigate(researchHref(project.id))}
        >
          Research
        </Button>

        {/* Destructive things behind one more click, so the row's default
            reading is "ways in" rather than "ways to lose things". */}
        <Disclosure
          className="menu"
          label={<span aria-label={`More actions for ${project.name}`}>⋯</span>}
          open={menuOpen}
          onToggle={() => setMenuOpen(!menuOpen)}
        >
          <Button
            small
            tone="danger"
            disabled={busy}
            title="Retire this project"
            onClick={onDelete}
          >
            Delete
          </Button>
        </Disclosure>
      </div>

      <Disclosure
        className="project-sessions"
        label={`sessions (${sessionCount})`}
        open={open}
        onToggle={onToggle}
      >
        {sessions.length > 0 ? (
          <SessionForest nodes={sessions} heldBy={project.activeSessionId} />
        ) : (
          <EmptyState title="Nothing has run in this project yet." />
        )}
      </Disclosure>
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
