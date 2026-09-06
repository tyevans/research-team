import type { AskConversationSummary, AskTranscript } from '@domain/ask/conversation.ts'
import type { ProjectId } from '@domain/shared/identifier.ts'

import { AskComposer } from './AskComposer.tsx'
import { AskHead } from './AskHead.tsx'
import { AskThread } from './AskThread.tsx'

/** The ask page, as a pure function of props.
 *
 * The split from `AskView` is what makes anything on this page openable in
 * Storybook: a store here would mean a container, a repository fake and a
 * `crypto.randomUUID` in scope before a single pixel could be looked at, and
 * the states worth looking at -- mid-stream, refused, forty turns deep -- are
 * precisely the ones that are awkward to reach through a real repository.
 *
 * It owns the viewport and does not scroll, so `AskThread` can: see there for
 * why the composer must keep the bottom edge.
 */
export const AskPage = ({
  projectId,
  transcript,
  conversationId,
  asking,
  error,
  onAsk,
  onReset,
  history = [],
  historyError = null,
  reading = false,
}: {
  projectId: ProjectId
  transcript: AskTranscript
  // Null until the stream's first frame names it -- see `AskState.conversationId`.
  conversationId: string | null
  asking: boolean
  error: string | null
  onAsk: (question: string) => void
  onReset: () => void
  /** Past conversations, for the thread's empty state. Defaulted so the eight
   *  stories and the tests that predate history need no argument -- a page
   *  with no history draws none, which is the same thing they showed before. */
  history?: readonly AskConversationSummary[]
  historyError?: string | null
  /** Whether this is a stored conversation being read rather than a live one.
   *
   * It hides the composer, and that is the whole of what it does. A reader
   * cannot continue a stored conversation -- resuming one is B102, and the
   * server has no route for it -- so a composer here would accept a question
   * and start a *different* conversation under the same heading. Disabling it
   * instead was rejected: a disabled control with no explanation is a promise
   * the page cannot keep, and there is nothing to explain until B102 lands. */
  reading?: boolean
}) => (
  // `ask` carries no rules of its own -- it is a selector hook for
  // `AskView.browser.test.tsx`, which cannot query `section:has(...)`
  // portably. The layout it names is the `flex`/`overflow-hidden` utilities
  // beside it: the section owns the viewport and does not scroll, so
  // `AskThread` can, which is what keeps the composer on the bottom edge.
  <section className="ask flex min-h-0 flex-1 flex-col overflow-hidden">
    <AskHead projectId={projectId} onReset={onReset} reading={reading} />

    {/* A refusal made before the stream started -- a busy chat, a dead
        network, an unknown project -- never becomes an answer, so it has
        nowhere to live in the transcript's own error and needs saying here
        too: the store puts it in both the banner and the failed turn, since a
        rejection is the one case where it can afford to. */}
    {error ? (
      <div className="error-box mx-5 mt-4 shrink-0" role="alert">
        <strong>That question did not go through.</strong>
        {error}
      </div>
    ) : null}

    <AskThread
      projectId={projectId}
      transcript={transcript}
      conversationId={conversationId}
      history={history}
      historyError={historyError}
    />

    {reading ? null : <AskComposer asking={asking} onAsk={onAsk} />}
  </section>
)
