import { useCallback } from 'react'

import type { SessionStore } from '@application/session/session-store.ts'
import { ScrubPoint } from '@domain/session/scrub-point.ts'
import type { SessionId } from '@domain/shared/identifier.ts'
import type { FilePath } from '@domain/shared/file-path.ts'

import { Pane } from '../layout/Pane.tsx'
import { Split } from '../layout/Split.tsx'

import { Confirm } from '../common/Confirm.tsx'
import { ErrorBox } from '../common/primitives.tsx'
import { sessionHref } from '../routing/routes.ts'
import {
  ComposerPanel,
  ConversationPanel,
  conversationMeta,
  TimelineFeed,
  TimelinePanel,
  timelineMeta,
  WorkspacePanel,
  workspaceMeta,
} from './panels.tsx'
import { ScrubBar } from './ScrubBar.tsx'
import { SESSION_TRACKS, useSessionPanes } from './use-session-panes.ts'
import { useSessionScreen } from './use-session-screen.ts'

/** One session, read on its own: three panes and nothing else on the page.
 *
 * **This keeps its `Split`, and the project page no longer does.** A transcript
 * read at `#/s/<id>` is still three peer columns whose widths a reader trades
 * against each other, which is exactly what `Split` is; `routes.ts:29-34`
 * argues that route stays top-level and this is what it stays as. What moved out
 * is everything that was not the arrangement — `useSessionScreen` holds the
 * effects and the callbacks, `panels.tsx` holds the contents — because HOLDER
 * needs both of those in a shape with no `Split` in it.
 *
 * Two renderings of one session with different layout ownership is a real
 * complexity cost and the plan's §3.3 says so plainly. The alternative was a
 * `Split` inside a `Pane`, which slice 0 shipped and this slice removes: it puts
 * a pane header inside a pane header, and the reader pays for a nesting that
 * exists only because two files could not share a hook.
 */
export const SessionView = ({
  store,
  sessionId,
  at,
  path: openPath,
}: {
  /** Owned by the shell, which needs the same session's head for the
   *  breadcrumb. */
  store: SessionStore
  sessionId: SessionId
  at: ScrubPoint
  /** The open file, read from the route. */
  path: FilePath | null
}) => {
  const panes = useSessionPanes()

  // Memoised because `useSessionScreen` lists it as a dependency of the two
  // navigation callbacks, and one of those is a `document` listener's
  // dependency in turn: a fresh function every render would re-subscribe the
  // Escape handler on every render rather than on every file change.
  const href = useCallback(
    (point: ScrubPoint, path: FilePath | null) => sessionHref(sessionId, point, path),
    [sessionId],
  )

  const screen = useSessionScreen({ store, sessionId, at, path: openPath, href })
  const { state } = screen

  if (state.error) {
    return (
      <section className="view view-session">
        <ErrorBox
          heading="Session unavailable"
          message={state.error}
          onRetry={() => void store.getState().reload()}
        />
      </section>
    )
  }

  return (
    <section className="view view-session">
      <ScrubBar
        head={state.head}
        log={state.log}
        scrub={state.scrub}
        loading={state.loadingSnapshot}
        onSelect={screen.selectEvent}
        onFork={() => {
          if (state.scrub.kind === 'historical') screen.forkAt(state.scrub.at)
        }}
        onEndSession={() => screen.setEndPending(true)}
      />

      {/* The last `window.confirm` in the console, S-D1, and the one place a
          reader was still handed the browser's own chrome: a box that blocks
          the whole tab, cannot be styled, and renders these two sentences as
          one paragraph joined by newlines because that is all it can do. The
          wording is carried over verbatim -- it was already right, and it is
          the part that matters, because "end this session" sounds
          destructive and these sentences are what say it is not. Only the box
          changed. */}
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

      <Split
        id="session"
        label="Session panes"
        tracks={SESSION_TRACKS}
        collapsed={panes.collapsed}
        onCollapsedChange={panes.onCollapsedChange}
        onRefuse={panes.onRefuse}
      >
        <Pane
          id="timeline"
          label="Event log"
          meta={timelineMeta(state.log.length)}
          footer={<TimelineFeed store={store} />}
        >
          <TimelinePanel screen={screen} />
        </Pane>

        <Pane
          id="workspace"
          label="Workspace"
          meta={workspaceMeta(screen.historicalAt)}
          // The file list and the file viewer scroll independently, so the
          // body must be a column that does not scroll around them.
          scroll="regions"
        >
          <WorkspacePanel screen={screen} sessionId={sessionId} openPath={openPath} />
        </Pane>

        <Pane
          id="conversation"
          label="Conversation"
          meta={conversationMeta(screen.messages.length, screen.compacted, screen.historicalAt)}
          // `Conversation` renders its own scroll container because it holds a
          // ref on it to stick to the bottom, so this body is a column around
          // it rather than a second scroller.
          scroll="regions"
          footer={
            <>
              {/* Approvals used to sit here, above the composer. They are now
                  the shell's `DecisionBar`, for the reason that component
                  states: a gated call parked in this footer was invisible from
                  every other page in the console. */}
              <ComposerPanel screen={screen} store={store} />
            </>
          }
        >
          <ConversationPanel screen={screen} />
        </Pane>
      </Split>
    </section>
  )
}
