import type { DelegationArtifact } from '@domain/conversation/artifact.ts'

import { Header, Item, Row, percent, type Phase } from './parts.tsx'

/** Every worker on one wall-clock axis against the turn.
 *
 * The point is what it makes visible without being read: a fan-out that
 * silently serialised draws as a staircase, where four rows that each report a
 * plausible duration say nothing at all. `started_ms` is relative to the turn
 * for the same reason — an absolute clock would make the renderer reason about
 * skew, and would make a replayed turn draw differently from a live one. */
export const Delegation = ({ artifact, phase }: { artifact: DelegationArtifact; phase: Phase }) => {
  // The axis is the turn so far, so a worker still running does not shrink the
  // scale of the ones that finished; `?? 0` treats an unfinished worker as
  // contributing only its start, which is all that is known about it.
  const span = artifact.workers.reduce(
    (widest, worker) => Math.max(widest, worker.started_ms + (worker.duration_ms ?? 0)),
    0,
  )

  return (
    <Row glyph="⑂" phase={phase}>
      <Header
        name="ask_agent"
        arg={artifact.task}
        count={`${artifact.workers.length} worker${artifact.workers.length === 1 ? '' : 's'}`}
      />
      <div className="stream-list">
        {artifact.workers.map((worker) => (
          <Item
            key={worker.name}
            testId="worker"
            name={worker.name}
            linked={worker.ok}
            mark={
              <span className="stream-track">
                <i
                  data-testid="worker-bar"
                  data-running={String(worker.duration_ms === null)}
                  data-ok={String(worker.ok)}
                  style={{
                    left: `${percent(worker.started_ms, span)}%`,
                    // A worker still running is pinned to the axis's live edge
                    // rather than given a width, because its width is the one
                    // thing not known: `duration_ms` is null precisely because
                    // nothing has measured it. Drawing it as zero-width would
                    // read as "returned immediately", which is the opposite of
                    // true — and `min-width` in the stylesheet keeps the
                    // newest worker, whose start *is* the edge, visible.
                    ...(worker.duration_ms === null
                      ? { right: '0%' }
                      : { width: `${percent(worker.duration_ms, span)}%` }),
                  }}
                />
              </span>
            }
            value={worker.duration_ms === null ? '…' : `${(worker.duration_ms / 1000).toFixed(1)}s`}
          />
        ))}
      </div>
    </Row>
  )
}
