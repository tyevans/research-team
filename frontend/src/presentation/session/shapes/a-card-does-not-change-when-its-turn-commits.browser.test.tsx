import { render } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { ToolResult } from './ToolResult.tsx'
import { acknowledgement, entityList, excerpt, hitList, toolMessage } from './fixtures.ts'

/** The property the whole "phase is position" decision rests on.
 *
 * `IN PROGRESS — NOT YET RECORDED` is deleted as a per-card label because,
 * repeated once per card, it stopped being read at all. What replaces it is
 * the live edge: everything above it is settled by virtue of being above it,
 * and the edge itself is marked by a pulse and an accent on the row's glyph.
 *
 * That only works if the two phases are the same component with a `phase`
 * prop and **no geometry differs between them**. If a phase adds so much as a
 * pulse dot to the header, every card in a turn jumps at the instant it
 * commits — which is the defect, not the fix. Two components that agree are
 * two components that will stop agreeing, so this is asserted rather than
 * arranged.
 *
 * A measurement, so it is a browser test: in jsdom every rect is zero and both
 * phases would be "identical" with the stylesheet deleted.
 */
describe('a card does not change when its turn commits', () => {
  it.each([
    ['hit_list', hitList],
    ['entity_list', entityList],
    ['excerpt', excerpt],
    ['acknowledgement', acknowledgement],
  ])('is byte-identical in geometry for %s', (_shape, artifact) => {
    const message = toolMessage(artifact)

    const live = render(<ToolResult message={message} phase="live" />)
    const liveBox = live.getByTestId('stream-body').getBoundingClientRect()
    const liveGutter = live.getByTestId('stream-gutter').getBoundingClientRect()
    live.unmount()

    const settled = render(<ToolResult message={message} phase="settled" />)
    const settledBox = settled.getByTestId('stream-body').getBoundingClientRect()
    const settledGutter = settled.getByTestId('stream-gutter').getBoundingClientRect()

    expect(settledBox.width).toBe(liveBox.width)
    expect(settledBox.height).toBe(liveBox.height)
    expect(settledGutter.width).toBe(liveGutter.width)
    expect(settledGutter.left).toBe(liveGutter.left)
  })

  it('marks only the live edge', () => {
    const { getByTestId } = render(<ToolResult message={toolMessage(hitList)} phase="live" />)
    expect(getByTestId('stream-glyph')).toHaveAttribute('data-phase', 'live')
  })

  it('leaves a settled row unmarked', () => {
    // The half that would otherwise pass with the attribute hard-coded.
    const { getByTestId } = render(<ToolResult message={toolMessage(hitList)} phase="settled" />)
    expect(getByTestId('stream-glyph')).toHaveAttribute('data-phase', 'settled')
  })

  it('carries the live treatment in the animation, not in the box', () => {
    // Named explicitly because "no geometry differs" is satisfied by a phase
    // that does nothing at all, and a live edge nobody can see is the same
    // defect as a banner nobody reads.
    const live = render(<ToolResult message={toolMessage(hitList)} phase="live" />)
    const name = getComputedStyle(live.getByTestId('stream-glyph')).animationName
    expect(name).not.toBe('none')
    live.unmount()

    const settled = render(<ToolResult message={toolMessage(hitList)} phase="settled" />)
    expect(getComputedStyle(settled.getByTestId('stream-glyph')).animationName).toBe('none')
  })
})
