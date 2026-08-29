import { useState } from 'react'

import type { ExcerptArtifact } from '@domain/conversation/artifact.ts'

import { Expander, Header, Quote, Row, compact, percent, type ShapeProps } from './parts.tsx'

const PREVIEW = 400

/** What was read, and which part of the document it was.
 *
 * The ruler is the whole reason this shape exists. An agent quoting 9% of a
 * document from near its start is making a materially different claim from one
 * that read the whole thing, and `@1529-3872 of 25784` in a paragraph of
 * monospace does not distinguish them at a glance. */
export const Excerpt = ({ artifact, phase, tool }: ShapeProps<ExcerptArtifact>) => {
  const [expanded, setExpanded] = useState(false)
  const { start, end, char_count: total, text } = artifact
  const name = artifact.title ?? artifact.source_id
  const long = text.length > PREVIEW

  return (
    <Row shape="excerpt" phase={phase}>
      <Header
        name={tool ?? 'read_source'}
        arg={artifact.label ? `${name} · ${artifact.label}` : name}
        explanation={artifact.uri ?? artifact.source_id}
        count={
          <>
            <span className="inline-block h-[5px] w-[56px] overflow-hidden rounded-md bg-bg-raise align-middle [&>i]:block [&>i]:h-full [&>i]:bg-accent">
              <i
                data-testid="ruler-fill"
                style={{
                  marginLeft: `${percent(start, total)}%`,
                  width: `${percent(end - start, total)}%`,
                }}
              />
            </span>
            {`${compact(start)}–${compact(end)} of ${compact(total)}`}
          </>
        }
      />
      <Quote>{expanded || !long ? text : `${text.slice(0, PREVIEW)}…`}</Quote>
      {long ? (
        <Expander
          expanded={expanded}
          onToggle={() => setExpanded((open) => !open)}
          label={expanded ? 'less' : 'full excerpt'}
        />
      ) : null}
    </Row>
  )
}
