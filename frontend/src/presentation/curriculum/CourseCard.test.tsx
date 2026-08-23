import { render, screen } from '@testing-library/react'
import { expect, it, vi } from 'vitest'

import type { CourseCandidate } from '@domain/knowledge/catalog.ts'

import { CourseCard } from './CourseCard.tsx'

/** One course candidate, drawn as a card. `size` is a layout concern this
 *  suite cannot judge -- jsdom lays nothing out, so it stays out of every
 *  test here and belongs to `course-card-sizing.browser.test.tsx` instead,
 *  which measures it.
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

it('renders the title', () => {
  render(<CourseCard candidate={aCandidate()} size="highlight" onOpen={() => {}} />)
  expect(screen.getByText('The Roman Succession Crisis')).toBeInTheDocument()
})

it('gives the art its own alt text, not an empty one', () => {
  // A browsing surface where every image is decorative (`alt=""`) is one a
  // screen-reader user cannot tell cards apart in -- the alt has to be the
  // candidate's own, not a placeholder the component invented.
  render(<CourseCard candidate={aCandidate()} size="highlight" onOpen={() => {}} />)
  const img = screen.getByRole('img', { name: 'A mosaic of an imperial court' })
  expect(img).toBeInTheDocument()
})

it('renders no blurb, and no empty paragraph, when the candidate has none', () => {
  // `blurb: null` is the ordinary state of every candidate on a cold project,
  // not an error -- there must be nothing rendered in its place, not an empty
  // element sized as if copy were coming.
  const { container } = render(
    <CourseCard candidate={aCandidate({ blurb: null })} size="highlight" onOpen={() => {}} />,
  )
  expect(container.querySelector('.crs-card-blurb')).toBeNull()
})

it('renders a current blurb with no staleness note', () => {
  render(
    <CourseCard
      candidate={aCandidate({
        blurb: {
          text: 'A crisis of succession.',
          membershipHash: 'hash-1',
          generatedAt: '2026-01-01T00:00:00Z',
        },
      })}
      size="highlight"
      onOpen={() => {}}
    />,
  )
  expect(screen.getByText('A crisis of succession.')).toBeInTheDocument()
  expect(screen.queryByText(/out of date|stale/i)).toBeNull()
})

it('marks a stale blurb with its staleness note', () => {
  render(
    <CourseCard
      candidate={aCandidate({
        membershipHash: 'hash-2',
        blurb: {
          text: 'A crisis of succession.',
          membershipHash: 'hash-1',
          generatedAt: '2026-01-01T00:00:00Z',
        },
      })}
      size="highlight"
      onOpen={() => {}}
    />,
  )
  expect(screen.getByText('A crisis of succession.')).toBeInTheDocument()
  expect(screen.getByText(/out of date|stale/i)).toBeInTheDocument()
})

it('marks a featured candidate to assistive technology, not only by colour', () => {
  // A visual-only cue (a border, a colour) says nothing to a screen reader --
  // there has to be text or an aria attribute a non-visual reading catches.
  render(<CourseCard candidate={aCandidate({ featuredRank: 1 })} size="hero" onOpen={() => {}} />)
  expect(screen.getByText(/featured/i)).toBeInTheDocument()
})

it('does not mark an unfeatured candidate as featured', () => {
  render(
    <CourseCard
      candidate={aCandidate({ featuredRank: null })}
      size="highlight"
      onOpen={() => {}}
    />,
  )
  expect(screen.queryByText(/featured/i)).toBeNull()
})

it('calls onOpen with the slug when clicked', async () => {
  const onOpen = vi.fn()
  render(
    <CourseCard
      candidate={aCandidate({ slug: 'roman-succession' })}
      size="highlight"
      onOpen={onOpen}
    />,
  )

  screen.getByRole('button', { name: /The Roman Succession Crisis/ }).click()

  expect(onOpen).toHaveBeenCalledWith('roman-succession')
})
