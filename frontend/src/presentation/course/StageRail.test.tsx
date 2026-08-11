import { render, screen } from '@testing-library/react'
import { expect, it } from 'vitest'

import type { Course, StageProgress } from '@domain/project/course.ts'
import { ProjectId } from '@domain/shared/identifier.ts'

import { Stage } from './StageRail.tsx'

/** What a rail row is called, for a reader who cannot see it.
 *
 * S-D3's second category. "4/6" and "—" are glyphs: the first is only a count
 * if you already know what is being counted, and the second is not even that.
 * Both carried a sentence in a `title`, which is announced on hover and is not
 * an accessible name — so a screen reader read "4 slash 6" and an em dash and
 * the sentence reached nobody.
 *
 * A `Tooltip` would not have fixed it and could not have been used: the row is
 * a `<button>` and `Tooltip`'s wrapper is another one, so the conversion here
 * is a name rather than an explanation. That distinction is the reason this
 * test asserts the *name* and not that some text appeared somewhere.
 */

const PROJECT = ProjectId('11111111-1111-1111-1111-111111111111')

const course: Course = {
  projectId: PROJECT,
  projectName: 'Spacing',
  holdingSessionId: null,
  workflowId: 'research',
  workflowName: 'Research',
  position: 1,
  stages: [],
} as unknown as Course

const stage = (over: Partial<StageProgress> = {}): StageProgress => ({
  index: 4,
  id: 'step4.draft',
  name: 'Draft',
  kind: 'author',
  spine: 0,
  scopeLevel: 'course',
  status: 'current',
  outputs: [],
  gateDecisions: [],
  reviewerRole: null,
  findingsReport: null,
  ...over,
})

const slot = (path: string, present: boolean) =>
  ({
    path,
    present,
    artifactType: 'report',
    subtype: null,
    cardinality: 'one',
    hasFrontmatter: present,
    missingFields: [],
    provenance: null,
  }) as unknown as StageProgress['outputs'][number]

it('says what a stage owes in the row’s own name, not in a hover', () => {
  render(
    <Stage
      stage={stage({ outputs: [slot('a.md', true), slot('b.md', false)] })}
      course={course}
      open={false}
      onToggle={() => {}}
    />,
  )

  expect(
    screen.getByRole('button', {
      name: 'Stage 4: Draft, current, 1 of 2 declared artifacts written',
    }),
  ).toBeInTheDocument()
})

it('names the em dash a stage with no artifacts of its own shows', () => {
  render(<Stage stage={stage()} course={course} open={false} onToggle={() => {}} />)

  // The dash is the entire visible content of that cell. Without a name it is
  // read as punctuation or skipped, and "this stage produces nothing" is not a
  // fact a reader can infer from being told nothing.
  expect(
    screen.getByRole('button', {
      name: 'Stage 4: Draft, current, declares no artifact of its own',
    }),
  ).toBeInTheDocument()
})
