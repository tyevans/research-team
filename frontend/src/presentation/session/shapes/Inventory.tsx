import { useState } from 'react'

import type { InventoryArtifact } from '@domain/conversation/artifact.ts'

import { bytes } from '../../formatting/format.ts'
import { Bar, Expander, Header, Item, Row, compact, type ShapeProps } from './parts.tsx'

const CAP = 5

/** What is in the corpus, sized.
 *
 * `unit` travels on the artifact rather than per item, and the rendering
 * depends on it: a list mixing characters and bytes on one bar axis is the
 * multi-column-grid mistake in miniature — two marks that look comparable and
 * are not. */
export const Inventory = ({ artifact, phase, tool }: ShapeProps<InventoryArtifact>) => {
  const [expanded, setExpanded] = useState(false)
  const items = [...artifact.items].sort((a, b) => b.size - a.size)
  const shown = expanded ? items : items.slice(0, CAP)
  const hidden = items.length - shown.length
  const max = items[0]?.size ?? 0
  const size = (n: number) => (artifact.unit === 'bytes' ? bytes(n) : compact(n))

  return (
    <Row glyph="▦" phase={phase}>
      <Header
        name={tool ?? 'list_sources'}
        arg={artifact.kind}
        count={`${artifact.total} item${artifact.total === 1 ? '' : 's'}`}
      />
      <div className="stream-list">
        {shown.map((item) => (
          <Item
            key={item.item_id}
            testId="inventory-item"
            name={item.title ?? item.item_id}
            detail={item.label ?? item.detail}
            mark={<Bar value={item.size} max={max} />}
            value={size(item.size)}
          />
        ))}
      </div>
      {hidden > 0 ? (
        <Expander
          expanded={expanded}
          onToggle={() => setExpanded((open) => !open)}
          label={expanded ? 'fewer' : `${hidden} more`}
        />
      ) : null}
    </Row>
  )
}
