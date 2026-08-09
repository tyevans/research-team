import { useQueryClient } from '@tanstack/react-query'
import { useMemo, useState } from 'react'

import { notify } from '@application/notifications/toast-store.ts'
import { queryKeys } from '@application/queries/keys.ts'
import { createSessionStore, type SessionStore } from '@application/session/session-store.ts'
import type { Course } from '@domain/project/course.ts'
import { CourseView } from '@presentation/course/CourseView.tsx'
import { courseHref, researchHref, homeHref, type Route } from '@presentation/routing/routes.ts'
import { navigate, useRoute } from '@presentation/routing/use-route.ts'
import { ResearchView } from '@presentation/research/ResearchView.tsx'
import { SessionView } from '@presentation/session/SessionView.tsx'
import { Breadcrumbs } from '@presentation/shell/Breadcrumbs.tsx'
import { ConnectionBadge, DriftBadge } from '@presentation/shell/ConnectionBadge.tsx'
import { StreamProvider, useStream } from '@presentation/shell/StreamProvider.tsx'
import { useFrameRefresh } from '@presentation/shell/use-frame-refresh.ts'
import { Toasts } from '@presentation/shell/Toasts.tsx'
import { TreeView } from '@presentation/tree/TreeView.tsx'

import { useContainer } from './container-context.tsx'

export const App = () => (
  <StreamProvider>
    <Shell />
  </StreamProvider>
)

const Shell = () => {
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
        approvals: container.approvals,
        now: container.now,
        notify,
      }),
    [container],
  )

  const head = sessionStore((state) => state.head)
  const [course, setCourse] = useState<Course | null>(null)

  useTreeRefresh(route.name === 'home')

  return (
    <>
      <header className="topbar">
        <a className="brand" href={homeHref()}>
          <span className="brand-mark" />
          <span className="brand-name">research&#8209;team</span>
        </a>
        <Breadcrumbs
          route={route}
          session={route.name === 'session' ? head : null}
          course={route.name === 'course' || route.name === 'research' ? course : null}
        />
        <div className="topbar-right">
          <DriftBadge />
          <ConnectionBadge state={stream.connection} />
        </div>
      </header>

      <Toasts />

      <main id="app">
        <CurrentView route={route} store={sessionStore} onCourse={setCourse} />
      </main>
    </>
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
  switch (route.name) {
    case 'session':
      return <SessionView store={store} sessionId={route.id} at={route.at} path={route.path} />
    case 'course':
      return (
        <CourseView
          key={route.id}
          projectId={route.id}
          onLoaded={onCourse}
          watching={route.watching}
          onWatch={(sessionId) => navigate(courseHref(route.id, sessionId))}
        />
      )
    case 'research':
      return (
        <ResearchView
          key={route.id}
          projectId={route.id}
          entity={route.entity}
          // Replaced rather than pushed, for the reason scrubbing replaces.
          // Browsing a graph also *grows* it -- every selection pulls in a
          // neighbourhood -- so a back button that restored the previous
          // entity could not also un-draw what that click added. It would
          // return a URL describing a smaller graph than the one on screen,
          // which is worse than not offering the step back at all.
          onEntity={(id) => navigate(researchHref(route.id, id), { replace: true })}
        />
      )
    default:
      return <TreeView />
  }
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
      // move the marker -- and a poll would be N more requests per interval
      // on a page that already asks two per drawn row.
      void queryClient.invalidateQueries({ queryKey: queryKeys.allRuns() })
      void queryClient.invalidateQueries({ queryKey: queryKeys.allWorkers() })
    },
  )
}
