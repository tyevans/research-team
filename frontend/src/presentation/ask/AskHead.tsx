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
 * Not `.view-head`: that rule lives unlayered in `tree.css` and caps itself at
 * 1100px for the tree it was written for, which this page had to undo with two
 * `!` overrides. Owning the head outright is one rule instead of three.
 */
export const AskHead = ({ projectId, onReset }: { projectId: ProjectId; onReset: () => void }) => (
  // `border-0` first, `border-b` second: `border-solid` sets `border-style:
  // solid` on all four sides, and a side with a style but no explicit width
  // falls back to the browser's `medium` (~3px) rather than 0 -- the same
  // defect `AskTurn.tsx` documents, caught here by the same screenshot.
  <header className="flex shrink-0 items-start justify-between gap-5 border-0 border-b border-solid border-line-soft px-5 pt-5 pb-4">
    <div>
      <h1 className="font-semibold m-0 text-2xl">Ask</h1>
      {/* `ask-sub` is a selector hook for `AskView.test.tsx`, which has no
          other way to tell this paragraph from the composer's own "not
          saved" copy -- both say the same sentence on purpose. */}
      <p className="ask-sub mt-1 max-w-[60ch] text-sm text-fg-dim">
        Answers come from this project’s sources and findings. Not saved — the conversation goes
        when you leave.
      </p>
    </div>

    <div className="flex flex-wrap items-center gap-3">
      {/* One control in three states rather than three buttons: the border
          belongs to the group, and the links divide it. */}
      <nav
        className="flex items-stretch overflow-hidden rounded-md border border-solid border-line"
        aria-label="Project views"
      >
        {/* The project page with no selection, which is the course today. */}
        <a
          className="border-0 px-4 py-2 text-sm whitespace-nowrap text-fg-dim no-underline hover:bg-bg-hover hover:text-fg aria-[current=page]:bg-bg-raise aria-[current=page]:text-fg"
          href={projectHref(projectId)}
        >
          Course
        </a>
        <a
          className="border-0 border-l border-solid border-line px-4 py-2 text-sm whitespace-nowrap text-fg-dim no-underline hover:bg-bg-hover hover:text-fg aria-[current=page]:bg-bg-raise aria-[current=page]:text-fg"
          href={projectHref(projectId, { facet: 'entity', id: null })}
        >
          Research
        </a>
        {/* A link to where you already are, rather than a disabled span: it
            keeps the three the same kind of thing, and `aria-current` is what
            says the difference -- kept off a parallel `.is-current` class so
            the two facts cannot drift, per the `aria-[current=page]:` variant
            above and below. */}
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
