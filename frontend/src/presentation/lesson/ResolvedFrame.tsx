import { useState, type ReactNode } from 'react'

import type { GraphNode } from '@domain/knowledge/graph.ts'
import type { ResolvedEntity } from '@domain/lesson/resolved.ts'

/** How many candidates the picker will draw.
 *
 * `/graph/entities?name=` is a *substring* filter, so this is reachable with
 * an ordinary short name rather than a pathological one -- a reference to
 * "Const" in a Roman-history project matches Constantine, Constantius,
 * Constans, Constantinople and everything else beginning that way, and an
 * uncapped picker would put a hundred buttons inside a paragraph of prose.
 * Eight is a judgement, not a measurement: enough that a genuine collision
 * between two or three entities never truncates, few enough that the block
 * stays something a reader scrolls past.
 *
 * The cap is never silent. A picker showing some of the matches without
 * saying so is worse than one that shows none, because a reader who does not
 * find their entity concludes it is absent.
 */
const MAX_CANDIDATES = 8

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
 *
 * **The pick lives here rather than in each widget, and it is scoped to the
 * candidate list that offered it.** It was a `useState` in `DefinitionWidget`
 * before, overriding the reference unconditionally -- so a pick survived a
 * later search result that no longer contained it, and the widget kept drawing
 * an entity the current answer does not offer. That is a property of this
 * shape rather than of any one widget, and five copies of it would be five
 * chances to get it wrong; `ResolvedFrame.test.tsx` fails on the stale pick if
 * the scoping below is removed.
 */
export const ResolvedFrame = ({
  reference,
  name,
  children,
}: {
  reference: ResolvedEntity
  /** What the author wrote, shown verbatim in every non-resolved state. The
   *  reference is the prose the widget degrades to, so it is never derived
   *  from a candidate -- a reader must see the word the answer used. */
  name: string
  children: (entity: GraphNode) => ReactNode
}) => {
  const [picked, setPicked] = useState<string | null>(null)

  if (reference.state === 'resolved') return <>{children(reference.entity)}</>

  if (reference.state === 'ambiguous') {
    // A pick counts only while the candidate list still offers it. Held
    // unconditionally it would outlive the search result that produced it: a
    // refetch that resolves the name to one entity, or to a different set,
    // would leave the widget drawing an id nothing on the page now names.
    //
    // The picked candidate carries the author's name and an empty
    // `entityType`, the same synthesis `useEntityReference` makes for a
    // pinned `entity_id` and for the same reason -- the id is the whole of
    // what a pick decides.
    const chosen = reference.candidates.find((candidate) => candidate.id === picked)
    if (chosen) return <>{children({ id: chosen.id, name, entityType: '' })}</>

    const shown = reference.candidates.slice(0, MAX_CANDIDATES)
    const hidden = reference.candidates.length - shown.length

    return (
      <div className="cmp-ref cmp-ref-ambiguous">
        <span className="cmp-ref-name">{name}</span>
        <p className="cmp-ref-note">
          {/* "match" rather than "share that name": the candidates are a
              substring search's results, and only some of them literally
              carry the name. `at least` is what `truncated` buys -- the
              server capped its page, so this count is a floor and stating it
              flat would be a claim about the graph the client cannot make. */}
          {reference.truncated ? 'At least ' : ''}
          {reference.candidates.length} entities in this project match that name
          {hidden > 0 ? `; showing the first ${String(shown.length)}` : ''}.
        </p>
        <ul className="cmp-ref-picker">
          {shown.map((candidate) => (
            <li key={candidate.id}>
              <button
                type="button"
                className="cmp-ref-pick"
                onClick={() => setPicked(candidate.id)}
              >
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
      // No `cmp-ref-missing` modifier: it had no rule in `components.css`, and
      // a class in the attribute with nothing in the bundle is indistinguishable
      // from one that works (CLAUDE.md's unlayered-`tokens.css` entry is the
      // same shape of failure). The `.cmp-ref-note` beside the name is what
      // draws this state's difference, and a widget branching on the state has
      // `reference.state` rather than a selector.
      <div className="cmp-ref">
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
