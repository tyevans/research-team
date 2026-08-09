import { useCallback, useEffect } from 'react'
import { useQueryClient } from '@tanstack/react-query'

import { notify } from '@application/notifications/toast-store.ts'
import { errorMessage } from '@application/ports/errors.ts'
import { queryKeys } from '@application/queries/keys.ts'
import { currentView, type SessionStore } from '@application/session/session-store.ts'
import { useContainer } from '@app/container-context.tsx'
import { ScrubPoint } from '@domain/session/scrub-point.ts'
import { compactedThrough } from '@domain/session/session.ts'
import { findFile } from '@domain/workspace/workspace-file.ts'
import type { EventIndex } from '@domain/session/event-index.ts'
import { shortId, type SessionId } from '@domain/shared/identifier.ts'
import type { FilePath } from '@domain/shared/file-path.ts'

import { ErrorBox } from '../common/primitives.tsx'
import { plural } from '../formatting/format.ts'
import { sessionHref, homeHref } from '../routing/routes.ts'
import { navigate } from '../routing/use-route.ts'
import { ActivityFeed } from './ActivityFeed.tsx'
import { Approvals } from './Approvals.tsx'
import { Composer } from './Composer.tsx'
import { Conversation } from './Conversation.tsx'
import { FileList } from './FileList.tsx'
import { FileView } from './FileView.tsx'
import { ScrubBar } from './ScrubBar.tsx'
import { Pane } from './Pane.tsx'
import { Timeline } from './Timeline.tsx'
import { usePanes } from './use-panes.ts'
import { useSessionStream } from './use-session-stream.ts'

export const SessionView = ({
  store,
  sessionId,
  at,
  path: openPath,
}: {
  /** Owned by the shell, which needs the same session's head for the
   *  breadcrumb. `open()` resets it wholesale, so switching sessions through it
   *  leaves nothing of the previous one behind. */
  store: SessionStore
  sessionId: SessionId
  at: ScrubPoint
  /** The open file, read from the route. Not mirrored into state: the address
   *  bar owns it, so a scrub cannot silently drop it and a link always
   *  reproduces the screen. */
  path: FilePath | null
}) => {
  const container = useContainer()
  const queryClient = useQueryClient()
  const state = store()
  const panes = usePanes()

  useEffect(() => {
    void store.getState().open(sessionId, at)
    return () => store.getState().close()
    // `at` is deliberately not a dependency: opening is per session, and a
    // scrub within one is handled below without refetching the log.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId, store])

  // A hand-edited hash or the browser's back button changes the position
  // without remounting, and the fold has to follow.
  useEffect(() => {
    if (!ScrubPoint.equals(store.getState().scrub, at)) void store.getState().scrubTo(at)
  }, [at, store])

  useSessionStream(store)

  // Expired highlights are swept on a timer so a flash does not linger until
  // some unrelated render happens to clear it.
  useEffect(() => {
    if (state.fresh.size === 0) return
    const timer = setTimeout(() => store.getState().sweepFresh(), 1_600)
    return () => clearTimeout(timer)
  }, [state.fresh, store])

  // Both of these rewrite the address bar rather than component state, and both
  // replace rather than push: dragging through forty events, or clicking down a
  // file list, should not bury the page you arrived from under forty entries.
  const selectEvent = useCallback(
    (point: ScrubPoint) => {
      navigate(sessionHref(sessionId, point, openPath), { replace: true })
    },
    [openPath, sessionId],
  )

  const openFile = useCallback(
    (path: FilePath) => {
      navigate(sessionHref(sessionId, state.scrub, path), { replace: true })
    },
    [sessionId, state.scrub],
  )

  /** Global "back to live". The timeline handles Escape itself and stops the
   *  event, so a keypress with it focused never folds twice.
   *
   *  `selectEvent` is a real dependency, and used to be suppressed as one. It
   *  closes over the open file, so the listener registered on the first render
   *  kept navigating with whatever file was open then — pressing Escape after
   *  opening a file dropped it, which is exactly the case the path is in the
   *  URL to survive. Re-subscribing costs one listener swap. */
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return
      if (!ScrubPoint.isHistorical(store.getState().scrub)) return
      if (document.activeElement instanceof HTMLTextAreaElement) return
      selectEvent(ScrubPoint.head())
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [selectEvent, store])

  const forkAt = (index: EventIndex) => {
    void store
      .getState()
      .fork(index)
      .then((forked) => {
        if (forked) {
          void queryClient.invalidateQueries({ queryKey: queryKeys.tree() })
          navigate(sessionHref(forked))
        }
      })
  }

  const endSession = () => {
    if (
      !window.confirm(
        'End this session and hand its files back to the project?\n\n' +
          'The log stays readable and forkable. The project becomes free, and the ' +
          "next session in it starts from this one's files.",
      )
    ) {
      return
    }
    void container.sessions
      .release(sessionId)
      .then((released) => {
        if (!released) {
          notify('This session is not in a project.', 'bad')
          return
        }
        notify(`Session ended. ${shortId(state.head?.projectId)} is free.`, 'good')
        void queryClient.invalidateQueries({ queryKey: queryKeys.projects() })
        navigate(homeHref())
      })
      .catch((error: unknown) => notify(`Could not end session: ${errorMessage(error)}`, 'bad'))
  }

  if (state.error) {
    return (
      <section className="view view-session">
        <ErrorBox
          title="Session unavailable"
          message={state.error}
          onRetry={() => void store.getState().reload()}
        />
      </section>
    )
  }

  const view = currentView(state)
  const historicalAt = ScrubPoint.toNullable(state.scrub)
  const files = view?.files ?? []
  const messages = view?.messages ?? []
  const compacted = compactedThrough(view?.compactedThrough, messages.length)

  return (
    <section className="view view-session">
      <ScrubBar
        head={state.head}
        log={state.log}
        scrub={state.scrub}
        loading={state.loadingSnapshot}
        onSelect={selectEvent}
        onFork={() => {
          if (state.scrub.kind === 'historical') forkAt(state.scrub.at)
        }}
        onEndSession={endSession}
      />

      <div className="panes" style={{ gridTemplateColumns: panes.gridTemplateColumns }}>
        <Pane
          name="timeline"
          title="Event log"
          label="Event timeline"
          meta={state.log.length > 0 ? plural(state.log.length, 'event') : ''}
          panes={panes}
          footer={<ActivityFeed store={store} />}
        >
          <Timeline
            log={state.log}
            scrub={state.scrub}
            fresh={state.fresh}
            discarded={state.discarded}
            onSelect={selectEvent}
            onFork={forkAt}
          />
        </Pane>

        <Pane
          name="workspace"
          title="Workspace"
          label="Workspace"
          meta={historicalAt !== null ? `@ event ${historicalAt}` : 'head'}
          panes={panes}
          bodyClassName="pane-body-split"
        >
          {state.snapshotError ? (
            <ErrorBox
              title={`Could not fold to event ${historicalAt}`}
              message={state.snapshotError}
              onRetry={() => void store.getState().scrubTo(state.scrub)}
            />
          ) : (
            <>
              <div className="files">
                <FileList
                  files={files}
                  open={openPath}
                  historicalAt={historicalAt}
                  onOpen={openFile}
                  onReopen={() => {
                    if (openPath) {
                      void queryClient.invalidateQueries({
                        queryKey: queryKeys.file(sessionId, openPath, state.scrub),
                      })
                    }
                  }}
                />
              </div>
              <div className="file-view">
                {/* Keep the open file honest: if it does not exist at this
                    point, say so rather than showing another point's bytes. */}
                {openPath && files.length > 0 && !findFile(files, openPath) ? (
                  <MissingHere path={openPath} at={historicalAt} />
                ) : (
                  <FileView sessionId={sessionId} path={openPath} scrub={state.scrub} />
                )}
              </div>
            </>
          )}
        </Pane>

        <Pane
          name="conversation"
          title="Conversation"
          label="Conversation"
          meta={
            messages.length > 0
              ? [
                  plural(messages.length, 'message'),
                  compacted ? `${compacted} compacted` : null,
                  historicalAt !== null ? `@ ${historicalAt}` : null,
                ]
                  .filter(Boolean)
                  .join(' · ')
              : ''
          }
          panes={panes}
          raw
          footer={
            <>
              <Approvals
                approvals={state.approvals}
                deciding={state.deciding}
                onDecide={(approval, decision) => void store.getState().decide(approval, decision)}
              />
              <Composer
                turn={state.turn}
                note={state.note}
                scrub={state.scrub}
                onSend={(input) => void store.getState().send(input)}
                onCancel={() => void store.getState().cancel()}
                onRecheck={() => void store.getState().refreshRunning(true)}
                onJumpTo={(index) => selectEvent(ScrubPoint.at(index))}
                onTyping={() => store.getState().dismissNote()}
              />
            </>
          }
        >
          <Conversation view={view} error={state.snapshotError} historicalAt={historicalAt} />
        </Pane>
      </div>
    </section>
  )
}

const MissingHere = ({ path, at }: { path: FilePath; at: number | null }) => (
  <div className="empty">
    <strong>Not in the workspace here.</strong>
    {`${path.value} does not exist as of event ${at ?? 'HEAD'}.`}
  </div>
)
