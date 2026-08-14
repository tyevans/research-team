import { useQueryClient } from '@tanstack/react-query'

import { queryKeys } from '@application/queries/keys.ts'
import type { SessionStore } from '@application/session/session-store.ts'
import { ScrubPoint } from '@domain/session/scrub-point.ts'
import { findFile } from '@domain/workspace/workspace-file.ts'
import type { SessionId } from '@domain/shared/identifier.ts'
import type { FilePath } from '@domain/shared/file-path.ts'

import { ErrorBox } from '../common/primitives.tsx'
import { plural } from '../formatting/format.ts'
import { ActivityFeed } from './ActivityFeed.tsx'
import { Composer } from './Composer.tsx'
import { Conversation } from './Conversation.tsx'
import { FileList } from './FileList.tsx'
import { FileView } from './FileView.tsx'
import { Timeline } from './Timeline.tsx'
import type { SessionScreen } from './use-session-screen.ts'

/** The four things a session's screen is made of, with nothing around them.
 *
 * **Content-only, and that is the whole design constraint.** Two arrangements
 * mount these: `SessionView`'s three-pane `Split` on `#/s/<id>`, where each of
 * them is a `Pane` body, and the project page's HOLDER column and MATERIAL
 * `workspace` tab, where none of them is inside a `Pane` at all. So a panel that
 * rendered its own `Pane` would be usable by exactly one of its two callers, and
 * a panel that rendered its own heading would draw a second one inside a pane
 * header that already has one — which is the "pane header inside a pane header"
 * slice 0 shipped and this slice removes.
 *
 * The meta strings are here for the same reason in reverse: they are the *only*
 * thing the two arrangements would otherwise duplicate, because `Pane` takes a
 * `meta` prop and the stacked column writes the same words into its own label.
 * Two copies of "`n` messages · `m` compacted · @ `k`" is two copies that drift.
 */

/** "12 events", or nothing at all for an empty log — `Pane` treats `undefined`
 *  as "no meta" and renders no element, which is what an empty log should
 *  read as. */
export const timelineMeta = (logLength: number): string | undefined =>
  logLength > 0 ? plural(logLength, 'event') : undefined

/** Where the workspace is folded to. Always a string: unlike the other two this
 *  is never absent, because "head" is a real answer and a workspace with no
 *  files at head is still at head. */
export const workspaceMeta = (historicalAt: number | null): string =>
  historicalAt !== null ? `@ event ${String(historicalAt)}` : 'head'

export const conversationMeta = (
  messageCount: number,
  compacted: number,
  historicalAt: number | null,
): string | undefined =>
  messageCount > 0
    ? [
        plural(messageCount, 'message'),
        compacted ? `${String(compacted)} compacted` : null,
        historicalAt !== null ? `@ ${String(historicalAt)}` : null,
      ]
        .filter(Boolean)
        .join(' · ')
    : undefined

export const TimelinePanel = ({ screen }: { screen: SessionScreen }) => (
  <Timeline
    log={screen.state.log}
    scrub={screen.state.scrub}
    fresh={screen.state.fresh}
    discarded={screen.state.discarded}
    onSelect={screen.selectEvent}
    onFork={screen.forkAt}
  />
)

/** The live activity strip under the timeline. A separate export rather than
 *  part of `TimelinePanel` because it is pinned *outside* the log's scroller in
 *  both arrangements — `Pane`'s `footer` slot on `#/s/`, and the bottom of the
 *  timeline section in HOLDER — and inside it, it scrolls away. */
export const TimelineFeed = ({ store }: { store: SessionStore }) => <ActivityFeed store={store} />

/** The file list over the file viewer.
 *
 * Renders its own two-element flex column rather than relying on a `Pane` body
 * with `scroll="regions"`, because MATERIAL's tab panel is not a pane body. The
 * two children carry `.files` and `.file-view`, which are the classes
 * `workspace.css` dresses — including the inward focus ring measured in
 * `FileList.browser.test.tsx`, which is why neither wrapper is replaced with
 * utilities here.
 */
export const WorkspacePanel = ({
  screen,
  sessionId,
  openPath,
}: {
  screen: SessionScreen
  sessionId: SessionId
  openPath: FilePath | null
}) => {
  const queryClient = useQueryClient()

  if (screen.state.snapshotError) {
    return (
      <ErrorBox
        heading={`Could not fold to event ${String(screen.historicalAt)}`}
        message={screen.state.snapshotError}
        onRetry={() => void screen.state.scrubTo(screen.state.scrub)}
      />
    )
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="files">
        <FileList
          files={screen.files}
          open={openPath}
          historicalAt={screen.historicalAt}
          onOpen={screen.openFile}
          onReopen={() => {
            if (openPath) {
              void queryClient.invalidateQueries({
                queryKey: queryKeys.file(sessionId, openPath, screen.state.scrub),
              })
            }
          }}
        />
      </div>
      <div className="file-view">
        {/* Keep the open file honest: if it does not exist at this point, say
            so rather than showing another point's bytes. */}
        {openPath && screen.files.length > 0 && !findFile(screen.files, openPath) ? (
          <MissingHere path={openPath} at={screen.historicalAt} />
        ) : (
          <FileView sessionId={sessionId} path={openPath} scrub={screen.state.scrub} />
        )}
      </div>
    </div>
  )
}

export const ConversationPanel = ({ screen }: { screen: SessionScreen }) => (
  <Conversation
    view={screen.view}
    error={screen.state.snapshotError}
    historicalAt={screen.historicalAt}
  />
)

/** The composer, wired. Pinned below the transcript in both arrangements and
 *  therefore never a child of `ConversationPanel`: `Pane`'s `footer` and
 *  HOLDER's last row are both outside the scroller, which is what stops a text
 *  box leaving the screen as the conversation grows. */
export const ComposerPanel = ({
  screen,
  store,
}: {
  screen: SessionScreen
  store: SessionStore
}) => (
  <Composer
    turn={screen.state.turn}
    note={screen.state.note}
    scrub={screen.state.scrub}
    onSend={(input) => void store.getState().send(input)}
    onCancel={() => void store.getState().cancel()}
    onRecheck={() => void store.getState().refreshRunning(true)}
    onJumpTo={(index) => screen.selectEvent(ScrubPoint.at(index))}
    onTyping={() => store.getState().dismissNote()}
  />
)

const MissingHere = ({ path, at }: { path: FilePath; at: number | null }) => (
  <div className="empty">
    <strong>Not in the workspace here.</strong>
    {`${path.value} does not exist as of event ${at ?? 'HEAD'}.`}
  </div>
)
