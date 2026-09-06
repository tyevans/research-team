import type { AskConversationSummary } from '@domain/ask/conversation.ts'
import type { ProjectId } from '@domain/shared/identifier.ts'

import { projectHref } from '../routing/routes.ts'
import { plural, relativeTime } from '../formatting/format.ts'

/** Past conversations, as links.
 *
 * **Where this lives is the decision B103 said had not been made.** It draws
 * inside the thread's empty state rather than in a rail, a drawer or a tab of
 * its own, and the reasoning is that the empty state is exactly the moment a
 * reader wants it: the page they are looking at has nothing on it, and the
 * thing they most plausibly want is something they already asked. A rail would
 * take width from a 72ch column on every turn of every conversation to serve a
 * click that happens once; a drawer would be a second piece of chrome on a page
 * whose whole argument is that it has almost none.
 *
 * The cost, and it is real: mid-conversation the list is not reachable without
 * pressing "New chat" first. That is one extra click on the one path where the
 * reader has said what they want by typing it, and it keeps the transcript --
 * the thing this page is -- undivided. If it turns out to be wrong, the fix is
 * a disclosure in `AskHead`, not a rail.
 *
 * Links rather than buttons, because a conversation has a URL
 * (`#/p/<id>/ask/<conversation>`) and a reader should be able to open one in a
 * new tab or send it to somebody. That is the same argument `routes.ts` makes
 * for a scrub point being in the hash.
 */
export const AskHistory = ({
  projectId,
  conversations,
  error,
}: {
  projectId: ProjectId
  conversations: readonly AskConversationSummary[]
  /** The list route's refusal, rendered rather than swallowed. A 503 here
   *  means the ask projection is unwired, which the route distinguishes from
   *  an empty project on purpose -- see `list_asks`. Showing nothing would
   *  throw that distinction away at the last step. */
  error: string | null
}) => {
  if (error !== null) {
    return (
      <p className="m-0 text-sm text-fg-faint" role="status">
        Earlier conversations could not be loaded — {error}
      </p>
    )
  }
  if (conversations.length === 0) return null

  return (
    <section className="ask-history flex w-full flex-col gap-2" aria-labelledby="ask-history-head">
      <h2 id="ask-history-head" className="m-0 text-sm font-semibold text-fg-dim">
        Earlier conversations
      </h2>
      {/* Zeroed because there is no preflight: a bare `<ul>` keeps the user
          agent's margin, padding and bullets. */}
      <ul className="m-0 flex list-none flex-col gap-1 p-0">
        {conversations.map((conversation) => (
          <li key={conversation.conversationId}>
            <a
              className="flex flex-col gap-1 rounded-md border border-solid border-line-soft px-3 py-2 no-underline hover:bg-bg-hover"
              href={projectHref(projectId, {
                facet: 'ask',
                id: conversation.conversationId,
              })}
            >
              {/* The first question is the only thing that names a
                  conversation -- nothing titles these, and a title would be a
                  second model call per ask for a string a reader can already
                  recognise. Clamped to two lines rather than truncated at a
                  character count: a question's first clause is what makes it
                  recognisable, and where that ends is a function of the width
                  the reader has. */}
              <span className="line-clamp-2 text-sm text-fg">{conversation.firstQuestion}</span>
              <span className="text-xs text-fg-faint">
                {relativeTime(conversation.openedAt)} · {plural(conversation.turnCount, 'turn')}
              </span>
            </a>
          </li>
        ))}
      </ul>
    </section>
  )
}
