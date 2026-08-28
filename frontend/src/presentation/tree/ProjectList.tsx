import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useMemo, useState, type RefObject } from 'react'

import { notify } from '@application/notifications/toast-store.ts'
import { errorMessage } from '@application/ports/errors.ts'
import { queryKeys } from '@application/queries/keys.ts'
import { useContainer } from '@app/container-context.tsx'
import { isHeld, type Project } from '@domain/project/project.ts'
import { currentSession, matches, rollups, type ProjectRollup } from '@domain/project/landing.ts'
import type { ProjectId } from '@domain/shared/identifier.ts'

import { Confirm } from '../common/Confirm.tsx'
import { Menu, MenuItem, MenuTrigger } from '../common/Menu.tsx'
import { Button, EmptyState, ErrorBox } from '../common/primitives.tsx'
import { Tooltip } from '../common/Tooltip.tsx'
import { ProjectCard } from '../entity/project/ProjectCard.tsx'
import { relativeTime } from '../formatting/format.ts'
import { projectHref, sessionHref } from '../routing/routes.ts'
import { navigate } from '../routing/use-route.ts'
import { ActivityChip, useProjectActivity } from './ProjectActivity.tsx'
import { ProjectRows, withHeadings, withoutHeadings } from './ProjectRows.tsx'
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
  const [pending, setPending] = useState<Project | null>(null)

  /** The one write this page still makes, and the only one it should.
   *
   * **`takeOver` is gone from every call site here**, which is the landing
   * page's half of "the holding session stops being something a person
   * manages". Take-over ends somebody's session; it is the single most
   * holder-shaped verb in the console, and offering it on an *index* asked a
   * reader to resolve a lock before they had read anything. What is left is
   * holder-blind: `Continue` opens the session in progress when there is one,
   * and starts one when there is not, and the reader is never told which
   * happened because the answer is the same either way — they are looking at
   * the project's live conversation.
   *
   * This is deliberately still a mutation on a list page, and the alternative
   * was considered: remove `join` too, and let the project page own every verb
   * that writes. That is the tidier end state and it is not reachable from
   * here — the project view has no join affordance today, so removing this one
   * would leave the console with no way to start a session at all. Recorded in
   * the PR rather than shipped as a dead end.
   */
  const carryOn = useMutation({
    mutationFn: ({ id }: { id: ProjectId }) => projects.join(id, false),
    onSuccess: (result) => {
      if (result.warning) notify(`Joined, but ${result.warning}`, 'bad')
      navigate(sessionHref(result.sessionId))
    },
    onError: (error) => notify(`Could not open project: ${errorMessage(error)}`, 'bad'),
    onSettled: invalidate,
  })

  /** `isHeld(project)` is the surviving load-bearing read of the holder.
   *
   * It is the `force` flag: deleting a held project has to end its session
   * first, and a `false` here would fail against exactly the projects a person
   * is most likely to delete. Nothing on the page draws the holder any more,
   * so this is the argument that would rot silently — hence
   * `TreeView.test.tsx`'s assertion on the second argument, which is new and
   * which nothing checked while the holder was on screen. */
  const remove = useMutation({
    mutationFn: ({ project }: { project: Project }) => projects.delete(project.id, isHeld(project)),
    onSuccess: (_result, { project }) => notify(`Deleted project ${project.name}.`, 'good'),
    onError: (error) => notify(`Could not delete project: ${errorMessage(error)}`, 'bad'),
    onSettled: invalidate,
  })

  const ranked = useMemo(() => rollups(query.data ?? [], sessions), [query.data, sessions])
  const shown = useMemo(() => ranked.filter((rollup) => matches(rollup, search)), [ranked, search])
  const filtering = search.trim().length > 0
  // The clock comes from the container, not from `Date.now()` in render: the
  // headings are derived from it, so a test that wants a row under "This week"
  // has to be able to say when now is.
  //
  // **No headings while a search is running.** "Today" over a set of results
  // that share nothing but a substring labels nothing, and it costs a row of
  // vertical space per band in the region where a reader is scanning hardest.
  // There is a second reason and it is the load-bearing one: `itemKey`'s
  // uniqueness rests on each recency band opening exactly once, which holds
  // only because the input is sorted by band — so anything that reorders
  // results (a relevance rank, which is the obvious next step for this search)
  // silently produces duplicate keys and one measurement cell holding two
  // rows' heights. Dropping headings from filtered results removes the
  // precondition rather than relying on it.
  const items = useMemo(
    () => (filtering ? withoutHeadings(shown) : withHeadings(shown, now())),
    [shown, now, filtering],
  )

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
            onDelete={() => setPending(rollup.project)}
            onContinue={() => {
              const holder = rollup.project.activeSessionId
              if (holder) navigate(sessionHref(holder))
              else carryOn.mutate({ id: rollup.project.id })
            }}
            busy={carryOn.isPending || remove.isPending}
          />
        )}
      />
      {pending ? (
        <Confirm
          {...deleteCopy(pending)}
          onCancel={() => setPending(null)}
          onConfirm={() => {
            remove.mutate({ project: pending })
            setPending(null)
          }}
        />
      ) : null}
    </>
  )
}

/** The sentence this page must not lose.
 *
 * Kept word for word from the `window.confirm` it replaced. "Delete" does
 * something a reader will assume is worse than it is — it retires a project
 * without touching the work done in it — and this is the sentence that says
 * so.
 *
 * **The warning survives; the short id in it does not.** It read "Session
 * 3f2a1b9c is still holding it and will be ended first", which is the last
 * place on this page a holder was named. A reader about to destroy something
 * is entitled to know that a session in progress will end with it — that is
 * the warning, and it is kept. *Which* session is the part they cannot act on:
 * they are not being offered a choice between ending that one and ending
 * another, and eight characters of a uuid do not change the decision. So the
 * existence is stated and the identity is not, which is the same split the
 * rest of the page now makes.
 *
 * The take-over copy that stood beside this is gone with the verb it
 * explained.
 */
const deleteCopy = (project: Project) => {
  const lines = []
  if (project.activeSessionId) {
    lines.push('A session is still holding it, and will be ended first.')
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
 * **The row had eight targets and now has three.** It carried, in order: a
 * disclosure, two tooltip-wrapped metadata spans, `Resume 3f2a…`, `New
 * session`, `Project`, `Ask`, `⋯` and a session preview — with the project
 * page, which is what the whole console hangs off, reachable only through the
 * sixth of them, small, in the secondary tone, past a flex spacer. Meanwhile
 * the largest and most obvious thing on the row, the project's name, was an
 * inert `<span>`, because `ProjectCard`'s `href` was optional and this file
 * never passed it. Counting the tab stops is the measurement: roughly eight
 * per row, so about seventy before a reader reached the second screen of a
 * list whose entire job is to be scrolled.
 *
 * What is left: the card itself is the link to the project page (⌘-click
 * works, and it did not before); one `Continue`; one `⋯` for the two verbs
 * that are not "read this project". `Project` is deleted because the card *is*
 * that button now, and `Ask` moves into the menu — it is a facet `App.tsx`
 * intercepts above `ProjectView`, so it genuinely cannot be reached by opening
 * the project and clicking a tab, and it still needs a door. That reasoning is
 * the one thing kept verbatim from the button it replaces, because the whole
 * history of this row is destinations quietly losing their entrances.
 *
 * **This is a container, not a card.** It renders no markup of its own: the
 * drawing is `ProjectCard`, which is props-only and therefore has a story and
 * a test that need neither a query client nor a container.
 *
 * **Why the hook is still per row.** A hook cannot be called in a loop, and
 * `VirtualList`'s children argument is a render callback rather than a
 * component, so "one `useProjectActivity` per drawn row" has to be a component
 * per drawn row — this one. It costs no request per row: every call reads the
 * one `queryKeys.runningAgents()` entry, so N mounts are N subscribers to one
 * fetch. `ProjectActivity.test.tsx` pins the request count.
 */
const ProjectListRow = ({
  rollup,
  open,
  onToggle,
  onDelete,
  onContinue,
  busy,
}: {
  rollup: ProjectRollup
  open: boolean
  onToggle: () => void
  onDelete: () => void
  onContinue: () => void
  busy: boolean
}) => {
  const { project, sessions, sessionCount, lastActivity } = rollup
  const current = currentSession(rollup)
  const [menuOpen, setMenuOpen] = useState(false)
  const activity = useProjectActivity(project.id)

  return (
    <ProjectCard
      rollup={rollup}
      href={projectHref(project.id)}
      open={open}
      onOpenChange={onToggle}
      slots={{
        // Nothing to badge: the workflow chip that filled this was "which
        // preset, and how far through it", and there are no presets. The slot
        // stays because the card declares it, not because this page wants it.
        badges: null,
        activity: <ActivityChip label={activity.label} />,

        /* A label, not a control. The card owns the button, the caret, the
           click and all three ARIA attributes; this file used to write
           `aria-expanded` and `aria-controls` by hand against an id derived
           through an exported helper, which is three chances for a silent
           mismatch to reach a screen reader and none for a gate to notice.
           Both wordings are kept exactly, because they are what a reader and a
           test both find this control by. */
        toggle:
          sessionCount > 1
            ? open
              ? `sessions (${sessionCount})`
              : `all ${sessionCount} sessions`
            : null,

        /* **Plain text, and it used to be two tooltips.** The relative time
           wrapped a `Tooltip` giving the exact timestamp, and the short id
           wrapped another giving the full one: two tab stops per row, on a
           virtualized list, for an abbreviation nobody was reading and an
           identifier that names a project already named in full six pixels
           above. The id is deleted outright rather than moved — a `ProjectId`
           on an index is a debugging aid, and the project page shows it.

           They are the view's words rather than the card's on purpose:
           `lastActivity` is the newest session *start*, not the last turn, and
           "no sessions yet" against "nothing has run in this project" is this
           page choosing what it can honestly claim.

           The second reason they are not tooltips is a stacking one: the
           card's stretched link covers the stat line, so a hover target there
           would be a target a mouse cannot reach. A tooltip that only a
           keyboard can open is the S-D3 defect with the sides swapped. */
        meta: <span>{lastActivity ? relativeTime(lastActivity) : 'no sessions yet'}</span>,

        /* One verb, and it does not name a session.

           This was `Resume 3f2a…` beside `New session` for a held project and
           `Open` for a free one — a branch a reader had to resolve before
           acting, expressed in a vocabulary (holding, taking over) that is
           about where the next write goes rather than about anything they
           wanted. `Continue` answers the only question an index is asked:
           carry on with this. Which of the two things it does is decided in
           the list above, from a field the reader never sees. */
        primary: (
          <Tooltip
            asChild
            explanation="Pick up this project's conversation, starting one if none is open"
          >
            <Button small tone="accent" disabled={busy} onClick={onContinue}>
              Continue
            </Button>
          </Tooltip>
        ),

        overflow: [
          /* Ask is a page rather than a tab, so it needs its own door.
             `App.tsx` intercepts the `ask` facet above `ProjectView` and
             renders `AskPage` instead — which means it cannot be reached by
             opening the project and clicking a MATERIAL tab, the way the graph
             and the documents can. An entrance here is the difference between
             a page a reader can find and one only a typed URL reaches. It is
             in the menu rather than on the row because the row is now one
             verb, and this is not the verb.

             Destructive things are behind the same click, so the row's default
             reading is "ways in" rather than "ways to lose things".

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
            <MenuItem
              onSelect={() => navigate(projectHref(project.id, { facet: 'ask', id: null }))}
            >
              Ask
            </MenuItem>
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

           **No `held` marker on it, and none in the forest either.** The
           previewed row *is* the holder in the usual case, so the chip labelled
           the thing a reader was already looking at with a word about lock
           ownership. `currentSession` still prefers the holder — that is the
           head state, and it is the half of this concept the page keeps.

           The note takes the same slot because the two are alternatives: a
           project with no sessions has nothing to preview and nothing to
           expand, so it is the only case where this says something instead of
           showing something. */
        preview: current ? (
          <SessionRow session={current} />
        ) : sessionCount === 0 ? (
          <p className="project-no-sessions">Nothing has run in this project yet.</p>
        ) : null,

        sessions: <SessionForest nodes={sessions} />,
      }}
    />
  )
}
