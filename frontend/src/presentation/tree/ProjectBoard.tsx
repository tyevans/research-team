import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useMemo, useState, type RefObject } from 'react'

import { notify } from '@application/notifications/toast-store.ts'
import { errorMessage } from '@application/ports/errors.ts'
import { queryKeys } from '@application/queries/keys.ts'
import { useContainer } from '@app/container-context.tsx'
import { board, scaleOf, type Sort } from '@domain/project/board.ts'
import { isHeld, type Project, type ProjectListing } from '@domain/project/project.ts'
import type { ProjectId } from '@domain/shared/identifier.ts'
import type { Roster } from '@domain/worker/worker.ts'

import { Confirm } from '../common/Confirm.tsx'
import { elapsed } from '../formatting/format.ts'
import { EmptyState, ErrorBox } from '../common/primitives.tsx'
import { VirtualList } from '../common/VirtualList.tsx'
import { sessionHref } from '../routing/routes.ts'
import { navigate } from '../routing/use-route.ts'
import { ProjectBoardRow } from './ProjectBoardRow.tsx'
import { SkeletonRows } from './Skeletons.tsx'

/** What a board row is assumed to be before it is drawn.
 *
 * An **estimate that is exactly right**, rather than one the virtualizer has
 * to correct: every row is the same height now that the disclosure and the
 * session preview are gone, and the note line under each track is reserved
 * whether or not there is a note to put in it.
 *
 * **Measured, not chosen.** 97px is what a real row lays out to in Chromium
 * at 1440x900, including the item's own bottom padding; this constant was 128
 * until it was measured, which is a 25px error per row and would have put the
 * fourth row a hundred pixels from where the virtualizer expected it.
 * `project-board.browser.test.tsx` holds the two together — they are one fact
 * written twice, and the previous page's equivalent pair were 108 and 84 until
 * a test existed.
 */
export const BOARD_ROW_HEIGHT = 97

/** The projects, as a board rather than a list of cards.
 *
 * The one query, the one scale, and the two writes this page still makes.
 *
 * **The recency headings are gone, and adding sort is what removed them.**
 * `ProjectRows` grouped rows under "Today" / "This week" / "Older", and the
 * heading's virtualizer key was unique only because the input happened to be
 * sorted by band — its own comment warned that "anything that reorders results
 * silently produces duplicate keys and one measurement cell holding two rows'
 * heights". A sort control is precisely that reordering. So the headings could
 * not survive this page gaining one, and dropping them removes the precondition
 * rather than leaving it to be violated later. They were also not earning
 * their space: measured against the real database, five of six projects sat
 * under "Today", so the band labelled nothing and cost a row of chrome.
 */
export const ProjectBoard = ({
  scrollRef,
  search,
  sort,
}: {
  scrollRef: RefObject<HTMLElement | null>
  search: string
  sort: Sort
}) => {
  const { projects, workers } = useContainer()
  const queryClient = useQueryClient()
  const invalidate = () => queryClient.invalidateQueries({ queryKey: queryKeys.projects() })

  const query = useQuery({ queryKey: queryKeys.projects(), queryFn: () => projects.list() })
  const [pending, setPending] = useState<Project | null>(null)

  /** The whole board's live markers in one read.
   *
   * Hoisted out of the row, which is the change from the previous page: it
   * called `useProjectActivity` per drawn row, which cost no extra requests
   * (every call reads the same cache entry) but did mean the row could not be
   * rendered without a query client. Reading the roster once here makes
   * `ProjectBoardRow` props-only and testable without any of that machinery.
   */
  const rosters = useQuery({
    queryKey: queryKeys.runningAgents(),
    queryFn: () => workers.everywhere(),
    // A failed liveness read must not degrade the board: every row is still a
    // working link, and an error where a chip would go says nothing a reader
    // can act on. The next invalidation asks again.
    retry: false,
  })

  const carryOn = useMutation({
    mutationFn: ({ id }: { id: ProjectId }) => projects.join(id, false),
    onSuccess: (result) => {
      if (result.warning) notify(`Joined, but ${result.warning}`, 'bad')
      navigate(sessionHref(result.sessionId))
    },
    onError: (error) => notify(`Could not open project: ${errorMessage(error)}`, 'bad'),
    onSettled: invalidate,
  })

  /** `isHeld` is the surviving load-bearing read of the holder.
   *
   * It is the `force` flag: deleting a held project has to end its session
   * first, and a `false` here would fail against exactly the projects a person
   * is most likely to delete. Nothing on the board draws the holder, so this
   * is the argument that would rot silently — `ProjectBoard.test.tsx` asserts
   * on the second argument for that reason.
   */
  const remove = useMutation({
    mutationFn: ({ project }: { project: Project }) => projects.delete(project.id, isHeld(project)),
    onSuccess: (_result, { project }) => notify(`Deleted project ${project.name}.`, 'good'),
    onError: (error) => notify(`Could not delete project: ${errorMessage(error)}`, 'bad'),
    onSettled: invalidate,
  })

  const all = useMemo(() => query.data ?? [], [query.data])
  const shown = useMemo(() => board(all, search, sort), [all, search, sort])

  /** Scaled over **everything**, not over what the search left.
   *
   * The bars would otherwise rescale as a reader types, so the same project's
   * sources bar would be half-length in the full list and full-length as the
   * only match — which reads as the number having changed. A scale that moves
   * under a filter is a scale nobody can trust.
   */
  const scale = useMemo(() => scaleOf(all), [all])

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
  if (all.length === 0) {
    // Reached only when sessions exist — a database with neither is the
    // first-run page, which `TreeView` renders instead of this board.
    return (
      <EmptyState
        heading="No projects yet."
        detail="Any sessions in this database predate projects and cannot be reached from here. Create a project to start work that successive sessions share a filesystem and a knowledge graph with."
      />
    )
  }
  if (shown.length === 0) {
    return <EmptyState heading={`No project is called “${search.trim()}”.`} />
  }

  return (
    <>
      <VirtualList
        items={shown}
        scrollRef={scrollRef}
        className="relative m-0 list-none p-0"
        getKey={(listing) => String(listing.id)}
        estimate={() => BOARD_ROW_HEIGHT}
        overscan={4}
      >
        {(listing, position) => (
          <li
            ref={position.measure}
            data-index={position.index}
            className="pb-3"
            data-board-item
            style={{
              position: 'absolute',
              top: 0,
              left: 0,
              right: 0,
              transform: `translateY(${position.top}px)`,
            }}
          >
            <ProjectBoardRow
              listing={listing}
              scale={scale}
              activity={activityOf(rosters.data, listing)}
              onDelete={() => setPending(listing)}
              onContinue={() => {
                const holder = listing.activeSessionId
                if (holder) navigate(sessionHref(holder))
                else carryOn.mutate({ id: listing.id })
              }}
              busy={carryOn.isPending || remove.isPending}
            />
          </li>
        )}
      </VirtualList>
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

/** This project's live label out of the whole-board roster, or null.
 *
 * The row-level half of what `useProjectActivity` did, as a plain function
 * rather than a hook, because the fetch has moved up to the board. The
 * precedence — a run outranks a turn — is kept explicitly rather than taken as
 * `workers[0]`, for the reason that hook recorded: `everywhere()` says nothing
 * about the order within a roster, so `[0]` would make the label depend on
 * whatever order the server happened to fold in.
 *
 * **The elapsed suffix is part of the label and was dropped for one draft.**
 * Moving the hook's body here lost `· 4m`, silently: the chip still said "turn
 * running", which is plausible enough that nothing looked wrong, and the only
 * thing that noticed was the deleted hook's own test. It is restored, and
 * `TreeView.test.tsx` asserts on it now — the reason a run has no suffix is
 * that the server sends `startedAt: null` for one (`workers.py`), not that this
 * function declines to render it.
 */
const activityOf = (
  rosters: readonly Roster[] | undefined,
  listing: ProjectListing,
): string | null => {
  const roster = rosters?.find((one) => one.projectId === listing.id)
  const worker = roster?.workers.find((one) => one.kind === 'run') ?? roster?.workers[0]
  if (!worker) return null
  const what = worker.kind === 'turn' ? 'turn running' : `${worker.kind} running`
  const since = worker.startedAt ? elapsed(worker.startedAt) : ''
  return since ? `${what} · ${since}` : what
}

/** The sentence this page must not lose.
 *
 * Kept word for word. "Delete" does something a reader will assume is worse
 * than it is — it retires a project without touching the work done in it —
 * and this is the sentence that says so.
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
