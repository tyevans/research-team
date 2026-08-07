import { useQueryClient } from '@tanstack/react-query'
import { useEffect, useMemo, useRef, useState } from 'react'

import { notify } from '@application/notifications/toast-store.ts'
import { queryKeys } from '@application/queries/keys.ts'
import { createSessionStore, type SessionStore } from '@application/session/session-store.ts'
import type { Course } from '@domain/project/course.ts'
import { CourseView } from '@presentation/course/CourseView.tsx'
import { treeHref, type Route } from '@presentation/routing/routes.ts'
import { useRoute } from '@presentation/routing/use-route.ts'
import { SessionView } from '@presentation/session/SessionView.tsx'
import { Breadcrumbs } from '@presentation/shell/Breadcrumbs.tsx'
import { ConnectionBadge, DriftBadge } from '@presentation/shell/ConnectionBadge.tsx'
import { StreamProvider, useStream } from '@presentation/shell/StreamProvider.tsx'
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

  useTreeRefresh(route.name === 'tree')

  return (
    <>
      <header className="topbar">
        <a className="brand" href={treeHref()}>
          <span className="brand-mark" />
          <span className="brand-name">research&#8209;team</span>
        </a>
        <Breadcrumbs
          route={route}
          session={route.name === 'session' ? head : null}
          course={route.name === 'course' ? course : null}
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
      return (
        <SessionView
          store={store}
          sessionId={route.id}
          at={route.at}
          path={route.path}
        />
      )
    case 'course':
      return <CourseView key={route.id} projectId={route.id} onLoaded={onCourse} />
    default:
      return <TreeView />
  }
}

/** The tree is a projection of every session, so any log frame can change it.
 *
 * Debounced, because frames arrive in a burst when a turn commits and
 * refetching per frame would be dozens of identical requests for one repaint.
 * Only while the tree is on screen: a session view has its own, finer-grained
 * subscription and does not want this one's refetches. */
const useTreeRefresh = (active: boolean) => {
  const stream = useStream()
  const queryClient = useQueryClient()
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(() => {
    if (!active) return
    const off = stream.onFrame((frame) => {
      if (frame.kind !== 'log') return
      if (timer.current) clearTimeout(timer.current)
      timer.current = setTimeout(() => {
        void queryClient.invalidateQueries({ queryKey: queryKeys.tree() })
        void queryClient.invalidateQueries({ queryKey: queryKeys.sessions() })
      }, 400)
    })
    return () => {
      off()
      if (timer.current) clearTimeout(timer.current)
    }
  }, [active, queryClient, stream])
}
