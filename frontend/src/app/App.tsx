import { useQueryClient } from '@tanstack/react-query'
import { useMemo, useState } from 'react'

import { notify } from '@application/notifications/toast-store.ts'
import { queryKeys } from '@application/queries/keys.ts'
import { createSessionStore, type SessionStore } from '@application/session/session-store.ts'
import type { Course } from '@domain/project/course.ts'
import { AskView } from '@presentation/ask/AskView.tsx'
import { CourseView } from '@presentation/course/CourseView.tsx'
import { Shell } from '@presentation/layout/Shell.tsx'
import {
  homeHref,
  projectHref,
  sessionSelection,
  type Route,
  type Selection,
} from '@presentation/routing/routes.ts'
import { navigate, useRoute } from '@presentation/routing/use-route.ts'
import { ResearchView } from '@presentation/research/ResearchView.tsx'
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

export const App = () => (
  <StreamProvider>
    <Console />
  </StreamProvider>
)

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

  return (
    <Shell
      chrome={
        <>
          <a className="brand" href={homeHref()}>
            <span className="brand-mark" />
            <span className="brand-name">research&#8209;team</span>
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
      {/* Above the route's content and inside the surface, on every page.
          A gated call blocks an agent until a person answers it, and the
          person is wherever they happen to be — which is why this is one bar
          in the shell rather than the three per-session call sites it
          replaces. It renders nothing when nothing is pending. */}
      <DecisionBar />
      <CurrentView route={route} store={sessionStore} onCourse={setCourse} />
    </Shell>
  )
}

const CurrentView = ({
  route,
  store,
  onCourse,
}: {
  route: Route
  store: SessionStore
  onCourse: (course: Course | null) => void
}) => {
  if (route.name === 'session') {
    return <SessionView store={store} sessionId={route.id} at={route.at} path={route.path} />
  }
  if (route.name !== 'project') return <TreeView />

  const { id, selection } = route

  if (selection !== null && RESEARCH_FACETS.has(selection.facet)) {
    return (
      <ResearchView
        key={id}
        projectId={id}
        entity={
          selection.facet === 'entity' && typeof selection.id === 'string' ? selection.id : null
        }
        // Replaced rather than pushed, for the reason scrubbing replaces.
        // Browsing a graph also *grows* it -- every selection pulls in a
        // neighbourhood -- so a back button that restored the previous
        // entity could not also un-draw what that click added. It would
        // return a URL describing a smaller graph than the one on screen,
        // which is worse than not offering the step back at all.
        onEntity={(entity) =>
          navigate(projectHref(id, { facet: 'entity', id: entity }), { replace: true })
        }
      />
    )
  }

  // Before the course fallthrough, and not in `RESEARCH_FACETS`: ask is its
  // own view, not a facet the research page answers.
  if (selection?.facet === 'ask') return <AskView key={id} projectId={id} />

  const openStage = selection?.facet === 'stage' ? (selection.id ?? null) : null

  return (
    <CourseView
      key={id}
      projectId={id}
      onLoaded={onCourse}
      watching={selection?.facet === 'session' ? selection.id : null}
      onWatch={(sessionId) => navigate(projectHref(id, sessionSelection(sessionId)))}
      openStage={openStage}
      onToggleStage={(stageId) =>
        // Replaced rather than pushed, for the reason the graph's selection is:
        // opening a stage is a glance, and forty glances in the back stack make
        // the back button useless. Replacing keeps it linkable without that
        // cost -- which is the objection `useCourse` raised against routing
        // this at all, and it is answered rather than ignored.
        navigate(projectHref(id, openStage === stageId ? null : { facet: 'stage', id: stageId }), {
          replace: true,
        })
      }
    />
  )
}

/** Which facets the research view answers, until the two views merge.
 *
 * A dispatch table rather than a `switch` with two arms because it is a
 * *temporary* fact -- §3.2 of the proposal deletes both views into one page,
 * and at that point this set and the branch it feeds both go. Facets outside it
 * land on the course view, including the three (`file`, `artifact`, `finding`)
 * that no view reads yet: they parse and they are linkable, and the region that
 * renders them is a later slice.
 */
const RESEARCH_FACETS: ReadonlySet<Selection['facet']> = new Set(['entity', 'topic', 'doc'])

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
      // move the marker -- and a poll would be N more requests per interval
      // on a page that already asks two per drawn row.
      void queryClient.invalidateQueries({ queryKey: queryKeys.allRuns() })
      void queryClient.invalidateQueries({ queryKey: queryKeys.allWorkers() })
    },
  )
}
