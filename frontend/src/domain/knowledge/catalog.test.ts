import { describe, expect, it } from 'vitest'

import { blurbAge, type CourseCandidate } from './catalog.ts'

const candidate = (over: Partial<CourseCandidate> = {}): CourseCandidate => ({
  slug: 'warp',
  title: 'Warp drive',
  category: 'concept',
  prominence: 12,
  size: 8,
  membershipHash: 'abc',
  anchors: [],
  art: { url: 'data:image/svg+xml,x', alt: 'Warp drive' },
  blurb: null,
  featuredRank: null,
  ...over,
})

describe('blurbAge', () => {
  it('reports no age when the blurb was written from the current membership', () => {
    expect(
      blurbAge(candidate({ blurb: { text: 'x', membershipHash: 'abc', generatedAt: 'now' } })),
    ).toBe(null)
  })

  it('reports staleness when the membership has moved since', () => {
    // The number this repo has shipped without twice. A blurb describing a
    // cluster that has since doubled is not wrong in any way a reader sees.
    expect(
      blurbAge(
        candidate({
          blurb: { text: 'x', membershipHash: 'old', generatedAt: 'then' },
          membershipHash: 'new',
        }),
      ),
    ).toBe('stale')
  })

  it('reports nothing for a candidate with no blurb at all', () => {
    // An ordinary state, not a degraded one: every candidate on a cold project
    // has no copy yet.
    expect(blurbAge(candidate())).toBe(null)
  })
})
