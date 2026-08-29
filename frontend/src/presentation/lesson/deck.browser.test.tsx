import { render } from '@testing-library/react'
import { expect, it, vi } from 'vitest'

import type { AttemptsApi } from '@application/lesson/use-attempts.ts'
import { freshAttempt } from '@domain/lesson/attempt.ts'
import type { LessonDocument } from '@domain/lesson/document.ts'
import { componentBlock } from '@presentation/ask/ask-fixtures.ts'

import { OverlayHost } from '../layout/OverlayHost.tsx'
import { Deck } from './Deck.tsx'

/** The four claims about the deck that only a browser can settle.
 *
 * Everything about roles, focus order, keyboard routing and rendered text is
 * in `Deck.test.tsx`, where it runs in a second. What is here is what jsdom
 * would answer wrongly and confidently: a viewport-filling surface, a colour
 * that has to beat an unlayered rule, a border that has to draw on one side,
 * and -- the correction CLAUDE.md's most recent entry makes -- what is actually
 * *painted* at a point, rather than what was laid out there.
 *
 * The last one is the reason this file exists at all. A deck is an opaque
 * full-screen panel over the page: every geometry assertion about its content
 * passes whether or not something is drawn on top of it, which is exactly how
 * the catalog cards shipped blank.
 */

const DOC: LessonDocument = {
  blocks: [
    {
      kind: 'markdown',
      text: '# The Log Is the Only Source of Truth\n\nEverything is one ordered list of events.\n\n## What a fold is\n\nA fold is a pure function of the log.',
    },
    componentBlock({ type: 'mcq', id: 'q1', data: { prompt: 'Which?', options: [] } }),
  ],
}

const attempts = {
  stateFor: () => freshAttempt(),
  update: vi.fn(),
  submit: vi.fn(),
  reset: vi.fn(),
  mcqResponse: (picked: readonly number[]) => picked,
} as unknown as AttemptsApi

const present = (slide = 0) =>
  render(
    <OverlayHost>
      <Deck
        doc={DOC}
        attempts={attempts}
        label="lesson-01.md"
        withheldExplanation="graded on the server"
        slide={slide}
        onSlide={vi.fn()}
        onClose={vi.fn()}
      />
    </OverlayHost>,
  )

const root = () => document.querySelector('.deck-root')!

it('fills the viewport rather than sizing to its tallest slide', () => {
  // `.lay-layer-content` is `position: relative` and sizes to its content, so
  // a deck laid out inside it without `fixed inset-0` is as tall as whatever
  // is on the current slide -- a title slide would give a 200px "full screen".
  // jsdom pins `offsetHeight` to a constant and cannot see this at all.
  present()
  const box = root().getBoundingClientRect()
  expect(box.width).toBe(window.innerWidth)
  expect(box.height).toBe(window.innerHeight)
})

it('paints the slide, and not something opaque over it', () => {
  // The hit test, not the rectangle. Both the backdrop `Overlay` renders for a
  // modal and the deck's own `bg-bg` are full-bleed opaque surfaces in the same
  // stacking context, so "the prose has the right box at the right place" is
  // true in the failure as well as in the success -- which is precisely the
  // misdiagnosis CLAUDE.md records having made once from
  // `getBoundingClientRect` alone.
  present()
  // The paragraph, not the `.md-unwrapped` wrapper: `.doc > .md-unwrapped` is
  // `display: contents`, so the wrapper generates no box and
  // `getBoundingClientRect` on it is 0x0 at the origin -- the hit test would
  // then probe the top-left corner of the screen and fail for a reason that has
  // nothing to do with painting. Cost half a run to find, which is the same
  // trap in miniature: a geometry call answered confidently and meant nothing.
  const prose = document.querySelector('.deck-title p')!
  const box = prose.getBoundingClientRect()
  const painted = document.elementFromPoint(box.left + box.width / 2, box.top + box.height / 2)
  expect(prose.contains(painted)).toBe(true)
})

it('draws the current rail tick in the accent and the others in the line tone', () => {
  // A utility on a bare `<button>`'s child, against the console's own tokens.
  // The class is in the attribute either way; only the computed value knows
  // whether the reader can see where they are.
  present(1)
  const ticks = [...document.querySelectorAll('.deck-rail-row .deck-tick')]
  expect(ticks.length).toBeGreaterThan(2)

  const accent = getComputedStyle(document.documentElement).getPropertyValue('--accent').trim()
  const strong = getComputedStyle(document.documentElement).getPropertyValue('--line-strong').trim()
  expect(accent).not.toBe(strong)

  const current = getComputedStyle(ticks[1]!).backgroundColor
  const other = getComputedStyle(ticks[0]!).backgroundColor
  expect(current).not.toBe(other)
  expect(current).toBe(asRgb(accent))
})

it('gives the rail one border and not four', () => {
  // `border-r` beside `border-0`, which is the pair CLAUDE.md's `border-solid`
  // entry argues for: without the `border-0` the three sides that get a style
  // and no width fall back to the browser's `medium` and the rail draws a box.
  // No gate catches it; this is the gate.
  present()
  const rail = getComputedStyle(document.querySelector('.deck-rail')!)
  expect(rail.borderRightWidth).toBe('1px')
  expect(rail.borderTopWidth).toBe('0px')
  expect(rail.borderLeftWidth).toBe('0px')
  expect(rail.borderBottomWidth).toBe('0px')
})

it('lets the rail row wrap its section name instead of running off the column', () => {
  // A `.btn` would have won this: `white-space: nowrap` is unlayered on it, so
  // a rail row built from the `Button` primitive silently refuses to wrap and a
  // long heading runs under the slide. The reason `RailRow` is a bare
  // `<button>`, measured rather than asserted in prose.
  present()
  const row = document.querySelector('.deck-rail-row')!
  expect(getComputedStyle(row).whiteSpace).toBe('normal')
  expect(row.getBoundingClientRect().width).toBeLessThanOrEqual(
    document.querySelector('.deck-rail')!.getBoundingClientRect().width,
  )
})

/** A token's value as a browser reports a used colour, so a `#rrggbb` token can
 *  be compared with `getComputedStyle`'s `rgb(...)`. */
const asRgb = (value: string): string => {
  const probe = document.createElement('span')
  probe.style.color = value
  document.body.append(probe)
  const used = getComputedStyle(probe).color
  probe.remove()
  return used
}
