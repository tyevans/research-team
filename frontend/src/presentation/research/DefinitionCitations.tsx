import type { DefinitionCitation } from '@domain/knowledge/graph.ts'
import { shortId, type ProjectId } from '@domain/shared/identifier.ts'

import { projectHref } from '../routing/routes.ts'

/** The passages a definition was drawn from, as links into the document.
 *
 * Extracted from `GraphDetail`'s panel rather than copied into
 * `DefinitionWidget`, for the reason `ResolvedFrame` exists one layer up: two
 * differently-shaped citation links would be two places to get the `atSeconds`
 * check wrong, and that check is subtle enough to get wrong once already --
 * `atSeconds` is `0` for a real citation at a source's first second, so a
 * truthiness test drops the seek param silently for exactly that case.
 *
 * Rendered at all, rather than merely carried on the object, because the
 * backend refuses to store a definition that cites nothing (see
 * `entity_definitions.py`) on the premise that an ungrounded definition is
 * indistinguishable from a correct one at a glance. Dropping the citations at
 * the last step throws that guarantee away: a reader sees prose that reads as
 * fact with no way to tell it was checked.
 *
 * Known gap, inherited unchanged from the panel this came out of:
 * `Selection`'s `PlainFacet` arm carries no `start`/`end`, so a link opens the
 * document rather than the exact cited span.
 *
 * `className` is on the list and not the links because that is the only half
 * the two callers disagree about: the panel lays its row out with utilities,
 * and the widget's row is a `cmp-*` rule in `components.css` beside its
 * sibling widgets'. The anchors are deliberately *not* parameterised -- a
 * citation should look like a citation on both surfaces.
 */
export const DefinitionCitations = ({
  projectId,
  citations,
  className = 'm-0 flex list-none flex-wrap gap-2 p-0',
}: {
  projectId: ProjectId
  citations: readonly DefinitionCitation[]
  className?: string
}) => {
  if (citations.length === 0) return null

  return (
    <ul className={className}>
      {citations.map((citation) => (
        <li key={`${citation.sourceId}|${String(citation.start)}|${String(citation.end)}`}>
          <a
            className="font-mono text-xs text-fg-dim no-underline hover:underline"
            href={
              projectHref(projectId, { facet: 'doc', id: citation.sourceId }) +
              // Checked against `null`, not truthiness: `atSeconds` is `0` for
              // a real citation at a source's first second, and `0 ? … : …`
              // would silently drop the query for exactly that case. Same `?t=`
              // query `expandReferences` emits for an inline reference -- one
              // seek param, not two -- formatted with `String()` rather than
              // `toFixed`: it prints `252` for the common whole-second case
              // (matching the integer-only grammar `[[src:id@252]]` parses) and
              // keeps a genuine fraction like `252.5` intact, where a fixed
              // precision would either truncate or pad zeros nobody asked for.
              (citation.atSeconds === null ? '' : `?t=${String(citation.atSeconds)}`)
            }
          >
            {shortId(citation.sourceId)}
          </a>
        </li>
      ))}
    </ul>
  )
}
