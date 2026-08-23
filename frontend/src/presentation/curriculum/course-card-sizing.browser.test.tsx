import { render } from 'vitest-browser-react'
import { expect, it } from 'vitest'

import type { CourseCandidate } from '@domain/knowledge/catalog.ts'

import { CourseCard } from './CourseCard.tsx'

/** Card size is a computed style, so this cannot live in jsdom -- which lays
 *  nothing out and would report all three sizes identical (`scrollHeight` is
 *  0 everywhere, and a class name in the attribute proves nothing about what
 *  the cascade did with it). This measures the rendered widths instead.
 */

const aCandidate = (over: Partial<CourseCandidate> = {}): CourseCandidate => ({
  slug: 'roman-succession',
  title: 'The Roman Succession Crisis',
  category: 'history',
  prominence: 0.8,
  size: 12,
  membershipHash: 'hash-1',
  anchors: [],
  art: { url: '/art/roman-succession.png', alt: 'A mosaic of an imperial court' },
  blurb: null,
  featuredRank: null,
  ...over,
})

it('draws the hero wider than the highlight, and the highlight wider than the filed card', async () => {
  const screen = await render(
    <div style={{ display: 'flex', gap: '8px' }}>
      <CourseCard candidate={aCandidate({ slug: 'hero-card' })} size="hero" onOpen={() => {}} />
      <CourseCard
        candidate={aCandidate({ slug: 'highlight-card' })}
        size="highlight"
        onOpen={() => {}}
      />
      <CourseCard candidate={aCandidate({ slug: 'filed-card' })} size="filed" onOpen={() => {}} />
    </div>,
  )

  const widthOf = (selector: string) =>
    document.querySelector(selector)!.getBoundingClientRect().width

  await expect.element(screen.getByText('The Roman Succession Crisis').first()).toBeVisible()

  const hero = widthOf('.crs-card-hero')
  const highlight = widthOf('.crs-card-highlight')
  const filed = widthOf('.crs-card-filed')

  expect(hero).toBeGreaterThan(highlight)
  expect(highlight).toBeGreaterThan(filed)
})
