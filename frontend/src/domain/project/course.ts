import type { ProjectId, SessionId, SourceId } from '../shared/identifier.ts'

/** A workflow run against its plan.
 *
 * Every stage of the preset is here whether or not it has run, and every
 * artifact the preset declares is here whether or not it was written — because
 * a view built from what exists can only show what happened, and the question
 * this answers is what was *supposed* to.
 *
 * Nothing in this module judges. A missing artifact is missing, an empty
 * provenance block is empty, and neither is called a failure: the check library
 * owns verdicts, it runs on the server, and its findings arrive as `findings`
 * with the severities it assigned. A second opinion computed here would be the
 * one users actually saw.
 */
export interface Course {
  /** Carried on the aggregate rather than threaded through every component
   *  that needs it: a source link is addressed by project, and a view that had
   *  to be handed the id separately is a view that can be handed the wrong
   *  one. */
  readonly projectId: ProjectId
  readonly projectName: string
  /** An artifact is only readable through a session — that is where the file
   *  viewer lives. `null` says plainly that there is nothing to open it in. */
  readonly holdingSessionId: SessionId | null
  readonly preset: {
    readonly id: string
    readonly name: string
    readonly version: string | number | null
  }
  /** `null` when the project's recorded stage is not part of this preset. */
  readonly position: number | null
  readonly stageCount: number
  readonly stages: readonly StageProgress[]
  readonly findings: readonly Finding[]
  /** Declared checks that nothing implements: a guarantee the preset claims and
   *  nothing provides. Silence about these is worse than declaring none. */
  readonly unimplementedChecks: readonly string[]
}

export type StageStatus = 'done' | 'current' | 'todo' | (string & {})

export interface StageProgress {
  readonly index: number
  readonly id: string
  readonly name: string
  readonly kind: string
  readonly spine: number
  readonly scopeLevel: string
  readonly status: StageStatus
  readonly outputs: readonly ArtifactSlot[]
  /** What a human is allowed to answer at this stage's gate. `halt` is worth
   *  seeing in advance: the pipeline is structurally biased toward producing
   *  its own output, and the gates that can stop it are the counterweight. */
  readonly gateDecisions: readonly string[]
  readonly reviewerRole: string | null
  readonly findingsReport: string | null
}

/** One artifact a stage declares.
 *
 * Four states, which a naive row flattens into two: missing; present with no
 * readable frontmatter; present and claiming sources; present and claiming its
 * thinking was the model's own. The last two are both legitimate and must not
 * look alike, and an artifact claiming *neither* is the one shape the contract
 * calls never right.
 */
export interface ArtifactSlot {
  readonly path: string
  readonly artifactType: string
  readonly subtype: string | null
  readonly cardinality: string
  readonly stageId: string
  readonly present: boolean
  readonly hasFrontmatter: boolean
  readonly missingFields: readonly string[]
  readonly provenance: Provenance | null
  readonly bodyChars: number
}

export interface Provenance {
  readonly sources: readonly SourceSpan[]
  /** Not a defect: a stage whose reasoning is its own and says so is working as
   *  designed. The flag is here so a reviewer can weigh it. */
  readonly inferred: boolean
  readonly unreadable: number
  /** Neither a source nor an admission of inference — indistinguishable from an
   *  artifact never checked against anything. Computed server-side precisely so
   *  a client cannot rederive it wrongly. */
  readonly empty: boolean
}

export interface SourceSpan {
  readonly sourceId: SourceId
  readonly start: number | null
  readonly end: number | null
}

export type FindingSeverity =
  'invariant' | 'blocking' | 'advisory' | 'human_gate' | 'critic_gate' | (string & {})

export interface Finding {
  readonly check: string
  readonly severity: FindingSeverity
  readonly message: string
  readonly cites: readonly string[]
  readonly suggestedEdit: string | null
}

/** `human_gate` and `critic_gate` are not defects: they mark work no run can
 *  clear by itself. Spelling them out keeps a reader from filing them with the
 *  failures just because they arrived in the same list. */
export const severityLabel = (severity: FindingSeverity): string =>
  SEVERITY_LABELS[severity] ?? severity

const SEVERITY_LABELS: Readonly<Record<string, string>> = {
  invariant: 'invariant',
  blocking: 'blocking',
  advisory: 'advisory',
  human_gate: 'needs a person',
  critic_gate: 'needs a critic pass',
}

export const allArtifacts = (course: Course): readonly ArtifactSlot[] =>
  course.stages.flatMap((stage) => stage.outputs)

/** Written-of-declared, never a percentage: a stage owing two artifacts with
 *  one written is a specific situation, and "50%" is not. */
export const writtenCount = (slots: readonly ArtifactSlot[]): number =>
  slots.filter((slot) => slot.present).length

export const formatSpan = (span: SourceSpan): string =>
  span.start === null || span.end === null
    ? span.sourceId
    : `${span.sourceId}@${span.start}-${span.end}`
