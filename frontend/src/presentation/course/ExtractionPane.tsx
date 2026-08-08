import { useEffect, useMemo } from 'react'

import { createExtractionStore } from '@application/knowledge/extraction-store.ts'
import { useContainer } from '@app/container-context.tsx'
import type { Extraction } from '@domain/knowledge/extraction.ts'
import type { ProjectId } from '@domain/shared/identifier.ts'

import { useStream } from '../shell/StreamProvider.tsx'

/** `remember`, while it is still happening.
 *
 * The roster row above says an extraction is running; this says what it is
 * doing. That split is the point — a run can spend minutes inside one
 * `remember` call, and until this pane existed the only honest thing the
 * console could say about those minutes was "extraction".
 *
 * Builds **its own** store, keyed to this project, rather than reading a
 * shared one: `createExtractionStore` is a factory, and the store's first job
 * is discarding frames addressed to other projects. The live feed is
 * application-wide and fanned out to every listener, so without that filter
 * one course page would render another course's extraction.
 *
 * `catchUp()` runs on mount **and on every reconnect**. It is the only
 * recovery there is: these frames carry no feed position, `Last-Event-ID`
 * cannot replay them, and a socket that dropped mid-ingest would otherwise
 * leave this pane stopped on whatever frame arrived last — which on screen is
 * indistinguishable from an extraction that has hung.
 */
export const ExtractionPane = ({ projectId }: { projectId: ProjectId }) => {
  const { extractions } = useContainer()
  const stream = useStream()

  const store = useMemo(
    () => createExtractionStore({ extractions, projectId }),
    [extractions, projectId],
  )

  useEffect(() => {
    // Swallowed rather than surfaced: a build whose server has no extraction
    // route should render "nothing has run", not an error banner over a page
    // whose other panels are fine.
    void store.getState().catchUp().catch(noop)
  }, [store])

  useEffect(
    () =>
      stream.onFrame((frame) => {
        if (frame.kind === 'extraction') store.getState().handleFrame(frame.payload)
      }),
    [stream, store],
  )

  useEffect(
    () => stream.onReconnect(() => void store.getState().catchUp().catch(noop)),
    [stream, store],
  )

  const { current, last } = store()

  return (
    <section className="extraction" aria-label="Knowledge extraction">
      <h3 className="extraction-title">Reading into the graph</h3>

      {!current && !last ? (
        <p className="sub extraction-sub">No extraction has run on this project yet.</p>
      ) : null}

      {current ? <Running extraction={current} /> : null}
      {last ? <Last extraction={last} /> : null}
    </section>
  )
}

const noop = () => {}

/** The stages so far, with the one in flight marked.
 *
 * A list rather than a percentage: the stages are not equal in length —
 * `extracting` is a model call per chunk and `consolidating` a decision per
 * entity — so any bar drawn over them would be a made-up number. Naming the
 * stage and counting inside it says only what is known.
 */
const Running = ({ extraction }: { extraction: Extraction }) => {
  // `extracted` having *arrived* is what makes the counts real, not the counts
  // being non-null: they carry forward from frame to frame once set, and
  // showing them before that stage would show them as zero-ish gaps.
  const counted = extraction.stages.some((entry) => entry.stage === 'extracted')
  const confidence = confidenceText(extraction.domainConfidence)

  return (
    <div className="extraction-running">
      <ol className="extraction-stages">
        {extraction.stages.map((entry) => {
          const now = entry.stage === extraction.stage
          return (
            <li
              key={entry.stage}
              className={now ? 'extraction-stage extraction-now' : 'extraction-stage'}
              aria-current={now ? 'step' : undefined}
            >
              {entry.stage}
            </li>
          )
        })}
      </ol>

      {extraction.stage === 'extracting' && extraction.modelCalls !== null ? (
        <p className="extraction-line">model calls: {extraction.modelCalls}</p>
      ) : null}

      {counted ? (
        <p className="extraction-line">
          {extraction.entities ?? 0} entities · {extraction.relationships ?? 0} relationships
          {extraction.domain ? ` · ${extraction.domain}` : ''}
          {confidence ? ` (${confidence})` : ''}
        </p>
      ) : null}

      {extraction.total !== null ? (
        <div className="extraction-merges">
          <p className="extraction-line">
            consolidating {extraction.index ?? 0}/{extraction.total}
          </p>
          <ul className="extraction-merge-list">
            {extraction.merges.map((line, at) => (
              // Indexed because the same verdict can legitimately repeat and
              // the line is all there is; the list only ever grows at the end.
              <li key={`${at}-${line}`} className="extraction-merge">
                {line}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </div>
  )
}

/** The last finished extraction, collapsed.
 *
 * Kept rather than cleared on completion for the reason the server keeps the
 * frames: nothing durable records these stages, so this is the only account of
 * what just happened. Collapsed because it is history, and open by default it
 * would compete with the extraction actually running.
 */
const Last = ({ extraction }: { extraction: Extraction }) => (
  <details className={extraction.failed ? 'extraction-last extraction-failed' : 'extraction-last'}>
    <summary className="extraction-summary">
      {extraction.failed ? 'The last extraction failed' : 'Last extraction'} · {extraction.sourceId}
    </summary>
    <p className="extraction-line">
      {extraction.entities ?? 0} entities · {extraction.relationships ?? 0} relationships
      {extraction.domain ? ` · ${extraction.domain}` : ''}
      {confidenceText(extraction.domainConfidence)
        ? ` (${confidenceText(extraction.domainConfidence)})`
        : ''}
    </p>
    {extraction.failed ? (
      <p className="extraction-line extraction-failed-detail">{failureDetail(extraction)}</p>
    ) : null}
  </details>
)

const failureDetail = (extraction: Extraction): string =>
  extraction.stages.find((entry) => entry.stage === 'failed')?.detail ?? 'No reason was reported.'

/** Three outcomes, not two.
 *
 * `null` means no classifier ran and there is nothing to say, so nothing is
 * said. `0` means one ran and gave up — rendered as `0.00` that reads as a
 * confident low score, which is the exact misreading this distinction exists
 * to prevent, so it is spelled out in words instead.
 */
const confidenceText = (value: number | null): string | null => {
  if (value === null) return null
  if (value === 0) return 'fallback — treat the shape as unverified'
  return value.toFixed(2)
}
