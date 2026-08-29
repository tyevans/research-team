import { useCallback } from 'react'

import type { SessionStore } from '@application/session/session-store.ts'
import { ScrubPoint } from '@domain/session/scrub-point.ts'
import type { FilePath } from '@domain/shared/file-path.ts'
import { SourceId, type ProjectId, type SessionId } from '@domain/shared/identifier.ts'

import { EmptyState } from '../common/primitives.tsx'
import { TabList, TabPanel, Tabs } from '../common/Tabs.tsx'
import { useProject } from './use-project.ts'
import { DocumentList } from '../research/DocumentList.tsx'
import { CatalogPane } from '../curriculum/CatalogPane.tsx'
import { CoursePage } from '../curriculum/CoursePage.tsx'
import { CurriculumPane } from '../curriculum/CurriculumPane.tsx'
import { OntologyPane } from '../research/OntologyPane.tsx'
import { EntityTreePane } from '../research/EntityTreePane.tsx'
import { GraphPane } from '../research/GraphPane.tsx'
import { MediaProposalPane } from '../research/MediaProposalPane.tsx'
import { TimelinePane } from '../research/TimelinePane.tsx'
import { projectHref, sessionSelection, type Facet, type Selection } from '../routing/routes.ts'
import { navigate } from '../routing/use-route.ts'
import { WorkspacePanel } from '../session/panels.tsx'
import { useSessionScreen } from '../session/use-session-screen.ts'

/** The two regions a project page has: a sidebar and the content beside it.
 *
 * Named for what they answer rather than for what they contain, which is the
 * argument for the merge in one line: QUEUE is "what is there to do" and
 * MATERIAL is "what has come of it". The two pages this replaces cut across
 * both — the course page held stages (QUEUE) and artifacts (MATERIAL); the
 * research page held topics (QUEUE) and documents and a graph (MATERIAL) — so a
 * reader following one thread crossed a route boundary to do it. The stages and
 * the artifacts are gone with the workflow system; the split they motivated is
 * not, because the research half made the same cut.
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
    // QUEUE is the questions this project still owes an answer to. It used to
    // be that plus a stage rail, on the argument that a stage and a topic are
    // both work items; the rail was the half that was never alive (measured
    // 2026-08-27 against the real database: zero workflow events of any kind,
    // against 64 topics across six projects), so what is left is not a
    // diminished pane but the honest one.
    //
    // `dialogue` joins `ask` at the end of this group for the same reason and
    // with the same caveat: `App.tsx` intercepts both above this view, so
    // neither is drawn by a region. The map is total over `Facet`, so they
    // have to be somewhere, and "what is there to do" is where a conversation
    // belongs. (The comment lives up here rather than beside those two cases
    // because `no-fallthrough` defaults to `allowEmptyCase: false`, and a
    // comment between empty cases reads to it as a fallthrough.)
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
    case 'area':
    case 'path':
    case 'catalog':
    case 'course':
    case 'entity':
    case 'timeline':
    case 'tree':
    case 'ontology':
    case 'doc':
    case 'media':
      return 'material'
  }
}

/** Which facets MATERIAL offers, in the order it offers them.
 *
 * **Order and default came apart, and this docstring used to assume they were
 * one decision.** It read "the default tab is loaded on every project page, so
 * what sits first is a bundle decision" — still true of the bundle, no
 * longer true of the position. `DEFAULT_MATERIAL` is `catalog` now, which is
 * the *last* tab's default reading, so first place is a reading-order decision
 * and the bundle argument moved to `DEFAULT_MATERIAL`'s own docstring, where
 * the choice is actually made.
 *
 * The bundle argument itself survives and still shapes this list: `GraphCanvas`
 * is `React.lazy` over ~60 kB of `react-force-graph-2d` and `TimelineCanvas` is
 * lazy too, so neither may be the default. What changed is that sitting last no
 * longer achieves that on its own — the default is a named facet, and it is
 * the only thing now keeping either canvas off a cold project page. Checked
 * rather than assumed when the session took first place — `npm run size`:
 * app 75.1 kB of 80.
 *
 * **Workspace is second, and what used to argue for that position is gone.**
 * The argument was an adjacency: Artifacts sat first of the pair because an
 * artifact was what a stage declared it produced and the workspace is the tree
 * those declarations were made *of*, so a reader checking a declaration against
 * the files moved one tab. Artifacts is deleted with the workflow system and the
 * adjacency has nothing to be adjacent to. What survives is the workspace on its
 * own terms: it is the only tab showing this project live and at any scrub
 * point, and everything after it is material that arrived from outside.
 */
type MaterialFacet = 'file' | 'doc' | 'media' | 'entity' | 'tree' | 'ontology' | 'timeline' | 'area'

/** Exported so a measurement of the rendered strip can be compared against the
 *  strip that was declared — a count taken from the rendered row alone cannot
 *  tell "eight tabs" from "eight of nine rendered".
 *
 * `project-tracks.browser.test.tsx` was that measurement and is deleted with
 * the split it took its floor from: the floors it held were widths at which
 * *two* regions still fit, and this page has one. The strip's own overflow
 * behaviour is unchanged — `.tabs` scrolls — so a twelfth tab is still
 * reachable rather than painted-and-unclickable, which is the failure the
 * floors existed to keep away. Nothing measures the strip's width now, and
 * that is a real gap rather than a tidy-up. */
export const MATERIAL_TABS: readonly { id: MaterialFacet; label: string }[] = [
  // **"Holding session" was first and is gone.** Not demoted -- removed. A
  // person does not choose which session to read a project through: the
  // reading head answers that, and it answers it whether or not anybody is
  // holding. What the tab actually offered was a transcript, a scrub bar, an
  // event log and a composer, which is a whole session view standing as a peer
  // of Curriculum and Graph in a strip of things to *look at*. The session
  // route is where somebody studying a run goes, and it still is.
  //
  // The measurement that started it: 118 entries -- the second most-entered
  // view in the product -- at a 2.3s median with 55% bouncing under three
  // seconds. That was read as a bad *default* when the default moved to
  // `catalog` (#286), and deliberately not read as a bad tab, because dwell
  // measures what readers were handed rather than what they would pick. It is
  // read as neither here: the tab is not losing a competition for a place in
  // the strip, it is answering a question a reader was never asking.
  //
  // First now, and the promotion is not a claim about attention: this is the
  // only tab showing the project's own files, and everything after it is
  // material that arrived from outside. Nothing in it is lazy, so the bundle
  // argument in this list's docstring is untouched by the move.
  { id: 'file', label: 'Workspace' },
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
  // narrow band, back when this page stacked two panes below 821 -- measured
  // by `project-stacked.browser.test.tsx`, deleted with the split.
  { id: 'ontology', label: 'Classes' },
  // After Graph, not before: this list is ordered by what the reader is asking,
  // and the timeline is a second reading of the graph's own material. Last also
  // keeps it out of the default position, which matters for the same bundle
  // reason `DEFAULT_MATERIAL` is not a canvas -- `TimelineCanvas` is lazy, and a
  // default of `timeline` would pull it on every project page anybody opened.
  { id: 'timeline', label: 'Timeline' },
  // **One tab for two facets**, and the second one is deliberately not here.
  //
  // `area` and `path` are two readings of one response -- what the project is
  // about, and what order to take it in -- and the pane switches between them
  // with a toggle of its own. Two tabs was the first arrangement and it broke
  // the strip: MATERIAL's floor measured 646px against 837px of tabs, and two
  // controls clipped in the narrow band. Eleven tabs is where this strip
  // stopped fitting *beside a sidebar*, which is worth knowing before the
  // twelfth is added -- though the sidebar is gone and both measurements were
  // taken by browser tests that went with it.
  //
  // Nine now, since Artifacts and Findings came out with the workflow system.
  // That is about 150px of headroom and it is deliberately unspent: what to put
  // in it is an information-architecture decision (splitting `course` out of
  // this tab is the standing candidate) and not something to settle inside a
  // deletion.
  //
  // Last for the bundle reason the graph tabs are last, and deliberately
  // *after* Timeline rather than beside Graph: an area is a fold over the same
  // material the four readings above draw, so a reader who has not looked at
  // the graph has nothing to check it against.
  //
  // The tab id stayed `area` rather than becoming `catalog` when the catalog
  // became this tab's default: the id is what `MaterialFacet`, `regionOf` and
  // the tab strip's `value` compare against, and the catalog is reached by
  // *not* carrying `area` or `path` on the selection (see `materialTab` in
  // `ProjectView`) rather than by a tab id of its own.
  { id: 'area', label: 'Curriculum' },
]

/** Which tabs the strip offers, given what this project actually has.
 *
 * **A tab whose panel can only say "there is nothing here" is worse than no
 * tab**, because a reader cannot tell it apart from one that might have
 * something until they have spent the click. Measured over
 * `~/.research-team/interactions.db` on 2026-08-23 (2,476 events): Workspace
 * took 14 entries at a 0.7s median and **100% bounce** — every single visit
 * under three seconds. That is not readers finding a page thin; it is what
 * arriving at an `EmptyState` and leaving looks like in aggregate. The same
 * measurement covered Artifacts and Findings, which is the argument that
 * deleted them; it is in this commit's message, because the code that held it
 * went with them.
 *
 * **The condition moved with its data source, which is the only honest way to
 * widen it.** It was `hasSession` — is somebody holding this project — on the
 * argument that "a project's files belong to the session holding it". That was
 * true of where the tab read from, not of the project: a released project has
 * files, and the tab hid them. It is `hasWorkspace` now, meaning the reading
 * head resolves to a session, and the panel behind it folds files out of that
 * same session. Widening `hasSession` on its own would have produced a tab that
 * is present and still empty — which is exactly the defect the 100% bounce
 * condemned, with the gate removed instead of the cause.
 *
 * The tab still hides, and it still should: a project nothing has ever been
 * written in resolves no reading head and has nothing to show. The second
 * condition was `hasCourse` and it went with the course query.
 *
 * **A tab the route explicitly names is always offered**, whatever the
 * condition says. `#/p/<id>/file/<path>` is a link somebody sent, and the
 * alternatives are both worse than a tab reading "No workspace yet.": dropping
 * the tab leaves Radix with a selected value no trigger carries, so the strip
 * shows nothing chosen while a panel is open below it; and redirecting would
 * swallow the link. `openTab` is that facet already mapped through
 * `materialTab`, so a `catalog` selection compares as `area` here.
 *
 * **A function for one predicate, deliberately.** It reads as over-built and
 * somebody will want to inline it. The deep-link exemption is the reason not
 * to: it is non-obvious, its failure is silent (a strip with nothing selected
 * over an open panel), and it gets re-derived wrong. It is also the seam the
 * next conditional tab goes in.
 */
export const visibleMaterialTabs = (
  { hasWorkspace }: { hasWorkspace: boolean },
  openTab: Facet,
): readonly { id: MaterialFacet; label: string }[] =>
  MATERIAL_TABS.filter((tab) => {
    if (tab.id === openTab) return true
    if (tab.id === 'file') return hasWorkspace
    return true
  })

/** The tab a bare `#/p/<id>` opens. Exported because `App.tsx`'s
 *  `viewNameOf` names the same facet in the interaction log, and a duplicated
 *  literal there would go quietly wrong the day this changes.
 *
 * **`catalog` rather than `session`, and this is a measurement overturning the
 * argument two comments above it.** `MATERIAL_TABS` says the holding session
 * is first because "it is what the page is about: a reader opening a project is
 * asking what is happening to it". Gross dwell over the real interaction log on
 * 2026-08-23 says readers disagree: `project/session` took **118 entries — the
 * second most-entered view in the product — at a 2.3s median with 55% bouncing
 * under three seconds**. Most of those entries are not a choice; it is the
 * default tab, so they are arrivals followed by departures. Against it,
 * `project/catalog` took 82 entries at a 20.6s median and **14% bounce, the
 * lowest of any view measured**.
 *
 * **The graph was the other candidate and was rejected on two grounds.** It
 * holds more raw attention (209 entries, 42.2s median) — but `MATERIAL_TABS`'s
 * own opening paragraph is the deciding argument: `GraphCanvas` is
 * `React.lazy` over ~60 kB of `react-force-graph-2d`, and the default tab is
 * loaded on every project page anybody opens, so defaulting to it would pull
 * that chunk for every reader including the ones who came to read a course.
 * The second ground is what the two views are for: the graph is a tool a
 * reader reaches for with a question already in hand, and its dwell is the
 * dwell of people who chose it. `CatalogPane` is statically imported and costs
 * the first paint nothing.
 *
 * **Unconditional, deliberately.** The obvious worry is a project with nothing
 * extracted landing on a blank page, and it was checked rather than assumed:
 * `CatalogPane`'s empty branch renders the blurb and art sweep controls above a
 * `role="status"` line that names how many candidates are waiting — an empty
 * catalog is the one screen that tells a reader what to press. A default that
 * changed with the project's state would be harder to reason about than this
 * one, and there is nothing here to buy with it.
 *
 * This is a `Facet` with no tab of its own — `catalog` is the Curriculum tab's
 * default reading — so `materialTab` below maps it, exactly as it maps a
 * `catalog` selection that arrives from the route. */
export const DEFAULT_MATERIAL: Facet = 'catalog'

/** A project, whole: one page, instead of two.
 *
 * **A frame with mostly-unchanged tenants.** Slice 0 built this as three panes
 * holding the components the two old pages happened to have, unrestyled, on
 * purpose: the container and the regions are two changes and shipping them
 * together leaves no way to tell which half broke. Slice 1 gave QUEUE its
 * header band; slice 2 took the nesting out of HOLDER and gave MATERIAL the
 * workspace; slice 3 rewrote three of MATERIAL's tabs in utilities and
 * threaded their route ids in.
 *
 * **There is one region now, and this is the second of the two that left.**
 * HOLDER became a tab in MATERIAL; QUEUE has become a drawer in the console's
 * chrome, which `TopicControls` argues in full. `Split` went with it -- what a
 * split buys is sizing, folding, the persistence of a fold and a stacked
 * fallback below `--bp-narrow`, and every one of those is an answer about how
 * *two* regions share a surface.
 *
 * `regionOf` below still names both, and deliberately: `queue` no longer means
 * "the left column of this page", it means "drawn by the chrome rather than by
 * this view", which is a distinction the tab resolution below still has to
 * make.
 */
export const ProjectView = ({
  projectId,
  selection,
  seekSeconds = null,
  store,
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
}) => {
  // The breadcrumb used to be told the name from here, through an `onLoaded`
  // the shell held in state. It reads `useCrumbProjectName` off the route
  // instead: the settings page is about a project and mounts no project view,
  // so a name pushed up from this component could never reach it. Both readers
  // share `queryKeys.project`, so nothing here fetches twice.
  const { readingHeadSessionId } = useProject(projectId)

  const watching: SessionId | null = selection?.facet === 'session' ? selection.id : null

  /** Whose files this page is reading: an explicitly named session, the
   *  project's **reading head** as the default, or neither.
   *
   * **This was `holdingSessionId` and the change is the point of the slice.**
   * The holder answers "who is driving"; the reading head answers "what is
   * there to read", and the second question has an answer whether or not
   * anybody is holding. Resolved off the holder, the Workspace tab was empty
   * for every project between sessions — which is what the 100% bounce
   * `visibleMaterialTabs` records was measuring, and why that tab was hidden
   * rather than fixed.
   *
   * `null` is still a real state — a project nothing has ever been written in
   * — and it is still why the screen hook below takes a nullable id rather
   * than being called from inside a branch. */
  const sessionId: SessionId | null = watching ?? readingHeadSessionId

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
   * `doc`, `artifact` and `finding` all parsed an id, landed on `selection` and
   * reached the right region — and were then mounted with `projectId` alone,
   * each component holding its open item in its own `useState`. Four linkable
   * states that opened the right tab and forgot what the link was about, and one
   * of them was a shipped broken link: `CitationList` writes
   * `#/p/<id>/doc/<sourceId>` and following it produced an unfiltered corpus.
   * Two of the four are deleted now; the defect and its fix were general.
   *
   * Two literal comparisons rather than one helper taking a facet: comparing
   * against a *variable* narrows nothing, so `selection.id` would still be the
   * union of every facet's id type — including `FilePath`, which is an object
   * and would reach a row as `[object Object]` through any `String()` that
   * silenced the type error.
   */
  const openDoc =
    selection?.facet === 'doc' && selection.id !== null ? SourceId(selection.id) : null
  /** The facet the tab strip is showing, which is the route's when the route
   *  names one this region draws and `DEFAULT_MATERIAL`'s otherwise.
   *
   * Resolved *before* the mapping below rather than inside its last arm, which
   * is the change that lets the default be a facet with no tab. `catalog` is
   * one, and it reaches `'area'` through the same arm a `catalog` selection
   * from the route does — one mapping for both, instead of a default that has
   * to be a tab id and a route facet that does not. */
  /** What this project has, which decides which tabs are offered. Read here
   *  rather than inside the strip so the condition sits beside the value that
   *  answers it -- `sessionId` is already resolved above, and it is the
   *  reading head now rather than the holder, which is what makes the gate
   *  mean "there is a workspace" rather than "somebody is holding this". */
  const has = { hasWorkspace: sessionId !== null }

  const openFacet: Facet =
    selection && regionOf(selection.facet) === 'material' ? selection.facet : DEFAULT_MATERIAL

  const materialTab: Facet =
    // **`session` is a facet with no tab, and it maps to Workspace.** It had
    // one until this slice, and the arm here was narrower: only a session
    // selection *carrying a path* was a workspace selection, because a bare
    // one meant "watch this transcript". There is no transcript on this page
    // now, so every `session` selection is a workspace one — which includes
    // the scrub-with-no-file-open that `href` above writes, and which would
    // otherwise resolve to a tab that no longer exists and select nothing.
    openFacet === 'session'
      ? 'file'
      : // `path`, `catalog` and `course` are facets with no tab of their own:
        // all three are readings of the Curriculum tab, chosen by a toggle
        // (or a card) inside the pane rather than by the strip. Mapped here
        // rather than given a tab because eleven tabs is where the strip
        // stops fitting -- see `MATERIAL_TABS`.
        openFacet === 'path' || openFacet === 'catalog' || openFacet === 'course'
        ? 'area'
        : openFacet

  /** Replaced, never pushed: a selection on this page is a glance, and forty
   *  glances in the back stack make the back button useless.
   *
   *  This took a `replace` flag until the roster left the page. Its one caller
   *  passing `false` was the worker row — opening a worker's transcript was a
   *  destination rather than a glance, and worth a back-button entry. The dock
   *  opens a worker in a drawer and writes no URL, so there is no longer a
   *  selection on this page that is a destination, and a flag with one legal
   *  value is a decision nobody is making. */
  const select = (next: Selection | null) => {
    navigate(projectHref(projectId, next), { replace: true })
  }

  return (
    /* One region rather than a `Split`, and the sidebar it lost is the point
       of the change. MATERIAL was `1fr` beside a quarter-width QUEUE that held
       the topic list; the list is in the chrome's drawer now (`TopicControls`
       carries why), so there is nothing to split with. `Split` owned the
       sizing, the fold, the persistence of that fold and the stacked shape
       below `--bp-narrow` -- all four are answers to "how do two regions share
       a surface", and none of them has a question here any more.

       A plain flex column rather than a `Pane`: `Pane` draws a label, a fold
       control and a `meta` line, and this one was already passing
       `collapsible={false}` and `showLabel={false}` to turn two of the three
       off. What is left of it is `scroll="regions"`, which is the flex column
       below said in a prop. */
    <div className="flex h-full min-h-0 flex-col">
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
        // **There used to be an arm above this one, and it broke silently.**
        // Clicking "Holding session" wrote `select(null)`, on the argument
        // that `null` lands back on that tab through `DEFAULT_MATERIAL` --
        // true while the default was `session`. The default moved to
        // `catalog` (#286) and this arm did not move with it, so the tab
        // bounced its own readers to Curriculum for a whole slice. Nothing
        // caught it, because the only file that clicked this tab was in the
        // browser project, outside CI.
        //
        // The tab is gone now and so is the arm, but the lesson is not: the
        // assertions that would have caught it -- what a click selects, and
        // which panel renders after it -- are jsdom's to make and now live
        // in `ProjectView.test.tsx`, in CI. `session` is still a *facet*
        // (`href` writes it for every scrub and file open) and it maps to
        // the Workspace tab through `materialTab` above; no click here
        // produces one, so no arm here handles one.
        onValueChange={(next) => {
          // The Curriculum tab opens on the catalog, not the area map --
          // `catalog` is its default reading (see `routes.ts`'s `FACETS`
          // comment), and `area`/`path` are reached from inside the pane.
          // Writing `area` here would reopen the analytic map on every
          // click of a tab whose declared default has moved.
          if (next === 'area') {
            select({ facet: 'catalog', id: null })
            return
          }
          select({ facet: next as MaterialFacet, id: null })
        }}
        className="flex min-h-0 flex-1 flex-col"
      >
        {/* The declared strip, filtered by what this project has — see
              `visibleMaterialTabs` for the measurement and for why a tab the
              route names is offered regardless. The `TabPanel`s below are all
              still rendered: hiding a trigger is what this does, and a panel
              removed with it would break the deep links that keep their
              triggers. */}
        <TabList label="Material" options={visibleMaterialTabs(has, materialTab)} />

        {/* No `overflow-auto`, for the same reason the document list has
              none: `WorkspacePanel` is a file list over a file viewer, each
              scrolling on its own — `workspace.css` gives `.files` its own
              `overflow: auto` and a 34% cap, and `.file-view` the rest. This
              panel is the flex column those two are sized against, which is
              exactly what the `scroll="regions"` pane body was on `#/s/`. */}
        <TabPanel value="file" className="flex min-h-0 flex-1 flex-col">
          {sessionId === null ? (
            // A blank panel reads as a load that failed rather than as an
            // absence, so the empty state says which one it is.
            //
            // **The sentence changed with the condition.** It used to read
            // "A project's files belong to the session holding it. Join the
            // project and its tree appears here." -- which was accurate
            // about where the bytes came from and wrong about the project:
            // a released project has files, and a reader was told to join
            // to see files that were already there. This branch is now only
            // reached by a project nothing has ever been written in, and
            // that is what it says.
            <EmptyState
              heading="Nothing has been written here yet."
              detail="This project has no files. Start a session in it, and everything it writes appears here."
            />
          ) : (
            <WorkspacePanel screen={screen} sessionId={sessionId} openPath={openPath} />
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

        <TabPanel value="area" className="flex min-h-0 flex-1 flex-col">
          {/* Four readings behind one tab, chosen by the facet: the
                catalog (default), the two analytic readings `area`/`path`
                that `CurriculumPane` already draws, and one candidate's own
                course page. `catalog` and `course` are their own components
                and their own fetches -- see `CatalogPane`'s and
                `CoursePage`'s own docstrings for why folding either response
                shape into `CurriculumPane` would be the wrong seam. */}
          {selection?.facet === 'area' || selection?.facet === 'path' ? (
            <CurriculumPane
              projectId={projectId}
              reading={selection.facet === 'path' ? 'path' : 'areas'}
              selected={selection.id ?? null}
              onReading={(reading) =>
                select({ facet: reading === 'path' ? 'path' : 'area', id: null })
              }
            />
          ) : selection?.facet === 'course' && selection.id !== null ? (
            <CoursePage
              projectId={projectId}
              slug={selection.id}
              onBack={() => select({ facet: 'catalog', id: null })}
            />
          ) : (
            <CatalogPane
              projectId={projectId}
              categoryKey={selection?.facet === 'catalog' ? (selection.id ?? null) : null}
              onCategory={(key) => select({ facet: 'catalog', id: key })}
              onCourse={(slug) => select({ facet: 'course', id: slug })}
            />
          )}
        </TabPanel>

        <TabPanel value="timeline" className="flex min-h-0 flex-1 flex-col">
          <TimelinePane
            projectId={projectId}
            entity={selection?.facet === 'timeline' ? (selection.id ?? null) : null}
            onEntity={(entity) => select({ facet: 'timeline', id: entity })}
          />
        </TabPanel>
      </Tabs>
    </div>
  )
}
