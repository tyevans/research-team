import type { ProjectId } from '@domain/shared/identifier.ts'

import { Button } from '../common/primitives.tsx'
import { projectHref } from '../routing/routes.ts'

/** The page's heading, and the three places a reader can be.
 *
 * Course, Research and Ask are three states of one control, and the page used
 * to draw two of them as quiet buttons and the third as nothing at all -- so
 * the reader on Ask saw only the two places they were not. They are one `nav`
 * now, with `aria-current="page"` on the one you are on, which is the same
 * fact told to a screen reader and to a stylesheet at once.
 *
 * "New chat" sits outside that group. It is an action rather than a
 * destination, and grouping it with three links is why the row read as four
 * unrelated buttons.
 *
 * Not `.view-head`: that rule lived unlayered in `tree.css` and capped itself at
 * 1100px for the tree it was written for, which this page had to undo with two
 * `!` overrides. Owning the head outright is one rule instead of three.
 *
 * The rule is **deleted** as of 2026-08-14 -- the course and research views
 * were its last two users and both are gone -- so the class this paragraph
 * declines no longer exists to be declined. Kept, and put in the past tense,
 * because it is the reason this component owns its own head rather than
 * reaching for a shared one, and that reason outlives the rule: the next
 * shared head someone writes will want the same cap for the same page, and
 * this is where the cost of adopting it is written down.
 */
export const AskHead = ({
  projectId,
  onReset,
  reading = false,
}: {
  projectId: ProjectId
  onReset: () => void
  /** Whether a stored conversation is being read rather than a live one.
   *
   * It changes two strings and nothing else. **The composer is absent in this
   * mode, and a page that removed it without saying so leaves a reader looking
   * for a control that used to be there** -- found by driving the built
   * console against a real database on 2026-09-05, where the head still
   * offered to keep a conversation on a page there was no way to add to. */
  reading?: boolean
}) => (
  // `border-0` first, `border-b` second: `border-solid` sets `border-style:
  // solid` on all four sides, and a side with a style but no explicit width
  // falls back to the browser's `medium` (~3px) rather than 0 -- the same
  // defect `AskTurn.tsx` documents, caught here by the same screenshot.
  <header className="flex shrink-0 items-start justify-between gap-5 border-0 border-b border-solid border-line-soft px-5 pt-5 pb-4">
    <div>
      <h1 className="m-0 text-2xl font-semibold">{reading ? 'A past conversation' : 'Ask'}</h1>
      {/* `ask-sub` is a selector hook for `AskView.test.tsx`, which has no
          other way to tell this paragraph from the composer's own copy -- both
          say the same thing on purpose. See `AskComposer` for why both stopped
          saying "not saved": the ask has been persisted the whole time, and
          the sentence only became checkable when the history list gave a
          reader a way to reopen one. */}
      <p className="ask-sub mt-1 max-w-[60ch] text-sm text-fg-dim">
        {reading
          ? 'Read only — this conversation cannot be continued. Start a new chat to ask something.'
          : 'Answers come from this project’s sources and findings. Kept — you can reopen a past conversation from a new chat.'}
      </p>
    </div>

    <div className="flex flex-wrap items-center gap-3">
      {/* One control in two states rather than two buttons: the border belongs
          to the group, and the link divides it.

          **Two, where there were three.** "Course" and "Research" were two
          entries pointing at two pages; increment C merged those pages, so both
          were addresses of the same project view differing only in which
          MATERIAL tab opened. Two entries that land on one page, named after
          routes that no longer exist, describe a console this is no longer. The
          graph is one tab away from where "Project" lands, which is the click
          this costs and it is the honest price of the merge. */}
      <nav
        className="flex items-stretch overflow-hidden rounded-md border border-solid border-line"
        aria-label="Project views"
      >
        <a
          className="border-0 px-4 py-2 text-sm whitespace-nowrap text-fg-dim no-underline hover:bg-bg-hover hover:text-fg aria-[current=page]:bg-bg-raise aria-[current=page]:text-fg"
          href={projectHref(projectId)}
        >
          Project
        </a>
        {/* A link to where you already are, rather than a disabled span: it
            keeps the two the same kind of thing, and `aria-current` is what
            says the difference -- kept off a parallel `.is-current` class so
            the two facts cannot drift, per the `aria-[current=page]:` variant
            above. */}
        <a
          className="border-0 border-l border-solid border-line px-4 py-2 text-sm whitespace-nowrap text-fg-dim no-underline hover:bg-bg-hover hover:text-fg aria-[current=page]:bg-bg-raise aria-[current=page]:text-fg"
          aria-current="page"
          href={projectHref(projectId, { facet: 'ask', id: null })}
        >
          Ask
        </a>
      </nav>

      <Button tone="quiet" onClick={onReset}>
        New chat
      </Button>
    </div>
  </header>
)
