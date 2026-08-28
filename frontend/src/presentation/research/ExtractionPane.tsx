import { useEffect, useMemo, useState } from 'react'

import { createExtractionStore } from '@application/knowledge/extraction-store.ts'
import { useContainer } from '@app/container-context.tsx'
import type { Extraction } from '@domain/knowledge/extraction.ts'
import type { ProjectId } from '@domain/shared/identifier.ts'

import { Disclosure } from '../common/primitives.tsx'
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
export const ExtractionPane = ({
  projectId,
  onRunning,
}: {
  projectId: ProjectId
  /** Called with whether a run is in flight, so the surface *behind* this
   *  float can stop calling the graph empty while it is being filled. A
   *  callback rather than hoisting the store: the store is built per project
   *  per mount by design, and lifting it would mean either two subscriptions
   *  or threading a zustand instance through a component whose other props
   *  are all plain data. */
  onRunning?: (running: boolean) => void
}) => {
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

  // `setExtracting` (the only caller today) is a stable `useState` setter
  // identity, so this does not loop -- the effect re-runs only when `current`
  // itself changes between null and set.
  useEffect(() => {
    onRunning?.(current !== null)
  }, [current, onRunning])

  return <ExtractionView current={current} last={last} />
}

const noop = () => {}

/** What an extraction looks like, given one somebody else is following.
 *
 * Separated from the subscription above so the three states are reachable
 * without a live feed: nothing has ever run, one is running, one has
 * finished -- and the fourth, a finished run *and* a new one already going,
 * which is the layout most likely to be wrong and was the hardest to reach.
 * `current` and `last` are independent for that reason rather than a single
 * `Extraction | null` with a status on it.
 */
export const ExtractionView = ({
  current,
  last,
}: {
  /** The run in flight, if there is one. */
  current: Extraction | null
  /** The most recent finished run, if there has been one. */
  last: Extraction | null
}) => {
  // Nothing has ever run, so this draws nothing. The claim it used to make —
  // "No extraction has run on this project yet." — is the same one the graph
  // stage's own empty state makes, and this now floats over that stage. Two
  // elements saying it is one too many; the stage keeps it, because that is
  // where a reader looking at an empty graph is already looking.
  if (!current && !last) return null

  return (
    <section className="extraction" aria-label="Knowledge extraction">
      {current ? <Running extraction={current} /> : null}
      {last ? <Last extraction={last} /> : null}
    </section>
  )
}

/** The stages so far, with the one in flight marked.
 *
 * A list rather than a percentage: the stages are not equal in length —
 * `extracting` is a model call per chunk and `consolidating` a decision per
 * *batch* of entities — so any bar drawn over them would be a made-up number.
 * Naming the stage and counting inside it says only what is known.
 *
 * The consolidating counter moves a batch at a time and then holds while the
 * adjudicator is asked about the whole batch at once. It looks stalled and is
 * not; that is the cost of batching those calls, and it is why the count is
 * `index/total` over entities rather than a bar that would appear to freeze.
 */
const Running = ({ extraction }: { extraction: Extraction }) => {
  // `extracted` having *arrived* is what makes the counts real, not the counts
  // being non-null: they carry forward from frame to frame once set, and
  // showing them before that stage would show them as zero-ish gaps.
  const counted = extraction.stages.some((entry) => entry.stage === 'extracted')
  const confidence = confidenceText(extraction.domainConfidence)

  return (
    <div className="extraction-running">
      <p className="extraction-status">
        <span className="extraction-dot" aria-hidden="true" />
        <span className="extraction-stage-name">{extraction.stage ?? 'starting'}</span>
        {extraction.total !== null ? (
          <span className="extraction-count">
            {extraction.index ?? 0}/{extraction.total}
          </span>
        ) : null}
      </p>

      {/* A trail, not a track: `Extraction.stages` is the stages *reached*,
          appended as frames arrive, and there is no declared pipeline to draw
          the rest of. `ExtractionStage` carries perception's two alongside
          extraction's five plus `failed`, which can follow any of them — so a
          fixed set of segments would draw a transcription as an extraction
          that had skipped four steps. It grows rather than fills, and it still
          measures nothing: a bar over stages of unequal length would be a
          made-up number, which is what the pill list this replaces was already
          right about. */}
      <ol className="extraction-trail">
        {extraction.stages.map((entry) => {
          const now = entry.stage === extraction.stage
          return (
            <li
              key={entry.stage}
              className={now ? 'extraction-seg extraction-seg-now' : 'extraction-seg'}
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
          {/* Kept alongside the status line's own count rather than folded
              into it: `total` is set whenever the server has a denominator at
              all, not only once `stage` reaches `consolidating` (see the
              `RunningWithoutADomain` story, which sets it at `extracting`), so
              the status line's count is the *general* one and this restates
              it labelled as consolidation specifically -- the two agree when
              the stages coincide and this is the only place saying which pass
              the count belongs to when they don't. */}
          <p className="extraction-line">
            consolidating {extraction.index ?? 0}/{extraction.total}
          </p>
          <MergeList merges={extraction.merges} />
        </div>
      ) : null}
    </div>
  )
}

/** What consolidation decided, entity by entity.
 *
 * Shared by the running section and the finished one, which is the whole
 * change: it used to live inline in `Running`, so every verdict vanished at the
 * moment the run finished and the disclosure that calls itself "the only
 * account of what just happened" accounted for none of it. A reader who looked
 * away for the minute the ingest took saw nothing at all.
 */
const MergeList = ({ merges }: { merges: readonly string[] }) =>
  merges.length === 0 ? null : (
    <ul className="extraction-merge-list">
      {merges.map((line, at) => (
        // Indexed because the same verdict can legitimately repeat and the line
        // is all there is; the list only ever grows at the end.
        <li key={`${at}-${line}`} className="extraction-merge">
          {line}
        </li>
      ))}
    </ul>
  )

/** The last finished extraction, collapsed.
 *
 * Kept rather than cleared on completion for the reason the server keeps the
 * frames: nothing durable records these stages, so this is the only account of
 * what just happened. Collapsed because it is history, and open by default it
 * would compete with the extraction actually running.
 */
const Last = ({ extraction }: { extraction: Extraction }) => {
  // `Disclosure` rather than the `<details>` this was. Here the controlled
  // state earns itself rather than only tidying up: this pane is driven by a
  // live frame subscription and re-renders whenever anything extracts, and the
  // open state now lives in React where a parent can hold it across the
  // remount that a *new* last-extraction causes. `<details>` could not be
  // handed that, which is the S-D14 shape.
  const [open, setOpen] = useState(false)
  return (
    <Disclosure
      className={extraction.failed ? 'extraction-last extraction-failed' : 'extraction-last'}
      open={open}
      onToggle={() => {
        setOpen((was) => !was)
      }}
      label={
        <span className="extraction-summary">
          {extraction.failed ? 'The last extraction failed' : 'Last extraction'} ·{' '}
          {extraction.sourceId}
        </span>
      }
    >
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
      {/* Behind the disclosure rather than beside the counts, so history still
          loses to a run in flight on a page they share -- the reason this
          section is collapsed at all. Rendered on a failed extraction too: a
          run that fell over after consolidating some of its entities decided
          those, and the failure detail says nothing about them. */}
      <MergeList merges={extraction.merges} />
    </Disclosure>
  )
}

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
