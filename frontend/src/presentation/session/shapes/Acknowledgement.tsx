import type { AcknowledgementArtifact } from '@domain/conversation/artifact.ts'

import { Row, type Phase } from './parts.tsx'

/** One line, no chrome, no expander.
 *
 * These are the stream's punctuation. Giving a write the same weight as a
 * search result is most of what makes the current feed read as noise, so this
 * shape deliberately has nothing to open and nothing to measure — and the test
 * that asserts there is no button is asserting a design decision, not an
 * implementation detail. */
export const Acknowledgement = ({
  artifact,
  phase,
}: {
  artifact: AcknowledgementArtifact
  phase: Phase
}) => (
  // The only shape that overrides its registry glyph, and only in one
  // direction: a write that failed is a state of the result, not a shape of
  // its own, so `SHAPE_GLYPH` holds the success mark and the failure mark is
  // named here beside the `tone` that colours it.
  <Row
    shape="acknowledgement"
    {...(artifact.ok ? {} : { glyph: '✗' })}
    phase={phase}
    tone={artifact.ok ? 'ok' : 'fail'}
  >
    <span className="stream-ack" data-testid="ack" data-ok={String(artifact.ok)}>
      {artifact.action} — <b>{artifact.subject}</b>
      {artifact.detail ? ` · ${artifact.detail}` : null}
    </span>
  </Row>
)
