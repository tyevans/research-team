import { useQueryClient } from '@tanstack/react-query'
import { useEffect, useMemo, useRef, useState } from 'react'

import { notify } from '@application/notifications/toast-store.ts'
import { queryKeys } from '@application/queries/keys.ts'
import { createSessionStore, type SessionStore } from '@application/session/session-store.ts'
import type { Course } from '@domain/project/course.ts'
import { AskView } from '@presentation/ask/AskView.tsx'
import { DialogueView } from '@presentation/dialogue/DialogueView.tsx'
import { Shell } from '@presentation/layout/Shell.tsx'
import { DEFAULT_MATERIAL, ProjectView } from '@presentation/project/ProjectView.tsx'
import { homeHref, interactionsHref, type Route } from '@presentation/routing/routes.ts'
import { useRoute, useSeekSeconds } from '@presentation/routing/use-route.ts'
import { InteractionsView } from '@presentation/interactions/InteractionsView.tsx'
import { SessionView } from '@presentation/session/SessionView.tsx'
import { Breadcrumbs } from '@presentation/shell/Breadcrumbs.tsx'
import { ConnectionBadge, DriftBadge } from '@presentation/shell/ConnectionBadge.tsx'
import { DecisionBar } from '@presentation/shell/DecisionBar.tsx'
import { AgentWidget } from '@presentation/agents/AgentWidget.tsx'
import { StreamProvider, useStream } from '@presentation/shell/StreamProvider.tsx'
import { useFrameRefresh } from '@presentation/shell/use-frame-refresh.ts'
import { Toasts } from '@presentation/shell/Toasts.tsx'
import { TreeView } from '@presentation/tree/TreeView.tsx'

import { useContainer } from './container-context.tsx'
import { InteractionLogProvider, useInteractionLog } from './interaction-log-provider.tsx'

export const App = () => (
  <StreamProvider>
    <Console />
  </StreamProvider>
)

/** The view, as the log names it.
 *
 * Derived from the parsed route rather than from `window.location.hash`,
 * because the hash carries ids and `view` is documented as structural. The
 * facet set is closed (`FACETS`), so this cannot grow a value nobody
 * expected.
 *
 * The fallback is `ProjectView`'s own `DEFAULT_MATERIAL`, imported rather than
 * repeated: a bare `#/p/<id>` opens that tab, and a literal `'session'` here
 * would keep saying so silently on the day the default moves. **That day
 * came** -- the default is `catalog` now -- and the import is why nothing had
 * to be found and changed here.
 *
 * What it costs the log, stated because the log is what moved the default and
 * somebody will read it again: `project/catalog` now covers both "arrived on a
 * bare project link" and "chose the Curriculum tab", where those were two
 * different view names before. Rows written from 2026-08-24 onward cannot be
 * compared against earlier ones on entry count, and the same confound that
 * made `project/session`'s 2.3s median hard to read now sits on
 * `project/catalog` instead. Distinguishing them needs a field saying whether
 * the facet was chosen or defaulted, which is not this change's to add.
 *
 * Exported for
 * `App.test.tsx`, which is the only place a route shape can be named without
 * driving the whole console. */
export const viewNameOf = (route: Route): string => {
  if (route.name === 'session') return 'session'
  // The explorer records its own use, and that is the honest arrangement
  // rather than an oversight. Reading the log is an interaction, its dwell
  // rows are real, and nothing filters them out -- so `interactions` will sit
  // near the top of any view count, and the correct reading of that is "the
  // person looking at this was looking at this". Excluding it would mean the
  // one view whose numbers are known to be wrong is the one nobody can check.
  if (route.name === 'interactions') return 'interactions'
  if (route.name !== 'project') return 'home'
  return `project/${route.selection?.facet ?? DEFAULT_MATERIAL}`
}

/** The composition root's own component: routing, the session store, and the
 *  chrome every route shares.
 *
 * Named `Console` rather than `Shell` because `Shell` is now the layout
 * primitive it renders. The old name was the whole reason this file kept its
 * hand-built `<header>`/`<main>` through three slices that migrated everything
 * underneath it -- a local `Shell` in scope makes an unused imported `Shell`
 * invisible, and nothing in a component test can see a missing composition
 * root. `App.test.tsx` is what sees it now. */
const Console = () => {
  const route = useRoute()
  const seekSeconds = useSeekSeconds()
  const stream = useStream()
  const container = useContainer()

  /** One session store for the application, rebuilt only if the container is.
   *
   * At the shell rather than inside `SessionView` because the breadcrumb needs
   * the session's fork origin, and a store the view owned privately would force
   * that fact to be fetched twice. `open()` resets it completely, so switching
   * sessions through it is as clean as a remount. */
  const sessionStore: SessionStore = useMemo(
    () =>
      createSessionStore({
        sessions: container.sessions,
        turns: container.turns,
        now: container.now,
        notify,
      }),
    [container],
  )

  const head = sessionStore((state) => state.head)
  const [course, setCourse] = useState<Course | null>(null)

  useTreeRefresh(route.name === 'home')

  const view = viewNameOf(route)

  return (
    // Above `Shell` rather than inside it: a route change is observed by
    // `useRoute()` once, here, and `dwell.enter(view)` fires from that one
    // observation rather than once per view component underneath.
    <InteractionLogProvider
      sink={container.interactions}
      view={view}
      projectId={route.name === 'project' ? route.id : null}
      sessionId={route.name === 'session' ? route.id : null}
    >
      <Shell
        chrome={
          <>
            <a className="brand" href={homeHref()}>
              <span className="brand-mark" />
              <span className="brand-name">research&#8209;team</span>
            </a>
            {/* Beside the brand rather than in `chrome-right`, and out of the
                breadcrumb's way: the log spans every project and session, so
                it belongs where the things that are true of the whole console
                are, not among the badges that describe the current one.
                Styled as an anchor wearing `.btn` -- the pattern `RunPanel`
                and `WorkerDrawer` already use for a link into a session --
                rather than a class of its own, because no new rule is needed
                for a link that exists everywhere. */}
            <a className="btn btn-ghost btn-sm" href={interactionsHref()}>
              log
            </a>
            <Breadcrumbs
              route={route}
              session={route.name === 'session' ? head : null}
              course={route.name === 'project' ? course : null}
            />
            <div className="chrome-right">
              {/* In the bar rather than floating over the page: as a fixed panel
                  at the lower right it sat on top of whatever was there, and the
                  only way past it was to find its own toggle. Here because "what
                  is running" is not a property of the page you happen to be on --
                  which is the whole reason it exists -- and the chrome is the one
                  piece every route already shares. That sentence is quoted in
                  `Shell.tsx` as the test for what belongs in this slot, so it is
                  the one thing here that is not merely description.

                  Left of the badges: those two describe the connection, this
                  describes the work, and the connection is the thing you look for
                  when the work stops making sense -- so it stays at the edge where
                  it has always been rather than being pushed along. */}
              <AgentWidget />
              <DriftBadge />
              <ConnectionBadge state={stream.connection} />
            </div>
          </>
        }
      >
        {/* Inside the surface rather than beside it, which is a change of parent
            and not of position: `.toasts` is `position: fixed`, so it is placed
            against the viewport wherever it is mounted, and `Shell` takes
            children for the surface alone. It stays outside the overlay host on
            purpose -- argued where `--z-toast` is declared. */}
        <Toasts />
        {/* Renders nothing; see its own comment for why this lives here
            rather than in `application/`. */}
        <ProjectSwitchLog projectId={route.name === 'project' ? route.id : null} />
        {/* Above the route's content and inside the surface, on every page.
            A gated call blocks an agent until a person answers it, and the
            person is wherever they happen to be — which is why this is one bar
            in the shell rather than the three per-session call sites it
            replaces. It renders nothing when nothing is pending. */}
        <DecisionBar />
        <CurrentView
          route={route}
          seekSeconds={seekSeconds}
          store={sessionStore}
          onCourse={setCourse}
        />
      </Shell>
    </InteractionLogProvider>
  )
}

/** Records `ProjectSwitched` when the route's project id changes.
 *
 * A component of its own, rendered inside `InteractionLogProvider` rather
 * than logic inlined in `Console`, for one reason that is not optional:
 * `Console` is what *renders* the provider, so a hook called at `Console`'s
 * own level would read the outer (silent) default context, one level above
 * where the real emitter is provided. This has to be a child of the
 * provider to see it at all.
 *
 * Left in `app/` rather than moved to `application/`, unlike every other
 * emission site: it exists only to observe a route transition, which is
 * `useRoute()`'s own concern and has no domain vocabulary of its own the way
 * a mutation's `onSuccess` or a store's `search()` does. `DecisionBar`'s
 * approval handler is the other named exception, for the same shape of
 * reason -- the seam is where the UI event becomes known, not where a
 * generic "the route changed" statement could be phrased.
 */
const ProjectSwitchLog = ({ projectId }: { projectId: string | null }) => {
  const log = useInteractionLog()
  const previous = useRef<string | null>(null)

  useEffect(() => {
    if (projectId !== null && projectId !== previous.current) {
      log.record('ProjectSwitched', {
        to_project_id: projectId,
        from_project_id: previous.current,
      })
    }
    previous.current = projectId
  }, [projectId, log])

  return null
}

const CurrentView = ({
  route,
  seekSeconds,
  store,
  onCourse,
}: {
  route: Route
  /** The `doc` route's own `?t=`, threaded down rather than re-read: it comes
   *  from the same hash `route` was parsed from, and reading it twice (once
   *  here, once lower) would be two parses of one URL that could disagree if
   *  the hash changed between them. `ProjectView` is the only branch that has
   *  anywhere to put it -- see its own prop for where it lands. */
  seekSeconds: number | null
  store: SessionStore
  onCourse: (course: Course | null) => void
}) => {
  if (route.name === 'session') {
    return <SessionView store={store} sessionId={route.id} at={route.at} path={route.path} />
  }
  // Ahead of the `!== 'project'` fallthrough below, which answers `TreeView`
  // for every route it does not recognise. A view added after that line is a
  // view nobody reaches.
  if (route.name === 'interactions') return <InteractionsView />
  if (route.name !== 'project') return <TreeView />

  const { id, selection } = route

  // Ahead of the project page rather than inside it, and the last arm of the
  // old dispatch left standing: ask is one conversation with no parts worth a
  // URL and nothing to read it against, so it is a view rather than a region.
  // `ProjectView.regionOf` maps it anyway, and says why.
  if (selection?.facet === 'ask') return <AskView key={id} projectId={id} />

  // Intercepted for `ask`'s reason -- a dialogue is one conversation with no
  // parts worth a URL segment beyond its own id, so it is a view rather than a
  // region.
  //
  // The id is a PROP now, not part of the `key`, and the difference is what
  // makes a dialogue resumable. Keyed on it, the view remounted the instant it
  // navigated to its own freshly minted id -- discarding the transcript that
  // had just streamed. `DialogueView` rebuilds its own store when the URL
  // names a dialogue it is not already on, which is the case the old key was
  // reaching for (`switching dialogues must not inherit the first's
  // transcript`) without the self-navigation collateral.
  if (selection?.facet === 'dialogue') {
    return <DialogueView key={id} projectId={id} dialogueId={selection.id} />
  }

  // Unconditional, which is the whole of what this slice changed here. The
  // branch that stood between the two facet sets, and the `RESEARCH_FACETS`
  // table that fed it, are gone -- the comment on that table named this change
  // as the one that would delete it. Every facet now reaches a region rather
  // than three of them landing on a page that reads none.
  return (
    <ProjectView
      key={id}
      projectId={id}
      selection={selection}
      seekSeconds={seekSeconds}
      store={store}
      onLoaded={onCourse}
    />
  )
}

/** The tree is a projection of every session, so any log frame can change it.
 *
 * Only while the tree is on screen: a session view has its own, finer-grained
 * subscription and does not want this one's refetches. The debounce, and why
 * there is one, now lives in `useFrameRefresh` -- shared with the research
 * page's topic list, which needs the same "the log moved, re-read" and had
 * none, which is why a seeded topic sat invisible until a reload. */
const useTreeRefresh = (active: boolean) => {
  const queryClient = useQueryClient()

  useFrameRefresh(
    active,
    (frame) => frame.kind === 'log',
    () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.tree() })
      void queryClient.invalidateQueries({ queryKey: queryKeys.sessions() })
      // The landing page's live markers, refreshed off the same frames
      // rather than off a timer of their own. A run's rounds *are* turns on
      // a session, so the frames that move the counts are the frames that
      // move the marker -- and a poll would be a request per interval on a
      // page a reader leaves open.
      //
      // `allWorkers()` is what keeps the markers fresh now that they read the
      // *global* roster: `queryKeys.runningAgents()` is `['workers','all']`,
      // under this prefix. That is the landing page owning its own freshness
      // rather than borrowing the dock's, and it costs no second subscription
      // because this one is already here and already gated on the route.
      // `ProjectActivity.test.tsx` fails if that nesting is broken.
      // `allRuns()` survives for `RunPanel`, not for this page.
      void queryClient.invalidateQueries({ queryKey: queryKeys.allRuns() })
      void queryClient.invalidateQueries({ queryKey: queryKeys.allWorkers() })
    },
  )
}
