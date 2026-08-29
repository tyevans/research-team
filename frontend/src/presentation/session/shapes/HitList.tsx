import { useState } from 'react'

import type { HitListArtifact } from '@domain/conversation/artifact.ts'

import { Expander, Header, Item, Quote, Row, Sparkline, type ShapeProps } from './parts.tsx'

const CAP = 5

/** Where a pattern lives in the corpus, before what it says.
 *
 * The card answers the question a reader actually has in front of nineteen
 * matches — *which document holds the weight* — with a sparkline per source
 * positioning every hit against that document's own length, and a count. One
 * representative snippet goes below, because nineteen snippets is the wall of
 * text this design replaces. */
export const HitList = ({ artifact, phase, tool }: ShapeProps<HitListArtifact>) => {
  const [expanded, setExpanded] = useState(false)
  const sources = [...artifact.sources].sort((a, b) => b.total - a.total)
  const shown = expanded ? sources : sources.slice(0, CAP)
  const hidden = sources.length - shown.length
  const snippet = sources.flatMap((source) => source.hits)[0]?.snippet ?? null

  return (
    <Row shape="hit_list" phase={phase}>
      <Header
        name={tool ?? 'search_sources'}
        arg={`/${artifact.pattern}/`}
        count={`${artifact.total} in ${sources.length} source${sources.length === 1 ? '' : 's'}`}
      />
      <div className="mt-[3px]">
        {shown.map((source) => (
          <Item
            key={source.source_id}
            testId="hit-source"
            name={source.title ?? source.source_id}
            detail={source.label}
            mark={
              <Sparkline
                positions={source.hits.map((hit) => hit.start)}
                total={source.char_count}
              />
            }
            value={source.total}
          />
        ))}
      </div>
      {snippet ? <Quote>{snippet}</Quote> : null}
      {/* The cap does a second job beyond height: a forty-match result cannot
          bury the reply beneath it. `suppressed` is what the tool dropped
          before it ever reached the wire, and it is named separately because
          "we showed you four of eleven" and "there were eleven" are different
          facts and the reader needs both. */}
      {hidden > 0 || artifact.suppressed > 0 ? (
        <Expander
          expanded={expanded}
          onToggle={() => setExpanded((open) => !open)}
          label={
            expanded
              ? 'fewer sources'
              : `all ${artifact.total} matches${hidden > 0 ? ` · ${hidden} more source${hidden === 1 ? '' : 's'}` : ''}${
                  artifact.suppressed > 0 ? ` · ${artifact.suppressed} suppressed` : ''
                }`
          }
        />
      ) : null}
    </Row>
  )
}
