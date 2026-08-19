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
import { OntologyPane } from '../research/OntologyPane.tsx'
import { EntityTreePane } from '../research/EntityTreePane.tsx'
import { GraphPane } from '../research/GraphPane.tsx'
import { MediaProposalPane } from '../research/MediaProposalPane.tsx'
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

/** The two regions a project page has: a sidebar and the content beside it.
 *
 * Named for what they answer rather than for what they contain, which is the
 * argument for the merge in one line: QUEUE is "what is there to do" and
 * MATERIAL is "what has come of it". The two pages this replaces cut across
 * both — the course page held stages (QUEUE) and artifacts (MATERIAL); the
 * research page held topics (QUEUE) and documents and a graph (MATERIAL) — so a
 * reader following one thread crossed a route boundary to do it.
 *
 * **There were three.** HOLDER answered "what is working on it right now" and
 * was the middle column; it is a tab in MATERIAL now, and `regionOf` below
 * carries both the reasoning and what it costs.
 */
export type Region = 'queue' | 'material'

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
    //
    // `dialogue` joins `ask` at the end of this group for the same reason and
    // with the same caveat: `App.tsx` intercepts both above this view, so
    // neither is drawn by a region. The map is total over `Facet`, so they
    // have to be somewhere, and "what is there to do" is where a conversation
    // belongs. (The comment lives up here rather than beside those two cases
    // because `no-fallthrough` defaults to `allowEmptyCase: false`, and a
    // comment between empty cases reads to it as a fallthrough.)
    case 'stage':
    case 'topic':
    case 'ask':
    case 'dialogue':
      return 'queue'
    // A session used to be its own region — HOLDER, "who is working on this
    // right now" — and is now a tab in MATERIAL. The question it answers has
    // not changed; what changed is that the page is a sidebar over one content
    // area rather than three peers, so there is one place for everything a
    // reader reads and QUEUE is the only thing beside it.
    //
    // The cost, recorded rather than argued away: a transcript and the output
    // it produced can no longer be on screen together. That was HOLDER's whole
    // argument for existing, and it loses to a permanent third of the page
    // spent on material a reader consults rather than reads.
    case 'session':
      return 'material'
    // A file is **not**, and this is the one mapping slice 2 reverses. It read
    // `holder` because a project file is a file in the holding session's
    // workspace, which is true and is about where the bytes come from — not
    // about which question the reader is asking. The regions are named
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
    case 'ontology':
    case 'doc':
    case 'media':
    case 'artifact':
    case 'finding':
      return 'material'
  }
}

/** Which facets MATERIAL offers, in the order it offers them.
 *
 * **The default tab is loaded on every project page, so what sits first is a
 * bundle decision as much as a taste one.** `GraphCanvas` is `React.lazy` over
 * ~60 kB of `react-force-graph-2d` and `TimelineCanvas` is lazy too, so
 * `entity` and `timeline` are kept out of the first position and sit last.
 * `artifact` held that position until the holding session took it; the swap
 * costs nothing, because the session's panels were a permanent region until
 * this slice and are all in the main chunk already. Checked rather than
 * assumed — `npm run size` after the change: app 75.1 kB of 80.
 *
 * **Artifacts then Workspace, and the order is an argument rather than an
 * accident.**
 * Artifacts and the workspace are the same shelf at two ages: an artifact is
 * what a stage declared it produced, and the workspace is the tree those
 * declarations are made *of*, live and at any scrub point. Putting them
 * adjacent means a reader checking whether a declared output actually exists
 * moves one tab rather than three. Findings, documents and the graph are all
 * about material that arrived from outside the course, so they sit after.
 */
type MaterialFacet =
  | 'session'
  | 'artifact'
  | 'file'
  | 'finding'
  | 'doc'
  | 'media'
  | 'entity'
  | 'tree'
  | 'ontology'
  | 'timeline'

/** Exported so `project-tracks.browser.test.tsx` can compare the strip it
 *  measures against the strip that was declared — a count taken from the
 *  rendered row alone cannot tell "eight tabs" from "eight of nine rendered". */
export const MATERIAL_TABS: readonly { id: MaterialFacet; label: string }[] = [
  // First, and therefore the default, which reverses the argument the two
  // paragraphs above make for `artifact`. Both halves of that argument survive:
  // the default tab is the one loaded on every project page, and `entity` and
  // `timeline` are still kept out of the position for exactly that reason. What
  // changed is that the holding session is no longer *optional* content — it
  // was a permanent region until this slice, so every panel it renders is
  // already in the main chunk and defaulting to it pulls nothing new.
  //
  // First rather than merely present because it is what the page is about: a
  // reader opening a project is asking what is happening to it, and the answer
  // used to be the middle third of the screen.
  { id: 'session', label: 'Holding session' },
  { id: 'artifact', label: 'Artifacts' },
  { id: 'file', label: 'Workspace' },
  { id: 'finding', label: 'Findings' },
  { id: 'doc', label: 'Documents' },
  // Directly after Documents: a proposal is a candidate for the same corpus
  // that tab lists, one step earlier in its life -- see `MediaProposalPane`'s
  // own docstring for why it is not folded into that tab instead.
  { id: 'media', label: 'Media' },
  { id: 'entity', label: 'Graph' },
  // Directly after Graph, not at the end: the tree is the graph's own material
  // read a second way (a list instead of a drawing), same as Timeline is a
  // second way (ordered by time) -- and the two adjacent readings belong next
  // to each other. Doesn't touch the bundle argument above: nothing in the
  // tree is lazy and nothing in it pulls a canvas, so inserting it here costs
  // nothing and Timeline still closes the list.
  { id: 'tree', label: 'Tree' },
  // Beside Tree, for Tree's own reason: both are list readings of the material
  // the canvas draws, and the two belong next to each other. Nothing here is
  // lazy and nothing pulls a canvas, so it costs the default tab nothing --
  // the same argument Tree makes one line above. What it *did* cost is the
  // narrow band: see `project-stacked.browser.test.tsx`, which predicted this
  // tab before it existed.
  { id: 'ontology', label: 'Classes' },
  // After Graph, not before: this list is ordered by what the reader is asking,
  // and the timeline is a second reading of the graph's own material. Last also
  // keeps it out of the default position, which matters for the same bundle
  // reason `artifact` is default -- `TimelineCanvas` is lazy, and a default of
  // `timeline` would pull it on every project page anybody opened.
  { id: 'timeline', label: 'Timeline' },
]

/** The tab a bare `#/p/<id>` opens. Exported because `App.tsx`'s
 *  `viewNameOf` names the same facet in the interaction log, and a duplicated
 *  literal there would go quietly wrong the day this changes. */
export const DEFAULT_MATERIAL: Facet = 'session'

/** A project, whole: one page with a sidebar and a content area, instead of two
 *  pages.
 *
 * **A frame with mostly-unchanged tenants.** Slice 0 built this as three panes
 * holding the components the two old pages happened to have, unrestyled, on
 * purpose: the container and the regions are two changes and shipping them
 * together leaves no way to tell which half broke. Slice 1 gave QUEUE its header
 * band; slice 2 took the nesting out of HOLDER and gave MATERIAL the workspace;
 * slice 3 rewrote three of MATERIAL's tabs in utilities and threaded their route
 * ids in. The stage list is still the course page's rail and the topic list is
 * still the research page's, both in QUEUE, and neither is MATERIAL's to
 * rewrite — which is also why neither `course.css` nor `research.css` has died
 * yet.
 *
 * **This slice made it two regions rather than three**, and the tenants moved
 * again without being rewritten: HOLDER's four panels are MATERIAL's first tab,
 * in the order and the flex column they already had.
 *
 * A `Split` rather than two divs, still, and the reasons survive the change of
 * shape: `Split` owns the sizing, the fold, the persistence of the fold, the
 * rail form a folded pane takes, and the handoff to the stylesheet below the
 * widest breakpoint. A sidebar needs every one of those. What it does not need
 * is a second fold — MATERIAL passes `collapsible={false}`, which is the one
 * thing this page asks the primitive for that peers never did.
 */
export const ProjectView = ({
  projectId,
  selection,
  seekSeconds = null,
  store,
  onLoaded,
}: {
  projectId: ProjectId
  /** What is selected, owned by the route. Not mirrored into state: the address
   *  bar is the single source of truth, so a reload reproduces the screen and
   *  every selection is sendable. */
  selection: Selection | null
  /** The `doc` route's `?t=`, already parsed and validated by
   *  `parseSeekSeconds` -- `null` for every case that is not a well-formed
   *  non-negative seek, which includes every facet but `doc`. Passed to
   *  `DocumentList` regardless of `selection.facet`: a stale `?t=` left over
   *  from an old link while some other facet is open has nowhere to apply
   *  itself, since `DocumentList` only reads it for the document it opens. */
  seekSeconds?: number | null
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

      <Pane id="material" label="Material" scroll="regions" collapsible={false} showLabel={false}>
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
          //
          // `session` is the arm that cannot go through the cast, because it is
          // the one facet whose `Selection` carries more than an id — an `at`
          // and a `path` the grammar requires. Choosing the tab is not choosing
          // a session to watch, so it writes the *default* selection rather
          // than inventing a scrub point: `null` lands back on this tab through
          // `DEFAULT_MATERIAL`, and the holding session is what the region
          // reads when nothing is explicitly watched. Watching a specific
          // worker still comes from `QueueHeader`, which has a session id to
          // write.
          onValueChange={(next) => {
            // Narrowed before the cast rather than cast to the whole union:
            // `session` is the one arm whose `Selection` carries an `at` and a
            // `path`, so `{ facet, id }` is not a legal selection for it and
            // the compiler says so. The `Exclude` is what keeps that true if a
            // second such facet is ever added.
            if (next === 'session') {
              select(null)
              return
            }
            select({ facet: next as Exclude<MaterialFacet, 'session'>, id: null })
          }}
          className="flex min-h-0 flex-1 flex-col"
        >
          <TabList label="Material" options={MATERIAL_TABS} />

          {/* The old HOLDER region, whole, one level further in.

              `flex min-h-0 flex-col` rather than `overflow-auto`, which is the
              `scroll="regions"` pane body this used to be: the two sections
              inside each own a scroller and split the leftover height between
              them, and a scrolling box here would be a box scrolling around a
              transcript that already scrolls.

              **Still no `Split` and no `Pane` inside it.** Slice 0 mounted
              `SessionView` whole, and `SessionView` is itself a three-pane
              `Split` — a pane header inside a pane header, two collapse groups,
              and a reader who could fold the event log inside a region they
              could also fold. Un-nesting it was right then and is right now;
              the region simply became a tab.

              **`keepMounted`, which is the one thing this panel asks for that
              the other six do not.** `Tabs` unmounts an inactive panel, and for
              a list or a graph that is right — it is what makes manual
              activation mean something. This panel is a live transcript with a
              composer in it, and it was a permanent column until this slice, so
              a half-typed message and a scrub position had never been at risk;
              unmounting discarded both on a trip to Artifacts and back.

              What it costs, plainly: the transcript goes on subscribing behind
              every other tab, and `hidden` is `display: none`, so everything in
              here measures zero while it is away. The second one is the danger
              — `Pane`'s `unmountWhenCollapsed` documents a virtualizer caching
              exactly that zero and coming back empty — and it is why the claim
              that covers this is in `ProjectView.browser.test.tsx` and asserts
              the conversation's height on the way back, not just the draft. */}
          <TabPanel value="session" keepMounted className="flex min-h-0 flex-1 flex-col">
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
                    if (screen.state.scrub.kind === 'historical')
                      screen.forkAt(screen.state.scrub.at)
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
          </TabPanel>

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
              seekSeconds={seekSeconds}
              onOpen={(sourceId) => select({ facet: 'doc', id: sourceId })}
            />
          </TabPanel>

          {/* `overflow-auto` here, unlike `doc` beside it: this panel has no
              virtualizer of its own to own the scroll, and a proposal list
              longer than the pane needs somewhere to scroll or the tail of
              the last need's group runs off the bottom of the page. */}
          <TabPanel value="media" className="min-h-0 flex-1 overflow-auto">
            <MediaProposalPane projectId={projectId} />
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

          <TabPanel value="ontology" className="flex min-h-0 flex-1 flex-col overflow-auto">
            {/* No selection of its own yet: the view shows every class at once
                and there is nothing a URL would usefully single out. The facet
                still carries an `id` slot, because the grammar gives every
                facet one -- it is simply unused here rather than absent. */}
            <OntologyPane projectId={projectId} />
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
