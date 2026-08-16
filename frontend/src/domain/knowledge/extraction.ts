/** Where one `remember` call has got to.
 *
 * Provisional: nothing durable records these stages, so a reconnect refetches
 * them from the catch-up route rather than replaying them off the feed. The
 * graph's own record is `DocumentExtracted` and `EntitiesMerged`, and neither
 * is visible here.
 */
export type ExtractionStage =
  | 'storing'
  | 'extracting'
  | 'extracted'
  | 'consolidating'
  | 'consolidated'
  | 'failed'
  // Perception's two, and they are on this union rather than on one of their
  // own because the server put them on `ExtractionStage` -- a transcription is
  // a second slow thing happening to a source row, reported through
  // `ExtractionActivity` and waiting in the same queue. `perceived` is
  // terminal; a perception that fails reports `failed`, like an extraction
  // that does.
  //
  // Three client-side lists mirror the server's literal and all three have to
  // learn a stage together: this union, `STAGES` in `mappers.ts`, and
  // `TERMINAL` in `extraction-store.ts`. Missing the first two is not a type
  // error -- `toStage` falls back to `extracting` for anything it does not
  // recognise -- so a finished transcription simply reads as "extracting"
  // forever, which is what shipped between the server learning these and this
  // line being written.
  | 'perceiving'
  | 'perceived'

export interface ExtractionFrame {
  readonly type: 'Extraction'
  readonly projectId: string
  readonly sourceId: string
  readonly stage: ExtractionStage
  readonly detail: string
  readonly entities: number | null
  readonly relationships: number | null
  readonly domain: string | null
  /** `0` means the classifier gave up and fell back; `null` means none ran.
   *  Kept distinct because a fallback presented as a decision is the one
   *  misreading this field exists to prevent. */
  readonly domainConfidence: number | null
  readonly index: number | null
  readonly total: number | null
  readonly modelCalls: number | null
}

export interface StageEntry {
  readonly stage: ExtractionStage
  readonly detail: string
}

export interface Extraction {
  readonly sourceId: string
  readonly stage: ExtractionStage | null
  readonly stages: readonly StageEntry[]
  readonly entities: number | null
  readonly relationships: number | null
  readonly domain: string | null
  readonly domainConfidence: number | null
  readonly index: number | null
  readonly total: number | null
  readonly modelCalls: number | null
  /** Every consolidation line, in arrival order: the entity being considered,
   *  then the verdict and its reason. The judgement is the interesting part of
   *  an ingest, so it is kept in full rather than counted. */
  readonly merges: readonly string[]
  readonly failed: boolean
}

export const emptyExtraction = (sourceId: string): Extraction => ({
  sourceId,
  stage: null,
  stages: [],
  entities: null,
  relationships: null,
  domain: null,
  domainConfidence: null,
  index: null,
  total: null,
  modelCalls: null,
  merges: [],
  failed: false,
})

export const isExtractionFrame = (frame: unknown): boolean =>
  typeof frame === 'object' && frame !== null && (frame as { type?: unknown }).type === 'Extraction'

/** Fold one frame into an extraction.
 *
 * A stage is listed once even though `extracting` and `consolidating` each
 * arrive many times: the list is the shape of the work, and the repeats are
 * progress within a stage. `??` rather than `||` throughout, so a real `0`
 * count survives.
 */
export const applyNote = (extraction: Extraction, frame: ExtractionFrame): Extraction => {
  const known = extraction.stages.some((entry) => entry.stage === frame.stage)
  const stages = known
    ? extraction.stages.map((entry) =>
        entry.stage === frame.stage && frame.detail ? { ...entry, detail: frame.detail } : entry,
      )
    : [...extraction.stages, { stage: frame.stage, detail: frame.detail }]

  return {
    ...extraction,
    sourceId: frame.sourceId,
    stage: frame.stage,
    stages,
    entities: frame.entities ?? extraction.entities,
    relationships: frame.relationships ?? extraction.relationships,
    domain: frame.domain ?? extraction.domain,
    domainConfidence: frame.domainConfidence ?? extraction.domainConfidence,
    index: frame.index ?? extraction.index,
    total: frame.total ?? extraction.total,
    modelCalls: frame.modelCalls ?? extraction.modelCalls,
    merges:
      frame.stage === 'consolidating' && frame.detail
        ? [...extraction.merges, frame.detail]
        : extraction.merges,
    failed: extraction.failed || frame.stage === 'failed',
  }
}
