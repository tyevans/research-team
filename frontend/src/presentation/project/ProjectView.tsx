import { errorMessage } from '@application/ports/errors.ts'
import type { SessionStore } from '@application/session/session-store.ts'
import type { Course } from '@domain/project/course.ts'
import { ScrubPoint } from '@domain/session/scrub-point.ts'
import type { ProjectId, SessionId } from '@domain/shared/identifier.ts'

import { EmptyState, Loading } from '../common/primitives.tsx'
import { TabList, TabPanel, Tabs } from '../common/Tabs.tsx'
import { ArtifactList } from '../course/ArtifactList.tsx'
import { Findings } from '../course/Findings.tsx'
import { StageList, stagesLeftBehind } from '../course/StageList.tsx'
import { useCourse } from '../course/use-course.ts'
import { Pane } from '../layout/Pane.tsx'
import { Split } from '../layout/Split.tsx'
import { DocumentList } from '../research/DocumentList.tsx'
import { GraphPane } from '../research/GraphPane.tsx'
import { TopicList } from '../research/TopicList.tsx'
import { projectHref, sessionSelection, type Facet, type Selection } from '../routing/routes.ts'
import { navigate } from '../routing/use-route.ts'
import { SessionView } from '../session/SessionView.tsx'
import { QueueHeader } from './queue/QueueHeader.tsx'
import { PROJECT_TRACKS, useProjectPanes } from './use-project-panes.ts'

/** The three regions a project page has.
 *
 * Named for what they answer rather than for what they contain, which is the
 * argument for the merge in one line: QUEUE is "what is there to do", HOLDER is
 * "what is working on it right now", MATERIAL is "what has been produced". The
 * two pages this replaces cut across all three — the course page held stages
 * (QUEUE) and artifacts (MATERIAL); the research page held topics (QUEUE) and
 * documents and a graph (MATERIAL) — so a reader following one thread crossed a
 * route boundary to do it.
 */
export type Region = 'queue' | 'holder' | 'material'

/** Which region a selected facet lands in.
 *
 * Exported and total over `Facet` because "every facet reaches a region" is the
 * verification story for this slice, and a test can hold a pure function where
 * it cannot hold a JSX tree. Total rather than partial-with-a-default for the
 * same reason: a facet added to `FACETS` should fail to compile here rather
 * than silently land in QUEUE.
 *
 * `ask` is in the map because the type demands it and not because this
 * component renders it — `App.tsx` intercepts that facet above this view, since
 * the ask page is one conversation with no parts and nothing to read it
 * against. That interception is the one arm of the old dispatch that survives
 * this slice, and it is deliberate rather than overlooked: the plan's §2.0
 * describes a two-arm branch, and there are three arms in the code it was
 * written against.
 */
export const regionOf = (facet: Facet): Region => {
  switch (facet) {
    // A stage and a topic are both work items — things this project owes
    // somebody. That they arrived from two different pages is the accident.
    case 'stage':
    case 'topic':
    case 'ask':
      return 'queue'
    // A session is what is holding the project, and a file is a file *in* a
    // session's workspace: there is no project file outside one. So both reach
    // the same region, which is also how `file` finally renders something. It
    // has parsed and been linkable since the route grammar landed, and no view
    // read it — because the view that could was reachable only by session.
    case 'session':
    case 'file':
      return 'holder'
    case 'entity':
    case 'doc':
    case 'artifact':
    case 'finding':
      return 'material'
  }
}

/** Which facets MATERIAL offers, in the order it offers them.
 *
 * `artifact` first and therefore the default, which is a bundle decision rather
 * than a taste one: `GraphCanvas` is `React.lazy` over ~60 kB of
 * `react-force-graph-2d`, and a default of `entity` would pull that chunk on
 * every project page anybody opened. The plan's §2.3 makes the same call and
 * defers *checking* it to the slice where the size budget can be read against a
 * page with real content in it.
 */
type MaterialFacet = 'artifact' | 'finding' | 'doc' | 'entity'

const MATERIAL_TABS: readonly { id: MaterialFacet; label: string }[] = [
  { id: 'artifact', label: 'Artifacts' },
  { id: 'finding', label: 'Findings' },
  { id: 'doc', label: 'Documents' },
  { id: 'entity', label: 'Graph' },
]

const DEFAULT_MATERIAL: Facet = 'artifact'

/** A project, whole: one page with three regions instead of two pages.
 *
 * **This is a frame with unchanged tenants, and it is deliberately ugly.**
 * Every component below is the one that rendered before the merge, re-parented
 * and not rewritten — the stage rail still draws itself as a page-width rail,
 * the session view still draws its own heading inside a pane that already has
 * one, and nothing has been restyled to fit a column. That is the point of
 * doing the frame on its own: the container and the regions are two changes,
 * and shipping them together would be the largest change in the increment with
 * no way to tell which half broke. Later slices own the contents.
 *
 * A `Split` rather than three divs because the regions are peers whose widths a
 * reader trades against each other, and `Split` already owns that — the sizing,
 * the fold, the refusal to fold the last one open, and the handoff to the
 * stylesheet below the widest breakpoint. Building any of it again here is the
 * mistake `split-tracks.ts` was written about.
 */
export const ProjectView = ({
  projectId,
  selection,
  store,
  onLoaded,
}: {
  projectId: ProjectId
  /** What is selected, owned by the route. Not mirrored into state: the address
   *  bar is the single source of truth, so a reload reproduces the screen and
   *  every selection is sendable. */
  selection: Selection | null
  /** The shell's session store, threaded through because HOLDER mounts
   *  `SessionView` and the shell needs the same session's head for the
   *  breadcrumb. */
  store: SessionStore
  /** Reported upward because the breadcrumb wants the project's name, and the
   *  course request is the one that already has it. */
  onLoaded?: (course: Course | null) => void
}) => {
  const { course } = useCourse(projectId, onLoaded)
  const panes = useProjectPanes()

  const openStage = selection?.facet === 'stage' ? (selection.id ?? null) : null
  const watching: SessionId | null = selection?.facet === 'session' ? selection.id : null

  // The open tab follows the route rather than component state, for the reason
  // every other selection here does: a reader who has found the document that
  // answers their question wants to send *that*, and a tab held in state is not
  // sendable. Falls back when the selection belongs to another region, so
  // opening a stage does not blank this pane.
  const materialTab: Facet =
    selection && regionOf(selection.facet) === 'material' ? selection.facet : DEFAULT_MATERIAL

  /** Replaced rather than pushed by default, which is the rule the course
   *  page's stage toggle and the graph's entity selection both already follow:
   *  a selection here is a glance, and forty glances in the back stack make the
   *  back button useless. The caller says otherwise for the one selection that
   *  is a destination — watching a worker. */
  const select = (next: Selection | null, replace = true) => {
    navigate(projectHref(projectId, next), { replace })
  }

  return (
    <Split
      id="project"
      label="Project regions"
      tracks={PROJECT_TRACKS}
      collapsed={panes.collapsed}
      onCollapsedChange={panes.onCollapsedChange}
      onRefuse={panes.onRefuse}
    >
      <Pane
        id="queue"
        label="Queue"
        meta={
          course.data
            ? `${String(stagesLeftBehind(course.data))} of ${String(course.data.stageCount)} stages left behind`
            : undefined
        }
      >
        {/* The four panels slice 0 parked loose here, now one band of chrome.
            That slice's comment named this as the change that would make it
            true, and `QueueHeader` carries the argument. */}
        <QueueHeader
          projectId={projectId}
          watching={watching}
          // Pushed rather than replaced: opening a worker's transcript is a
          // destination, and the back button should come back out of it.
          onWatch={(sessionId) => select(sessionSelection(sessionId), false)}
          holdingSessionId={course.data?.holdingSessionId ?? null}
        />

        {course.isError ? (
          // The two 409s — no workflow, or one this build does not ship — are
          // the interesting failures and the server's message names which.
          <EmptyState heading="No course to show." detail={errorMessage(course.error)} />
        ) : course.isPending ? (
          <Loading what="course" />
        ) : (
          <StageList
            course={course.data}
            openStage={openStage}
            onToggleStage={(stageId) =>
              select(openStage === stageId ? null : { facet: 'stage', id: stageId })
            }
          />
        )}

        <TopicList projectId={projectId} />
      </Pane>

      {/* `regions` rather than the default, and it is load-bearing.
          `SessionView` is itself a `Split`, which is `flex: 1 1 auto` inside
          whatever holds it; a scrolling body would be a box scrolling around a
          transcript that already scrolls — the box-inside-a-box `Pane`
          documents. With `regions` the body is a flex column that does not
          scroll, the nested split takes the height, and the three session panes
          keep their own scrollers.

          The nesting was checked rather than assumed, because it is the hazard
          the plan's §2.2 rests its slice order on. `Split` publishes its state
          through a React context that `Pane` reads from the *nearest* provider,
          so the session panes read the session split and the region panes read
          this one, with no crosstalk and no shared last-open rule. The two
          persistence groups are different strings. `splitTemplate` writes
          `grid-template-columns` inline on each `.lay-split` element and the
          two elements are different, so neither can overwrite the other — and
          `responsive.css`'s `[data-split='session']` rules still match the
          inner one, since the attribute is on the element they select. What
          nesting costs is a pane header inside a pane header, which is the ugly
          this slice accepts and slice 2 removes by lifting the inner `Split`
          out. */}
      <Pane id="holder" label="Holding session" scroll="regions">
        <Holder
          store={store}
          selection={selection}
          holdingSessionId={course.data?.holdingSessionId ?? null}
        />
      </Pane>

      <Pane id="material" label="Material" scroll="regions">
        {/* Utilities rather than a stylesheet, per the standing policy: new
            surfaces are dressed in utilities and no stylesheet is added. The
            flex column is what carries the pane body's height down to
            `.graph-browser`, which is `flex: 1; min-height: 0` and draws
            nothing in a box with no height. */}
        <Tabs
          value={materialTab}
          // The cast is narrow and is the one Radix forces: `Tabs` is
          // controlled by `string`, and every value it can hand back is an id
          // this component declared in `MATERIAL_TABS`.
          onValueChange={(next) => select({ facet: next as MaterialFacet, id: null })}
          className="flex min-h-0 flex-1 flex-col"
        >
          <TabList label="Material" options={MATERIAL_TABS} />

          <TabPanel value="artifact" className="min-h-0 flex-1 overflow-auto">
            {course.data ? <ArtifactList course={course.data} /> : <Loading what="artifacts" />}
          </TabPanel>

          <TabPanel value="finding" className="min-h-0 flex-1 overflow-auto">
            {course.data ? <ProjectFindings course={course.data} /> : <Loading what="findings" />}
          </TabPanel>

          {/* No `overflow-auto`: the document list owns a virtualizer, which
              owns a scroll container, and a scroller around it is the outer box
              absorbing the wheel from the inner one. */}
          <TabPanel value="doc" className="flex min-h-0 flex-1 flex-col">
            <DocumentList projectId={projectId} />
          </TabPanel>

          <TabPanel value="entity" className="flex min-h-0 flex-1 flex-col">
            <GraphPane
              projectId={projectId}
              entity={selection?.facet === 'entity' ? (selection.id ?? null) : null}
              // Replaced rather than pushed, for the reason it was replaced on
              // the research page: browsing a graph also *grows* it, so a back
              // button restoring the previous entity would return a URL
              // describing a smaller graph than the one on screen.
              onEntity={(entity) => select({ facet: 'entity', id: entity })}
            />
          </TabPanel>
        </Tabs>
      </Pane>
    </Split>
  )
}

/** What HOLDER shows: a session, or a sentence saying there is none.
 *
 * Split out because the choice of session has three sources and reads badly
 * inline — an explicitly watched one, the project's holding session as the
 * default, and neither.
 */
const Holder = ({
  store,
  selection,
  holdingSessionId,
}: {
  store: SessionStore
  selection: Selection | null
  holdingSessionId: SessionId | null
}) => {
  const watched = selection?.facet === 'session' ? selection.id : null
  const sessionId = watched ?? holdingSessionId

  if (sessionId === null) {
    return (
      <EmptyState
        heading="Nothing is holding this project."
        detail="Join the project from the landing page, and the session working on it appears here."
      />
    )
  }

  return (
    <SessionView
      store={store}
      sessionId={sessionId}
      at={selection?.facet === 'session' ? selection.at : ScrubPoint.head()}
      // The `file` facet's first renderer. A project file is a file in the
      // holding session's workspace, so this is the component that could always
      // have answered it — it was never reached, because the only route into it
      // named a session.
      path={
        selection?.facet === 'file'
          ? selection.id
          : selection?.facet === 'session'
            ? selection.path
            : null
      }
    />
  )
}

/** `Findings` renders `null` when a stage has nothing to report, which is right
 *  inside a page with other content on it and wrong as the whole of a tab: an
 *  empty panel reads as a load that failed. */
const ProjectFindings = ({ course }: { course: Course }) =>
  course.findings.length === 0 && course.unimplementedChecks.length === 0 ? (
    <EmptyState
      heading="No checks have reported on this stage."
      detail="Findings appear here when a gate or a critic runs against the current stage."
    />
  ) : (
    <Findings course={course} />
  )
