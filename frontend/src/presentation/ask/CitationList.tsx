import type { Citation } from '@domain/ask/conversation.ts'
import type { ProjectId } from '@domain/shared/identifier.ts'

import { projectHref } from '../routing/routes.ts'

/** What an answer stood on, as links back into the project.
 *
 * Links rather than labels, because the whole value of a citation is being
 * able to go and read the thing -- an answer that names a source or topic you cannot
 * open is asking to be taken on trust.
 *
 * Cites sources or topics (B52): links to the project's `doc` facet or `topic` facet.
 */
export const CitationList = ({
  projectId,
  citations,
}: {
  projectId: ProjectId
  citations: readonly Citation[]
}) => {
  // Nothing at all rather than an empty labelled list: most answers cite
  // nothing, and a "Sources" heading over emptiness on every one of them reads
  // as a page that lost its data.
  if (citations.length === 0) return null

  return (
    <div className="flex flex-wrap items-baseline gap-2 text-sm">
      <span className="tracking-wide text-xs text-fg-faint uppercase">Sources</span>
      {/* Zeroed as utilities rather than plain CSS: this build imports no
          preflight, so a bare `<ul>` arrives with the user agent's margin,
          padding and bullets, and `--spacing-0` makes `m-0`/`p-0` really emit
          -- see `AskView.browser.test.tsx`'s zeroing assertion, which selects
          this list. */}
      <ul className="m-0 flex list-none flex-wrap gap-2 p-0">
        {citations.map((citation) => (
          <li key={`${citation.kind}-${citation.id}`}>
            {/* The project's document or topic facet, not a bare id: the reader is on
                the project page already, and this keeps them on it. */}
            <a
              className="font-mono text-sm"
              href={projectHref(projectId, {
                facet: citation.kind === 'topic' ? 'topic' : 'doc',
                id: citation.id,
              })}
            >
              {citation.kind === 'topic' ? `topic:${citation.id}` : citation.id}
            </a>
          </li>
        ))}
      </ul>
    </div>
  )
}
