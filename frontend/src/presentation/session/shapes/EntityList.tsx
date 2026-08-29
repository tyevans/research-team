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

  // The cap is on the card, not on either group, and linked entities take the
  // room first: a result whose interesting half is at the bottom has spent its
  // five lines on the half nobody asked about.
  const shownLinked = expanded ? linked : linked.slice(0, CAP)
  const shownUnlinked = expanded
    ? unlinked
    : unlinked.slice(0, Math.max(0, CAP - shownLinked.length))
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
