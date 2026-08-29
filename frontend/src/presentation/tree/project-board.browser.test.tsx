import { render } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { scaleOf } from '@domain/project/board.ts'
import type { ProjectListing, ProjectSummary } from '@domain/project/project.ts'
import { ProjectId } from '@domain/shared/identifier.ts'

import { BOARD_ROW_HEIGHT } from './ProjectBoard.tsx'
import { ProjectBoardRow } from './ProjectBoardRow.tsx'
import { ProjectPipeline } from './ProjectPipeline.tsx'

/** The board's measurements, which jsdom cannot take.
 *
 * Everything here is a computed style, a resolved width or a hit test. Roles,
 * text and keyboard routing belong in `TreeView.test.tsx`, where they run in a
 * second rather than a minute.
 *
 * Three of these exist because the defect they cover **shipped inside this
 * branch** and was caught by a screenshot rather than by any gate: the amber
 * marking unextracted sources was `--tint-held`, a near-white background wash,
 * so the one thing this page was built to show was invisible against the empty
 * track; and the two tones were layered the wrong way round, so a
 * fully-extracted project drew entirely amber and the marker meant its
 * opposite. Every class attribute was exactly as intended in both cases. jsdom
 * would have passed both, and did.
 */

const EMPTY: ProjectSummary = {
  topics: 0,
  topicsOpen: 0,
  sources: 0,
  extracted: 0,
  courses: 0,
  sessions: 0,
  lastActivity: null,
}

const listing = (name: string, summary: Partial<ProjectSummary> = {}): ProjectListing => ({
  id: ProjectId('11111111-1111-4111-8111-111111111111'),
  name,
  activeSessionId: null,
  tipAtEvent: 0,
  summary: { ...EMPTY, ...summary },
})

/** A row at a realistic measure.
 *
 * The width is an inline style rather than a `w-[1100px]` utility, because the
 * wrapper's width is a *test fixture* rather than part of the design — and
 * because an arbitrary-value utility here would be one more class for
 * `check-tailwind.mjs` to have an opinion about. 1100px is `.home-inner`'s cap,
 * so the row lays out at the width it has in the application.
 */
const drawRow = (one: ProjectListing) =>
  render(
    <div style={{ width: '1100px' }}>
      <ProjectBoardRow
        listing={one}
        scale={scaleOf([one])}
        activity={null}
        onDelete={() => {}}
        onContinue={() => {}}
        busy={false}
      />
    </div>,
  )

/** One named track's parts.
 *
 * Scoped by track name rather than reaching for the first `[data-pipe-fill]`
 * on the page, which is what the first draft did and what made two of these
 * tests measure the *topics* bar while claiming to measure the corpus one.
 * Three tracks render every time, so an unscoped selector is always ambiguous
 * and silently answers about whichever comes first in the DOM.
 */
const track = (name: 'topics' | 'sources' | 'courses') => {
  const root = document.querySelector(`[data-pipe-track="${name}"]`)!
  return {
    bar: root.querySelector('[data-pipe-bar]')!,
    fill: root.querySelector('[data-pipe-fill]')!,
    done: root.querySelector('[data-pipe-done]'),
    tone: root.querySelector('[data-pipe-fill]')!.getAttribute('data-pipe-fill'),
  }
}

const rgb = (element: Element) => getComputedStyle(element).backgroundColor

/** Perceived brightness of an `rgb(...)` string, 0–255.
 *
 * `quiet-button-hover.browser.test.tsx`'s helper, for the same reason it has
 * one: the interesting question about two colours here is whether a person can
 * tell them apart, and string inequality cannot answer it.
 *
 * **This is not decoration on the assertion; it is the assertion.** The first
 * draft of the amber test compared the two colours with `not.toBe`, and
 * `bg-tint-held` — the near-white wash that was the original defect — passes
 * that, because `#faf1de` is a different string from `--line-soft`. Proved by
 * restoring `bg-tint-held` and re-running: eight tests, eight passes, with the
 * marker as invisible as it had been. A test that cannot fail on the defect it
 * was written for is worse than no test, because it is cited as coverage.
 */
const luminance = (colour: string) => {
  const [r, g, b] = colour.match(/\d+/g)!.slice(0, 3).map(Number)
  return 0.2126 * r! + 0.7152 * g! + 0.0722 * b!
}

describe('the corpus track', () => {
  it('paints the unextracted tail in an amber that differs from the empty track', () => {
    // The whole point of the two-tone bar. `--tint-held` is `#faf1de` and was
    // what this used for one draft: against `--line-soft` behind it the tail
    // was invisible.
    //
    // Stated as a *luminance gap* rather than as a named colour, so the palette
    // can be retuned without touching this file — and, more importantly,
    // because inequality is not the property. 40 is well below the ~110 the
    // current tokens give and well above the ~6 that `--tint-held` gave, so it
    // separates the two arrangements without pinning either.
    render(
      <ProjectPipeline
        summary={{ ...EMPTY, sources: 6, extracted: 3 }}
        scale={{ topics: 1, sources: 6, courses: 1 }}
      />,
    )

    const sources = track('sources')

    expect(sources.tone).toBe('behind')
    expect(Math.abs(luminance(rgb(sources.fill)) - luminance(rgb(sources.bar)))).toBeGreaterThan(40)
  })

  it('paints the extracted part in the same tone as an ordinary full bar', () => {
    // Extracted material is not a special category — it is the part of this bar
    // that is done — so it has to match the plain fills beside it, or the
    // corpus track stops being comparable with the two next to it.
    render(
      <ProjectPipeline
        summary={{ ...EMPTY, topics: 4, sources: 6, extracted: 3 }}
        scale={{ topics: 4, sources: 6, courses: 1 }}
      />,
    )

    expect(rgb(track('sources').done!)).toBe(rgb(track('topics').fill))
  })

  it('draws no amber at all when everything ingested has been extracted', () => {
    // The inverted-layer defect, stated as the assertion that would have caught
    // it: with the tones swapped, a complete project's inner fill covered the
    // whole bar in the *marker* colour, so the four projects with nothing
    // outstanding were the loudest rows on the page.
    render(
      <ProjectPipeline
        summary={{ ...EMPTY, sources: 6, extracted: 6 }}
        scale={{ topics: 1, sources: 6, courses: 1 }}
      />,
    )

    const sources = track('sources')

    expect(sources.tone).toBe('plain')
    expect(rgb(sources.done!)).toBe(rgb(sources.fill))
  })

  it('scales a bar to the board rather than to the project', () => {
    // The measurement the whole design rests on: a project with half the
    // board's largest source count draws a half-length bar, which is what makes
    // the three bars read as columns down the page. Scaled to itself it would
    // be full-length and say nothing at all.
    render(
      <div style={{ width: '1100px' }}>
        <ProjectPipeline
          summary={{ ...EMPTY, sources: 11 }}
          scale={{ topics: 1, sources: 22, courses: 1 }}
        />
      </div>,
    )

    const sources = track('sources')
    const bar = sources.bar.getBoundingClientRect()
    const fill = sources.fill.getBoundingClientRect()

    expect(fill.width / bar.width).toBeCloseTo(0.5, 2)
  })
})

describe('the row', () => {
  it('is the height the virtualizer estimates', () => {
    // One fact written twice. The constant was 128 against a real 97 before
    // this test existed — a 25px error per row, which would have put the fourth
    // row a hundred pixels from where the virtualizer expected it. The previous
    // page's equivalent pair were 108 and 84 until a test held them.
    //
    // The tolerance is a pixel: the height is a sum of token-derived paddings
    // and line boxes, and a sub-pixel line box is not a defect. A change large
    // enough to matter to a virtualizer is many pixels.
    drawRow(listing('Star Trek'))

    const rect = document.querySelector('[data-board-row]')!.getBoundingClientRect()
    // The item's own bottom padding (`pb-3`, `--spacing-3`) is part of what the
    // virtualizer measures, so it is added here rather than left out of the
    // constant.
    const gap = 10

    expect(Math.abs(rect.height + gap - BOARD_ROW_HEIGHT)).toBeLessThanOrEqual(1)
  })

  it('makes the whole row the project link, not just the name', () => {
    // A hit test rather than a rect. CLAUDE.md records this exact
    // misdiagnosis: the stretched `::after` has the right geometry whether or
    // not something opaque covers it, so `getBoundingClientRect` cannot tell a
    // working overlay from a buried one. `elementFromPoint` at a corner far
    // from the name text is the question that says what was *painted*.
    drawRow(listing('Star Trek'))

    const rect = document.querySelector('[data-board-row]')!.getBoundingClientRect()

    expect(document.elementFromPoint(rect.left + 8, rect.bottom - 8)?.tagName).toBe('A')
  })

  it('keeps the actions reachable through that overlay', () => {
    // The other half of the stretched link, and the half that breaks silently.
    // The buttons are raised above the overlay by `relative` alone — no
    // `z-index`, which `stacking.test.ts` forbids here — so it works only
    // because they come *after* the anchor in document order. Reordering the
    // head would make Continue unclickable with nothing else failing.
    const { getByRole } = drawRow(listing('Star Trek'))
    const rect = getByRole('button', { name: 'Continue' }).getBoundingClientRect()

    const hit = document.elementFromPoint(rect.left + rect.width / 2, rect.top + rect.height / 2)

    expect(hit?.closest('button')).not.toBeNull()
  })

  it('draws the accent button in the accent, against the bare-button defaults', () => {
    // The third cascade instance CLAUDE.md documents: unlayered `button`
    // selectors in `tokens.css` setting `background`, `color` and `font:
    // inherit` beat every Tailwind utility on every control in the console, and
    // `font` reached furthest because the shorthand also sets `font-size`.
    // Those rules are in `@layer base` now, and this is the standing
    // measurement that they stay there — a row whose one verb draws in the page
    // background is the `CourseCard` defect again.
    const { getByRole } = drawRow(listing('Star Trek'))
    const button = getByRole('button', { name: 'Continue' })

    const fill = getComputedStyle(button).backgroundColor
    const page = getComputedStyle(document.documentElement).backgroundColor

    expect(fill).not.toBe(page)
    expect(fill).not.toBe('rgba(0, 0, 0, 0)')
  })
})
