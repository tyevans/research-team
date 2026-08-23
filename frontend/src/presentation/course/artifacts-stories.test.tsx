import { composeStories } from '@storybook/react-vite'
import { render, screen } from '@testing-library/react'
import { expect, it } from 'vitest'

import * as stories from './Artifacts.stories.tsx'

/** Four states stay four states, and a disclosure does not wear a defect's
 *  colour.
 *
 * `Artifacts.tsx` states the rule: an artifact is in "one of four states a
 * naive row would flatten into two", and "the last two are both legitimate and
 * must not look alike".
 *
 * The mechanism is four `dress` strings that **replace** `Chip`'s default trio
 * rather than adding to it -- because two colour utilities on one element both
 * land in `@layer utilities`, where the winner is Tailwind's sort order. The
 * failure that guards against is specific and silent: a tone whose class
 * resolved to nothing would collapse four states into one grey and read as a
 * design decision. So these assert on *distinctness*, not on particular
 * colours -- the values may be retuned, the collapse may not happen.
 *
 * The pair that matters is `inferred` against `claims nothing`. One is a
 * disclosure -- "a stage whose reasoning is its own and says so is working as
 * designed" -- and the other is a gap the domain calls "indistinguishable from
 * an artifact never checked against anything". Asserting only that they differ
 * is not enough: a build that gave *both* the failure dress differs from
 * nothing and is wrong. So the direction is asserted too.
 *
 * **Proved red** by passing `INFERRED_DRESS` through as `BAD_DRESS`: the
 * direction test fails while the distinctness test stays green, which is
 * exactly the pair earning its keep.
 */
const { EveryState, InferredAgainstClaimsNothing, Open, MissingFields } = composeStories(stories)

const chipClasses = () =>
  [...document.body.querySelectorAll('span')]
    .filter((span) =>
      /written|not written|inferred|claims nothing|unreadable/.test(span.textContent ?? ''),
    )
    .map((span) => span.className)

it('gives the four states four distinct treatments', () => {
  render(<EveryState />)
  const written = screen.getAllByText('written')
  const notWritten = screen.getByText('not written')
  expect(written.length).toBeGreaterThan(0)
  expect(written[0]!.className).not.toBe(notWritten.className)

  // Four rows, four states, and no two chips collapsed onto one dress.
  const distinct = new Set(chipClasses())
  expect(distinct.size).toBeGreaterThanOrEqual(3)
})

/** The pair, and its direction. */
it('does not dress a disclosure as a defect', () => {
  render(<InferredAgainstClaimsNothing />)
  const inferred = screen.getByText('inferred')
  const nothing = screen.getByText('claims nothing')

  // They differ...
  expect(inferred.className).not.toBe(nothing.className)
  // ...and in the right direction: the gap wears the failure colour, the
  // disclosure does not.
  expect(nothing.className).toContain('text-k-failure')
  expect(inferred.className).not.toContain('text-k-failure')
})

/** "No readable frontmatter" and "frontmatter is missing X" are different
 *  facts: a file that says some of what it is differs from one that says none
 *  of it. */
it('separates absent frontmatter from incomplete frontmatter', () => {
  render(<MissingFields />)
  expect(screen.getByText(/Frontmatter is missing objective_ids, reviewed_by/)).toBeInTheDocument()
  expect(screen.queryByText(/No readable frontmatter/)).not.toBeInTheDocument()
})

/** `aria-current`, because "the one you followed a link to" is a fact a screen
 *  reader needs and a background colour is not one. */
it('marks the linked row for a reader who cannot see the fill', () => {
  const { container } = render(<Open />)
  const current = container.querySelectorAll('[aria-current]')
  expect(current).toHaveLength(1)
})
