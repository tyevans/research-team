import { useState } from 'react'

import type { EntityListArtifact, EntityRef } from '@domain/conversation/artifact.ts'

import { BAR_CLASS, Bar, Expander, Header, Item, Row, type ShapeProps } from './parts.tsx'

const CAP = 5

const byCount = (a: EntityRef, b: EntityRef) =>
  b.relationship_count - a.relationship_count || a.name.localeCompare(b.name)

/** What the graph returned, ordered by how connected it is.
 *
 * Two decisions carry this card:
 *
 * **Sorted by relationship count**, because the count is the only thing on the
 * row that says whether the graph actually knows anything about the entity,
 * and alphabetical order buries that under the letter A.
 *
 * **Unlinked entities sit below a rule and read `–`, not `0`.** An entity the
 * graph knows by name and has connected to nothing is the most actionable fact
 * a `graph_search` returns, and in the paragraph this replaces it was the least
 * visible thing on screen. `0` reads as a measurement; `–` reads as the absence
 * it is. */
export const EntityList = ({ artifact, phase, tool }: ShapeProps<EntityListArtifact>) => {
  const [expanded, setExpanded] = useState(false)
  const linked = artifact.entities.filter((e) => e.relationship_count > 0).sort(byCount)
  const unlinked = artifact.entities.filter((e) => e.relationship_count <= 0).sort(byCount)
  const max = linked[0]?.relationship_count ?? 0

  // **The cap is on the linked group, and the unlinked group appears only once
  // nothing linked is hidden.** It used to be one budget of five spent by the
  // linked entities first, which reads as obviously right and starves the half
  // the card exists to surface: five linked entities and one unlinked is the
  // ordinary shape of a `graph_search` result, and it left `CAP - 5 = 0` lines
  // for the orphan — so the most actionable row on the card was the one it
  // never drew. Three tests said six rows, the docstring above calls the
  // orphan the most actionable fact this tool returns, and the shipped
  // arithmetic agreed with neither.
  //
  // The rule that replaces it is a statement about the reader rather than
  // about height: someone who has not yet seen every *connected* entity is not
  // helped by the unconnected ones, and someone who has seen them all has
  // nothing better left to look at. So a truncated linked group hides the
  // unlinked entirely and says so on the expander, and a complete one lets
  // them through — capped at `CAP` themselves, so a query matching forty
  // orphans still cannot bury the reply.
  //
  // The cost, since it is real: the card is now up to ten rows rather than
  // five. That is the trade the old arithmetic was making silently in the
  // other direction.
  const shownLinked = expanded ? linked : linked.slice(0, CAP)
  const hidLinked = linked.length > shownLinked.length
  const shownUnlinked = expanded ? unlinked : hidLinked ? [] : unlinked.slice(0, CAP)
  const moreLinked = linked.length - shownLinked.length
  const moreUnlinked = unlinked.length - shownUnlinked.length

  const label = [
    moreLinked > 0 ? `${moreLinked} more` : null,
    moreUnlinked > 0 ? `${moreUnlinked} unlinked` : null,
  ]
    .filter(Boolean)
    .join(' · ')

  return (
    <Row shape="entity_list" phase={phase}>
      <Header
        name={tool ?? 'graph_search'}
        arg={`“${artifact.query}”`}
        count={`${artifact.entities.length} entit${artifact.entities.length === 1 ? 'y' : 'ies'}`}
        explanation={artifact.mode}
      />
      <div className="mt-[3px]">
        {shownLinked.map((entity) => (
          <Item
            key={entity.entity_id}
            testId="entity"
            name={entity.name}
            detail={entity.entity_type}
            mark={<Bar value={entity.relationship_count} max={max} />}
            value={entity.relationship_count}
          />
        ))}
        {shownUnlinked.length > 0 ? <div className="my-[4px] h-px bg-line-soft" /> : null}
        {shownUnlinked.map((entity) => (
          <Item
            key={entity.entity_id}
            testId="entity"
            name={entity.name}
            detail={entity.entity_type}
            linked={false}
            // An empty track rather than a zero-width fill. A fill of width
            // zero is still a bar, and a bar drawn for a value that does not
            // exist puts the entity on an axis it is not on.
            mark={<span className={BAR_CLASS} data-testid="bar" />}
            value="–"
          />
        ))}
      </div>
      {label ? (
        <Expander
          expanded={expanded}
          onToggle={() => setExpanded((open) => !open)}
          label={expanded ? 'fewer' : label}
        />
      ) : null}
    </Row>
  )
}
