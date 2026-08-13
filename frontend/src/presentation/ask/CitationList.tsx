import type { Citation } from '@domain/ask/conversation.ts'
import type { ProjectId } from '@domain/shared/identifier.ts'

import { projectHref } from '../routing/routes.ts'

/** What an answer stood on, as links back into the project.
 *
 * Links rather than labels, because the whole value of a citation is being
 * able to go and read the thing -- an answer that names a source you cannot
 * open is asking to be taken on trust.
 *
 * One kind, `source`. `Citation` says why there is no longer a topic kind, and
 * this renders nothing for one because there is nothing to render: a `kind`
 * with one member needs no branch, and a branch for a case the type forbids is
 * dead code that reads as a missing feature.
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
    <div className="ask-cites">
      <span className="ask-cites-label">Sources</span>
      <ul>
        {citations.map((citation) => (
          <li key={citation.id}>
            {/* The project's document facet, not a bare id: the reader is on
                the project page already, and this keeps them on it. */}
            <a href={projectHref(projectId, { facet: 'doc', id: citation.id })}>{citation.id}</a>
          </li>
        ))}
      </ul>
    </div>
  )
}
