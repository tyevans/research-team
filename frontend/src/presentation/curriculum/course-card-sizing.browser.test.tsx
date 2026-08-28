import { render } from 'vitest-browser-react'
import { expect, it } from 'vitest'

import type { CourseCandidate } from '@domain/knowledge/catalog.ts'

import { CourseCard } from './CourseCard.tsx'

/** Card geometry is a computed style, so this cannot live in jsdom -- which
 *  lays nothing out and would report all three sizes identical (`scrollHeight`
 *  is 0 everywhere, and a class name in the attribute proves nothing about what
 *  the cascade did with it). This measures the rendered result instead.
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

const boxOf = (selector: string) => document.querySelector(selector)!.getBoundingClientRect()

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

  await expect.element(screen.getByText('The Roman Succession Crisis').first()).toBeVisible()

  const hero = boxOf('.crs-card-hero').width
  const highlight = boxOf('.crs-card-highlight').width
  const filed = boxOf('.crs-card-filed').width

  expect(hero).toBeGreaterThan(highlight)
  expect(highlight).toBeGreaterThan(filed)
})

it('gives the art a declared aspect ratio rather than the image its own', async () => {
  // **The assertion that makes a shelf line up.** Generated art arrives at
  // whatever proportion the model chose, and a card whose art is a bare `<img>`
  // is as tall as its picture -- so twelve cards in a row have twelve different
  // heights and twelve different title baselines. `aspect-[3/2]` plus
  // `object-cover` is what fixes that, and it is invisible to every other kind
  // of test: jsdom reports 0×0, and the class name in the attribute says
  // nothing about whether `theme.css` generated a rule for it.
  //
  // The `src` here resolves to nothing, which is deliberate: a broken image is
  // the harshest case for this rule, because an `<img>` with no intrinsic size
  // is exactly where a missing aspect ratio collapses to zero height.
  //
  // Proved red on 2026-08-27 by deleting `CARD_ART`'s entry for `highlight`:
  // the ratio came back 0 rather than 1.5.
  const screen = await render(
    <CourseCard candidate={aCandidate()} size="highlight" onOpen={() => {}} />,
  )
  await expect.element(screen.getByText('The Roman Succession Crisis')).toBeVisible()

  const art = boxOf('.crs-card-art')
  expect(art.width).toBeGreaterThan(0)
  expect(art.width / art.height).toBeCloseTo(3 / 2, 1)
})

it('hides the feature toggle until the card is reached, and reveals it on keyboard focus', async () => {
  // Curation is one control per card and it must not be permanently on screen
  // -- twelve cards each carrying a visible button is a browsing surface that
  // looks like a form. Hiding it with `hidden`/`display:none` would make it
  // untabbable, which is the same defect with a nicer transition, so it is
  // `opacity` plus `focus-within`.
  //
  // Only a browser can judge this: `focus-within` is a selector jsdom never
  // evaluates, and `getComputedStyle` there returns only what an inline style
  // said -- so a card that revealed the toggle on hover alone, and never on
  // focus, would pass every jsdom test in this directory.
  //
  // It was red on its first run, against a real defect rather than a
  // deliberate break: the reveal was written `focus-within:opacity-100` on the
  // toggle's own wrapper, which asks whether *the toggle* has focus -- and the
  // focus lands on the overlay button, its sibling. So the toggle was
  // reachable only by a pointer, and every jsdom test in this directory passed.
  // `group-focus-within` is the fix; this measurement is the only thing that
  // could have found it.
  const screen = await render(
    <CourseCard
      candidate={aCandidate({ featuredRank: null })}
      size="highlight"
      onOpen={() => {}}
      onFeature={() => {}}
      onUnfeature={() => {}}
    />,
  )
  await expect.element(screen.getByText('The Roman Succession Crisis')).toBeVisible()

  const curate = document.querySelector('.crs-card-curate')!
  expect(getComputedStyle(curate).opacity).toBe('0')

  document.querySelector<HTMLButtonElement>('.crs-card-open')!.focus()
  expect(getComputedStyle(curate).opacity).toBe('1')
})

it('shows the toggle without being reached when the candidate is already featured', async () => {
  // The one card whose curation state is worth seeing at a glance: a reader
  // scanning for what they featured should not have to hover every card to
  // find out. Same measurement, opposite expectation.
  const screen = await render(
    <CourseCard
      candidate={aCandidate({ featuredRank: 1 })}
      size="highlight"
      onOpen={() => {}}
      onFeature={() => {}}
      onUnfeature={() => {}}
    />,
  )
  await expect.element(screen.getByText('The Roman Succession Crisis')).toBeVisible()

  expect(getComputedStyle(document.querySelector('.crs-card-curate')!).opacity).toBe('1')
})
