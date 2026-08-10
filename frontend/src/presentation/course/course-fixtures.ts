import type { ArtifactSlot, Course, StageProgress } from '@domain/project/course.ts'
import { ProjectId, SourceId } from '@domain/shared/identifier.ts'

/** A course to draw, shared by the stories for both panes.
 *
 * One fixture rather than one per story file, because the two panes render two
 * halves of the *same* course and a reader comparing them should be looking at
 * one project. Two fixtures would drift into describing two, which is exactly
 * the confusion the course page exists to remove.
 *
 * Not a test helper that stories borrow: it is imported by both, so it lives
 * apart from either and neither owns it.
 */
export const PROJECT = ProjectId('11111111-1111-1111-1111-111111111111')

export const artifact = (over: Partial<ArtifactSlot> = {}): ArtifactSlot => ({
  path: 'course/intake/brief.md',
  artifactType: 'brief',
  subtype: null,
  cardinality: 'one',
  stageId: 'step0.intake',
  present: true,
  hasFrontmatter: true,
  missingFields: [],
  bodyChars: 4_210,
  provenance: {
    sources: [{ sourceId: SourceId('aaaaaaaa-1111-2222-3333-444444444444'), start: 0, end: 420 }],
    inferred: false,
    unreadable: 0,
    empty: false,
  },
  ...over,
})

export const stage = (over: Partial<StageProgress> = {}): StageProgress => ({
  index: 1,
  id: 'step0.intake',
  name: 'Intake',
  kind: 'author',
  spine: 0,
  scopeLevel: 'course',
  status: 'done',
  outputs: [artifact()],
  gateDecisions: [],
  reviewerRole: null,
  findingsReport: null,
  ...over,
})

export const course = (over: Partial<Course> = {}): Course => {
  const stages: readonly StageProgress[] = over.stages ?? [
    stage(),
    stage({
      index: 2,
      id: 'step1.framing',
      name: 'Framing',
      status: 'current',
      outputs: [
        artifact({ path: 'course/framing/outline.md', artifactType: 'outline' }),
        artifact({
          path: 'course/framing/objectives.md',
          artifactType: 'objectives',
          present: false,
        }),
      ],
      gateDecisions: ['approve', 'revise', 'halt'],
      reviewerRole: 'editor',
      findingsReport: 'course/framing/findings.md',
    }),
    stage({
      index: 3,
      id: 'step2.draft',
      name: 'Draft',
      status: 'pending',
      outputs: [
        artifact({ path: 'course/draft/lesson.md', artifactType: 'lesson', present: false }),
      ],
    }),
    stage({ index: 4, id: 'step3.review', name: 'Review', status: 'pending', outputs: [] }),
  ]

  return {
    projectId: PROJECT,
    projectName: 'Spacing',
    holdingSessionId: null,
    preset: { id: 'hybrid.default', name: 'Hybrid', version: '1' },
    position: 2,
    stageCount: stages.length,
    stages,
    findings: [],
    unimplementedChecks: [],
    ...over,
    // After the spread, so a caller overriding `stages` gets a matching count
    // rather than the default's. The pair disagreeing is how a "3 of 4" over a
    // list of six gets written.
    ...(over.stages ? { stageCount: over.stages.length } : {}),
  }
}
