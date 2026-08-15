import { useCallback } from 'react'

import { errorMessage } from '@application/ports/errors.ts'
import type { SessionStore } from '@application/session/session-store.ts'
import type { Course } from '@domain/project/course.ts'
import { ScrubPoint } from '@domain/session/scrub-point.ts'
import type { FilePath } from '@domain/shared/file-path.ts'
import { SourceId, TopicId, type ProjectId, type SessionId } from '@domain/shared/identifier.ts'

import { Confirm } from '../common/Confirm.tsx'
import { EmptyState, Loading } from '../common/primitives.tsx'
import { TabList, TabPanel, Tabs } from '../common/Tabs.tsx'
import { ArtifactList } from '../course/ArtifactList.tsx'
import { Findings } from '../course/Findings.tsx'
import { StageList, stagesLeftBehind } from '../course/StageList.tsx'
import { useCourse } from '../course/use-course.ts'
import { Pane } from '../layout/Pane.tsx'
import { Split } from '../layout/Split.tsx'
import { DocumentList } from '../research/DocumentList.tsx'
import { EntityTreePane } from '../research/EntityTreePane.tsx'
import { GraphPane } from '../research/GraphPane.tsx'
import { TimelinePane } from '../research/TimelinePane.tsx'
import { TopicList } from '../research/TopicList.tsx'
import { projectHref, sessionSelection, type Facet, type Selection } from '../routing/routes.ts'
import { navigate } from '../routing/use-route.ts'
import {
  ComposerPanel,
  ConversationPanel,
  conversationMeta,
  TimelineFeed,
  TimelinePanel,
  timelineMeta,
  WorkspacePanel,
} from '../session/panels.tsx'
import { ScrubBar } from '../session/ScrubBar.tsx'
import { useSessionScreen } from '../session/use-session-screen.ts'
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
    // A session is what is holding the project: HOLDER is "who is working on
    // this right now", and a session is the answer.
    case 'session':
      return 'holder'
    // A file is **not**, and this is the one mapping slice 2 reverses. It read
    // `holder` because a project file is a file in the holding session's
    // workspace, which is true and is about where the bytes come from — not
    // about which question the reader is asking. The three regions are named
    // for questions, and "what has this project produced" is the one a file
    // answers: the workspace tree beside the artifacts is the live half of the
    // same shelf. Keeping it in HOLDER also cost the arrangement, because a
    // file list, a file viewer, a transcript and a composer stacked in one
    // column is four scrollers in the width of one region.
    case 'file':
      return 'material'
    case 'entity':
    case 'timeline':
    case 'tree':
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
 * page with real content in it. **`file` arriving does not disturb that
 * argument** — the workspace is `FileList` and `FileView`, both already in the
 * main chunk — so the default stays `artifact` and this slice does not also
 * change what a project page opens on.
 *
 * **Workspace second, and the order is an argument rather than an accident.**
 * Artifacts and the workspace are the same shelf at two ages: an artifact is
 * what a stage declared it produced, and the workspace is the tree those
 * declarations are made *of*, live and at any scrub point. Putting them
 * adjacent means a reader checking whether a declared output actually exists
 * moves one tab rather than three. Findings, documents and the graph are all
 * about material that arrived from outside the course, so they sit after.
 */
type MaterialFacet = 'artifact' | 'file' | 'finding' | 'doc' | 'entity' | 'tree' | 'timeline'

const MATERIAL_TABS: readonly { id: MaterialFacet; label: string }[] = [
  { id: 'artifact', label: 'Artifacts' },
  { id: 'file', label: 'Workspace' },
  { id: 'finding', label: 'Findings' },
  { id: 'doc', label: 'Documents' },
  { id: 'entity', label: 'Graph' },
  // Directly after Graph, not at the end: the tree is the graph's own material
  // read a second way (a list instead of a drawing), same as Timeline is a
  // second way (ordered by time) -- and the two adjacent readings belong next
  // to each other. Doesn't touch the bundle argument above: nothing in the
  // tree is lazy and nothing in it pulls a canvas, so inserting it here costs
  // nothing and Timeline still closes the list.
  { id: 'tree', label: 'Tree' },
  // After Graph, not before: this list is ordered by what the reader is asking,
  // and the timeline is a second reading of the graph's own material. Last also
  // keeps it out of the default position, which matters for the same bundle
  // reason `artifact` is default -- `TimelineCanvas` is lazy, and a default of
  // `timeline` would pull it on every project page anybody opened.
  { id: 'timeline', label: 'Timeline' },
]

const DEFAULT_MATERIAL: Facet = 'artifact'

/** A project, whole: one page with three regions instead of two pages.
 *
 * **A frame with mostly-unchanged tenants.** Slice 0 built this as three panes
 * holding the components the two old pages happened to have, unrestyled, on
 * purpose: the container and the regions are two changes and shipping them
 * together leaves no way to tell which half broke. Slice 1 gave QUEUE its header
 * band; slice 2 took the nesting out of HOLDER and gave MATERIAL the workspace;
 * slice 3 rewrote three of MATERIAL's five tabs in utilities and threaded their
 * route ids in. The stage list is still the course page's rail and the topic
 * list is still the research page's, both in QUEUE, and neither is MATERIAL's
 * to rewrite — which is also why neither `course.css` nor `research.css` has
 * died yet.
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
  /** The shell's session store, threaded through because HOLDER reads the
   *  holding session and the shell needs the same session's head for the
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

  /** Whose transcript HOLDER is reading: an explicitly watched session, the
   *  project's holding session as the default, or neither. `null` is a real and
   *  common state — a project nobody has joined — and it is why the screen hook
   *  below takes a nullable id rather than being called from inside a branch. */
  const sessionId: SessionId | null = watching ?? course.data?.holdingSessionId ?? null

  const openPath: FilePath | null =
    selection?.facet === 'file'
      ? selection.id
      : selection?.facet === 'session'
        ? selection.path
        : null

  /** Where a scrub or a file-open writes itself **on this page**, which is not
   *  where `SessionView` writes it.
   *
   * A `session` selection is the only one the route grammar gives an `at` and a
   * `path`, so both land there; the standalone `#/s/` address would be a
   * navigation off the project page, which is what this replaces. `sessionId`
   * cannot be null at the point either callback fires — nothing that calls them
   * is rendered without one — and the fallback keeps the reader on the page
   * rather than inventing an address if that ever stops being true.
   */
  const href = useCallback(
    (at: ScrubPoint, path: FilePath | null) =>
      sessionId === null
        ? projectHref(projectId)
        : projectHref(projectId, sessionSelection(sessionId, at, path)),
    [projectId, sessionId],
  )

  const screen = useSessionScreen({
    store,
    sessionId,
    at: selection?.facet === 'session' ? selection.at : ScrubPoint.head(),
    path: openPath,
    href,
  })

  // The open tab follows the route rather than component state, for the reason
  // every other selection here does: a reader who has found the document that
  // answers their question wants to send *that*, and a tab held in state is not
  // sendable. Falls back when the selection belongs to another region, so
  // opening a stage does not blank this pane.
  //
  // The first arm is the one that is not obvious. A session selection carrying
  // a path *is* a workspace selection — it is what `href` above writes when a
  // reader opens a file or scrubs while reading one — and without this arm the
  // second arm would fall through to `artifact` and close the Workspace tab
  // under them on the first click. `#/p/<id>/file/<path>` still arrives through
  // the second arm, which is what makes that URL a linkable entry point.
  /** The id the route carries for a MATERIAL facet, or `null`.
   *
   * **This is the half of "already linkable" that was not true.** `topic`,
   * `doc`, `artifact` and `finding` all parse an id, land on `selection` and
   * reach the right region — and were then mounted with `projectId` or `course`
   * alone, each component holding its open item in its own `useState`. Four
   * linkable states that opened the right tab and forgot what the link was
   * about, and one of them was a shipped broken link: `CitationList` writes
   * `#/p/<id>/doc/<sourceId>` and following it produced an unfiltered corpus.
   *
   * The plan's §1 says "a topic, a stage and an artifact are already linkable
   * states … a precondition that is met". Only the stage half was true, which
   * is why no slice had budgeted this.
   *
   * Two literal comparisons rather than one helper taking a facet: comparing
   * against a *variable* narrows nothing, so `selection.id` would still be the
   * union of every facet's id type — including `FilePath`, which is an object
   * and would reach a row as `[object Object]` through any `String()` that
   * silenced the type error.
   */
  const openArtifact = selection?.facet === 'artifact' ? selection.id : null
  const openFinding = selection?.facet === 'finding' ? selection.id : null
  const openDoc =
    selection?.facet === 'doc' && selection.id !== null ? SourceId(selection.id) : null
  /** QUEUE's, not MATERIAL's, and the fourth of the four that parsed an id and
   *  dropped it. `#/p/<id>/topic/<tid>` reached this region and rendered the
   *  default queue, because `TopicList` took `projectId` alone and the open
   *  topic was `useState` inside `useTopicQueue` — so a link to a topic was a
   *  link to the project page, and the reader found the question by hand.
   *
   * Branded through `TopicId(...)` exactly as `openDoc` is through
   * `SourceId(...)`: the route's ids are strings, the repository ports take
   * brands, and the constructor is where a string becomes one. */
  const openTopic =
    selection?.facet === 'topic' && selection.id !== null ? TopicId(selection.id) : null

  const materialTab: Facet =
    selection?.facet === 'session' && selection.path !== null
      ? 'file'
      : selection && regionOf(selection.facet) === 'material'
        ? selection.facet
        : DEFAULT_MATERIAL

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

        {/* Replaced rather than pushed, like the stage toggle above it and
            every MATERIAL selection below: a topic is a **glance**, not a
            destination. The queue is a list a reader scans — open a question,
            read what it is blocked on, go back to the list, open the next —
            and the honest test is what the back button should do after
            forty of those. Pushed, it walks back out through thirty-nine
            topics before it leaves the project page; replaced, it leaves.
            Watching a worker is the one selection on this page that is a
            destination, and it is the one that passes `false`.

            Closing writes `null` rather than `{ facet: 'topic', id: null }`,
            which is where this differs from the document list. A doc's close
            keeps its facet because MATERIAL has *tabs* and dropping the facet
            would close the Documents tab under the reader; QUEUE is always
            rendered whatever the facet is, so there is nothing for a bare
            `topic` selection to hold open and it would only be a URL that
            means the same as no selection at all. */}
        <TopicList
          projectId={projectId}
          open={openTopic}
          onOpen={(topicId) => select(topicId === null ? null : { facet: 'topic', id: topicId })}
        />
      </Pane>

      {/* `regions` rather than the default, and it is load-bearing: the body is
          a flex column that does not scroll, so the two sections inside it can
          each own a scroller and split the leftover height between them. A
          scrolling body here would be a box scrolling around a transcript that
          already scrolls — the box-inside-a-box `Pane` documents.

          **No `Split` and no `Pane` inside this one, which is the change.**
          Slice 0 mounted `SessionView` whole, and `SessionView` is itself a
          three-pane `Split`: a pane header inside a pane header, two collapse
          groups, and a reader who could fold the event log inside a region they
          could also fold. The nesting worked — the slice's browser test proved
          the height travelled — and it was still the wrong shape, because
          HOLDER is one region and a region's contents are not panes. */}
      <Pane id="holder" label="Holding session" scroll="regions">
        {sessionId === null ? (
          <EmptyState
            heading="Nothing is holding this project."
            detail="Join the project from the landing page, and the session working on it appears here."
          />
        ) : (
          <>
            <ScrubBar
              head={screen.state.head}
              log={screen.state.log}
              scrub={screen.state.scrub}
              loading={screen.state.loadingSnapshot}
              onSelect={screen.selectEvent}
              onFork={() => {
                if (screen.state.scrub.kind === 'historical') screen.forkAt(screen.state.scrub.at)
              }}
              onEndSession={() => screen.setEndPending(true)}
            />

            {screen.endPending ? (
              <Confirm
                heading="End this session and hand its files back to the project?"
                lines={[
                  'The log stays readable and forkable.',
                  "The project becomes free, and the next session in it starts from this one's files.",
                ]}
                confirmLabel="End the session"
                onCancel={() => screen.setEndPending(false)}
                onConfirm={() => {
                  screen.setEndPending(false)
                  screen.endSession()
                }}
              />
            ) : null}

            {/* Each section names itself, because it no longer gets a name from
                a `Pane` header — and losing those two names is the one thing
                un-nesting could quietly have cost. A screen-reader user
                navigating by region had "Event log" and "Conversation" here
                yesterday; `aria-label` on a `<section>` is the same landmark
                without the visible heading, chrome and a fold toggle that the
                region above already provides.

                The meta lines are the same strings the pane headers wrote,
                through the same helpers, which is why they are helpers. */}
            <section
              aria-label="Event log"
              className="flex min-h-0 flex-1 flex-col border-0 border-b border-solid border-line"
            >
              <SectionHead label="Event log" meta={timelineMeta(screen.state.log.length)} />
              {/* The scroller is this box and not `.timeline`, which has no
                  overflow of its own — `timeline.css:4` is a bare flex column,
                  and on `#/s/` the `Pane` body is what scrolls it. Something
                  here has to, or the log runs the page's whole height. */}
              <div className="min-h-0 flex-1 overflow-auto" data-holder-scroll="log">
                <TimelinePanel screen={screen} />
              </div>
              <TimelineFeed store={store} />
            </section>

            <section aria-label="Conversation" className="flex min-h-0 flex-1 flex-col">
              <SectionHead
                label="Conversation"
                meta={conversationMeta(
                  screen.messages.length,
                  screen.compacted,
                  screen.historicalAt,
                )}
              />
              {/* No scroller of its own: `Conversation` renders `.conv-scroll`,
                  which is already `flex: 1 1 auto; min-height: 0; overflow:
                  auto`, and holds a ref on it to stick to the bottom. A box
                  around it would absorb the wheel from the box that measures. */}
              <ConversationPanel screen={screen} />
            </section>

            {/* Pinned last and outside both scrollers, which is what `Pane`'s
                `footer` slot did on `#/s/`. Inside either one it scrolls away,
                and a composer that leaves the screen as the conversation grows
                is the defect that slot exists for. */}
            <ComposerPanel screen={screen} store={store} />
          </>
        )}
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
            {course.data ? (
              <ArtifactList course={course.data} open={openArtifact} />
            ) : (
              <Loading what="artifacts" />
            )}
          </TabPanel>

          {/* No `overflow-auto`, for the same reason the document list has
              none: `WorkspacePanel` is a file list over a file viewer, each
              scrolling on its own — `workspace.css` gives `.files` its own
              `overflow: auto` and a 34% cap, and `.file-view` the rest. This
              panel is the flex column those two are sized against, which is
              exactly what the `scroll="regions"` pane body was on `#/s/`. */}
          <TabPanel value="file" className="flex min-h-0 flex-1 flex-col">
            {sessionId === null ? (
              // The other half of "nothing is holding this project", and it
              // needs its own sentence for the reason `ProjectFindings` below
              // does: a blank panel reads as a load that failed. A project
              // workspace is a *session's* workspace, so with no session there
              // is no tree to show rather than an empty one.
              <EmptyState
                heading="No workspace yet."
                detail="A project's files belong to the session holding it. Join the project and its tree appears here."
              />
            ) : (
              <WorkspacePanel screen={screen} sessionId={sessionId} openPath={openPath} />
            )}
          </TabPanel>

          <TabPanel value="finding" className="min-h-0 flex-1 overflow-auto">
            {course.data ? (
              <ProjectFindings course={course.data} open={openFinding} />
            ) : (
              <Loading what="findings" />
            )}
          </TabPanel>

          {/* No `overflow-auto`: the document list owns a virtualizer, which
              owns a scroll container, and a scroller around it is the outer box
              absorbing the wheel from the inner one. */}
          <TabPanel value="doc" className="flex min-h-0 flex-1 flex-col">
            {/* Replaced rather than pushed, like every other selection here:
                opening a source is a glance down a list, and the drawer's own
                close writes `{ facet: 'doc', id: null }` so that closing it
                leaves the reader on the Documents tab rather than back at the
                default one. */}
            <DocumentList
              projectId={projectId}
              open={openDoc}
              onOpen={(sourceId) => select({ facet: 'doc', id: sourceId })}
            />
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

          <TabPanel value="tree" className="flex min-h-0 flex-1 flex-col">
            <EntityTreePane
              projectId={projectId}
              entity={selection?.facet === 'tree' ? (selection.id ?? null) : null}
              onEntity={(entity) => select({ facet: 'tree', id: entity })}
            />
          </TabPanel>

          <TabPanel value="timeline" className="flex min-h-0 flex-1 flex-col">
            <TimelinePane
              projectId={projectId}
              entity={selection?.facet === 'timeline' ? (selection.id ?? null) : null}
              onEntity={(entity) => select({ facet: 'timeline', id: entity })}
            />
          </TabPanel>
        </Tabs>
      </Pane>
    </Split>
  )
}

/** The heading a stacked HOLDER section gets instead of a pane header.
 *
 * Deliberately not a `Pane`. What a pane header carries that this does not is a
 * fold toggle and a `<section>` of its own with the collapse machinery behind
 * it, and HOLDER's sections are not foldable — the region is, once, from the
 * split above. What is kept is the two things a reader actually used the header
 * for: which of the two stacked boxes they are looking at, and its count.
 *
 * `<h3>` because the pane's own `<h2>` is directly above it, so the outline
 * stays in order. Not `sticky`: the scroller is the box *below* this element,
 * so it does not move.
 */
const SectionHead = ({ label, meta }: { label: string; meta: string | undefined }) => (
  <div className="flex shrink-0 items-baseline gap-2 px-3 py-1 text-xs text-fg-dim">
    <h3 className="font-medium tracking-wide m-0 text-xs uppercase">{label}</h3>
    {meta === undefined ? null : <span className="text-fg-faint">{meta}</span>}
  </div>
)

/** `Findings` renders `null` when a stage has nothing to report, which is right
 *  inside a page with other content on it and wrong as the whole of a tab: an
 *  empty panel reads as a load that failed. */
const ProjectFindings = ({ course, open }: { course: Course; open: string | null }) =>
  course.findings.length === 0 && course.unimplementedChecks.length === 0 ? (
    <EmptyState
      heading="No checks have reported on this stage."
      detail="Findings appear here when a gate or a critic runs against the current stage."
    />
  ) : (
    <Findings course={course} open={open} />
  )
