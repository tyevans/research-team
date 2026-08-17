import type { ReactNode } from 'react'

import type { GraphNode } from '@domain/knowledge/graph.ts'
import type { ResolvedEntity } from '@domain/lesson/resolved.ts'

/** The three states a resolved widget does not draw itself.
 *
 * Here rather than in each widget so five of them cannot drift into five
 * different ways of saying "not found" -- and so the *tone* is decided once.
 * The tone is the point: `missing` and `unavailable` degrade to readable
 * prose, never to an error panel, because a model writing about an entity the
 * extraction pipeline has not reached yet is normal rather than a defect.
 * Nothing here carries `role="alert"`, and that omission is load-bearing --
 * `ResolvedFrame.test.tsx` fails on `queryByRole('alert')` if one appears.
 *
 * `missing` and `unavailable` are worded differently on purpose. "Not in this
 * project's graph" is a claim about the corpus, and a page that could not look
 * the name up at all has not earned it.
 */
export const ResolvedFrame = ({
  reference,
  name,
  onPick,
  children,
}: {
  reference: ResolvedEntity
  /** What the author wrote, shown verbatim in every non-resolved state. The
   *  reference is the prose the widget degrades to, so it is never derived
   *  from a candidate -- a reader must see the word the answer used. */
  name: string
  /** Where a picked candidate goes. Optional because a widget may have
   *  nothing to do with one; the picker is still worth drawing, since seeing
   *  that two entities share a name is itself the answer to "why is this
   *  blank". */
  onPick?: (entityId: string) => void
  children: (entity: GraphNode) => ReactNode
}) => {
  if (reference.state === 'resolved') return <>{children(reference.entity)}</>

  if (reference.state === 'ambiguous') {
    return (
      <div className="cmp-ref cmp-ref-ambiguous">
        <span className="cmp-ref-name">{name}</span>
        <p className="cmp-ref-note">
          {reference.candidates.length} entities in this project share that name.
        </p>
        <ul className="cmp-ref-picker">
          {reference.candidates.map((candidate) => (
            <li key={candidate.id}>
              <button type="button" className="cmp-ref-pick" onClick={() => onPick?.(candidate.id)}>
                <span className="cmp-ref-pick-name">{candidate.name}</span>
                <span className="cmp-ref-pick-type">{candidate.entityType}</span>
              </button>
            </li>
          ))}
        </ul>
      </div>
    )
  }

  if (reference.state === 'missing') {
    return (
      <div className="cmp-ref cmp-ref-missing">
        <span className="cmp-ref-name">{name}</span>
        <span className="cmp-ref-note">not in this project&rsquo;s graph</span>
      </div>
    )
  }

  // `loading` and `unavailable` draw the same thing: the reference, and
  // nothing that would be a claim about the corpus. They differ only in
  // whether an answer is still coming, which is not worth a spinner on a
  // block a reader is scrolling past.
  return (
    <div className="cmp-ref cmp-ref-quiet">
      <span className="cmp-ref-name">{name}</span>
    </div>
  )
}
