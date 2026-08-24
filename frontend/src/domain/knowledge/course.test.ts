import { expect, it } from 'vitest'

import type { CourseCandidate } from './catalog.ts'
import type { CourseDetail, CourseFit, Outline } from './course.ts'
import { fitSummary, outlineAge } from './course.ts'

const CANDIDATE: CourseCandidate = {
  slug: 'rome',
  title: 'the fall of rome',
  category: 'history',
  prominence: 1,
  size: 12,
  membershipHash: 'hash-1',
  anchors: [],
  art: { url: '/art.png', alt: '' },
  blurb: null,
  featuredRank: null,
}

const OUTLINE: Outline = {
  promise: 'a promise',
  sections: [{ heading: 'h', summary: 's' }],
  membershipHash: 'hash-1',
  model: 'x',
  generatedAt: '2026-01-01T00:00:00Z',
}

const detailWith = (outline: Outline | null): CourseDetail => ({
  candidate: CANDIDATE,
  outline,
  members: [],
  course: null,
})

it('reports no staleness for a candidate with no outline yet', () => {
  expect(outlineAge(detailWith(null))).toBeNull()
})

it('reports no staleness when the outline hash matches the candidate', () => {
  expect(outlineAge(detailWith(OUTLINE))).toBeNull()
})

it('reports stale when the outline hash disagrees with the candidate', () => {
  const outline = { ...OUTLINE, membershipHash: 'hash-2' }
  expect(outlineAge(detailWith(outline))).toBe('stale')
})

const FIT: CourseFit = { kept: [], added: [], dropped: [], orphaned: false }

it('names an orphaned cluster rather than a diff', () => {
  const summary = fitSummary({ ...FIT, orphaned: true, added: [{ entityId: '1', name: 'a' }] })
  expect(summary).toContain('gone')
  expect(summary).not.toContain('added')
})

it('says nothing changed when kept membership is identical', () => {
  expect(fitSummary(FIT)).toContain('not changed')
})

it('names what was added and dropped', () => {
  const summary = fitSummary({
    ...FIT,
    added: [{ entityId: '1', name: 'a' }],
    dropped: ['2', '3'],
  })
  expect(summary).toContain('1 added')
  expect(summary).toContain('2 dropped')
})
