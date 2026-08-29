import { useState } from 'react'

import type { FileChangeArtifact } from '@domain/conversation/artifact.ts'

import { Bar, Expander, Header, Row, type ShapeProps } from './parts.tsx'

const PREVIEW = 300

/** How much of a file an edit touched, and then what it actually said.
 *
 * Today this renders as a summary string with each side cut to thirty
 * characters, which is short enough to be unreadable and long enough to look
 * like it is telling you something. The bar answers the question the summary
 * was trying to — *how much of this file moved* — and the before/after goes
 * behind an expander, because most edits are not the one the reader is
 * looking for. */
export const FileChange = ({ artifact, phase, tool }: ShapeProps<FileChangeArtifact>) => {
  const [expanded, setExpanded] = useState(false)
  const touched = artifact.added + artifact.removed
  const hasDiff = artifact.before !== null || artifact.after !== null
  const cut = (text: string) =>
    expanded || text.length <= PREVIEW ? text : `${text.slice(0, PREVIEW)}…`

  return (
    <Row glyph="±" phase={phase}>
      <Header
        name={tool ?? 'edit_file'}
        arg={artifact.path}
        title={artifact.path}
        count={
          <>
            <Bar value={touched} max={artifact.total_lines} />
            {`+${artifact.added} −${artifact.removed}`}
          </>
        }
      />
      {hasDiff ? (
        <div className="stream-diff" data-testid="diff">
          {artifact.before ? <div className="del">− {cut(artifact.before)}</div> : null}
          {artifact.after ? <div className="add">+ {cut(artifact.after)}</div> : null}
        </div>
      ) : null}
      {hasDiff && (artifact.before ?? '').length + (artifact.after ?? '').length > PREVIEW ? (
        <Expander
          expanded={expanded}
          onToggle={() => setExpanded((open) => !open)}
          label={expanded ? 'less' : 'full change'}
        />
      ) : null}
    </Row>
  )
}
