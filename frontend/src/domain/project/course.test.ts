import { describe, expect, it } from 'vitest'

import { ProjectId, SessionId, SourceId } from '../shared/identifier.ts'
import {
  allArtifacts,
  formatSpan,
  severityLabel,
  writtenCount,
  type ArtifactSlot,
  type Course,
  type StageProgress,
} from './course.ts'
import { hasResolvedStage, isHeld, type Project } from './project.ts'

const slot = (path: string, present: boolean): ArtifactSlot => ({
  path,
  artifactType: 'SourceClaim',
  subtype: null,
  cardinality: '1..n',
  stageId: 'st',
  present,
  hasFrontmatter: present,
  missingFields: [],
  provenance: null,
  bodyChars: 0,
})

const stage = (id: string, outputs: ArtifactSlot[]): StageProgress => ({
  index: 1,
  id,
  name: id,
  kind: 'course',
  spine: 1,
  scopeLevel: 'course',
  status: 'todo',
  outputs,
  gateDecisions: [],
  reviewerRole: null,
  findingsReport: null,
})

const course = (stages: StageProgress[]): Course => ({
  projectId: ProjectId('p1'),
  projectName: 'Knitting',
  holdingSessionId: null,
  preset: { id: 'hybrid', name: 'Hybrid', version: 1 },
  position: 1,
  stageCount: stages.length,
  stages,
  findings: [],
  unimplementedChecks: [],
})

describe('severityLabel', () => {
  it('spells out the two that are not defects', () => {
    // They mark work no run can clear by itself. Spelling them out keeps a
    // reader from filing them with the failures just because they arrived in
    // the same list.
    expect(severityLabel('human_gate')).toBe('needs a person')
    expect(severityLabel('critic_gate')).toBe('needs a critic pass')
  })

  it('passes the real severities through unchanged', () => {
    expect(severityLabel('blocking')).toBe('blocking')
    expect(severityLabel('invariant')).toBe('invariant')
  })

  it('shows an unknown severity rather than hiding it', () => {
    expect(severityLabel('something_new')).toBe('something_new')
  })
})

describe('allArtifacts', () => {
  it('flattens every stage’s declared outputs, in stage order', () => {
    const flat = allArtifacts(
      course([stage('a', [slot('/1.md', true)]), stage('b', [slot('/2.md', false)])]),
    )
    expect(flat.map((s) => s.path)).toEqual(['/1.md', '/2.md'])
  })

  it('is empty for a preset that declares no outputs', () => {
    expect(allArtifacts(course([stage('a', [])]))).toEqual([])
  })
})

describe('writtenCount', () => {
  it('counts what landed, not what was declared', () => {
    expect(writtenCount([slot('/1.md', true), slot('/2.md', false), slot('/3.md', true)])).toBe(2)
  })
})

describe('formatSpan', () => {
  it('shows the offsets an artifact cites', () => {
    expect(formatSpan({ sourceId: SourceId('paper-1'), start: 0, end: 400 })).toBe('paper-1@0-400')
  })

  it('shows the source alone when it cites no span', () => {
    expect(formatSpan({ sourceId: SourceId('paper-1'), start: null, end: null })).toBe('paper-1')
  })

  it('treats a half-open citation as no span, since it cannot be checked', () => {
    expect(formatSpan({ sourceId: SourceId('p'), start: 5, end: null })).toBe('p')
  })
})

describe('Project', () => {
  const project = (over: Partial<Project> = {}): Project => ({
    id: ProjectId('p1'),
    name: 'Knitting',
    activeSessionId: null,
    tipAtEvent: 0,
    workflow: null,
    stage: null,
    ...over,
  })

  it('knows whether somebody is holding it, which decides what the row can offer', () => {
    expect(isHeld(project())).toBe(false)
    expect(isHeld(project({ activeSessionId: SessionId('s1') }))).toBe(true)
  })

  it('reports a preset this build does not ship as unresolved rather than guessing', () => {
    const unknown = project({ workflow: { id: 'gone', name: 'gone', version: null } })
    expect(hasResolvedStage(unknown)).toBe(false)
  })

  it('resolves a stage when the preset is known', () => {
    const known = project({
      workflow: { id: 'hybrid', name: 'Hybrid', version: 1 },
      stage: { id: 'hybrid.step1', name: 'Framing', index: 2, of: 15 },
    })
    expect(hasResolvedStage(known)).toBe(true)
  })
})
