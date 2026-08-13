import type { AskTranscript } from '@domain/ask/conversation.ts'
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
  asking,
  error,
  onAsk,
  onReset,
}: {
  projectId: ProjectId
  transcript: AskTranscript
  asking: boolean
  error: string | null
  onAsk: (question: string) => void
  onReset: () => void
}) => (
  // `ask` carries no rules of its own -- it is a selector hook for
  // `AskView.browser.test.tsx`, which cannot query `section:has(...)`
  // portably. The layout it names is the `flex`/`overflow-hidden` utilities
  // beside it: the section owns the viewport and does not scroll, so
  // `AskThread` can, which is what keeps the composer on the bottom edge.
  <section className="ask flex min-h-0 flex-1 flex-col overflow-hidden">
    <AskHead projectId={projectId} onReset={onReset} />

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

    <AskThread projectId={projectId} transcript={transcript} />

    <AskComposer asking={asking} onAsk={onAsk} />
  </section>
)
