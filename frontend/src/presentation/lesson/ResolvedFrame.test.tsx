/** The three non-resolved states, drawn once so five widgets cannot drift
 *  into five different ways of saying "not found".
 *
 * Every assertion here is about *prose*. `missing` and `unavailable` must
 * degrade to a readable sentence and never to an error panel: a model writing
 * about an entity the extraction pipeline has not reached yet is normal, not
 * a defect. `queryByRole('alert')` is what pins that -- an alert is what an
 * error panel would be.
 */
import { render, screen } from '@testing-library/react'
import type { ReactNode } from 'react'
import { expect, it, vi } from 'vitest'

import type { GraphNode } from '@domain/knowledge/graph.ts'

import { ResolvedFrame } from './ResolvedFrame.tsx'

/** The `missing` wording, matched apostrophe-agnostically on purpose.
 *
 * The frame renders `&rsquo;` (U+2019) and a straight-quote regex silently
 * misses it -- which is harmless in the `getByText` above and *dangerous* in
 * the two `queryByText` assertions below, where the wrong glyph makes a
 * negative assertion pass without ever looking at the right string. Measured,
 * not reasoned: with the straight quote the `missing` test failed and both
 * negative ones passed. */
const MISSING_PROSE = /not in this project[’']s graph/i

const node = (id: string, name: string, entityType = 'Person'): GraphNode => ({
  id,
  name,
  entityType,
})

it('yields to its child once resolved, and draws no frame of its own', () => {
  render(
    <ResolvedFrame
      reference={{ state: 'resolved', entity: node('e1', 'Constantine') }}
      name="Constantine"
    >
      {(entity) => <p>definition of {entity.name}</p>}
    </ResolvedFrame>,
  )

  expect(screen.getByText(/definition of Constantine/)).toBeInTheDocument()
  expect(screen.queryByRole('alert')).not.toBeInTheDocument()
})

it('renders the reference as plain prose when the entity is missing', () => {
  const child = vi.fn()
  render(
    <ResolvedFrame reference={{ state: 'missing' }} name="Theodosius">
      {child as unknown as (entity: GraphNode) => ReactNode}
    </ResolvedFrame>,
  )

  expect(screen.getByText('Theodosius')).toBeInTheDocument()
  expect(screen.getByText(MISSING_PROSE)).toBeInTheDocument()
  expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  // The child never runs: there is no entity to hand it, and a widget that
  // fetched on a null id is exactly the bug this shape prevents.
  expect(child).not.toHaveBeenCalled()
})

it('renders the reference and nothing else when the lookup is unavailable', () => {
  render(
    <ResolvedFrame reference={{ state: 'unavailable' }} name="Theodosius">
      {() => <p>never</p>}
    </ResolvedFrame>,
  )

  expect(screen.getByText('Theodosius')).toBeInTheDocument()
  // Deliberately quieter than `missing`: this page cannot look the name up,
  // so it has learned nothing about the corpus and must not imply it has.
  expect(screen.queryByText(MISSING_PROSE)).not.toBeInTheDocument()
  expect(screen.queryByRole('alert')).not.toBeInTheDocument()
})

it('lists every candidate with its type when the name is ambiguous', () => {
  const picked = vi.fn()
  render(
    <ResolvedFrame
      reference={{
        state: 'ambiguous',
        candidates: [node('e1', 'Constantine', 'Person'), node('e2', 'Constantine', 'Place')],
      }}
      name="Constantine"
      onPick={picked}
    >
      {() => <p>never</p>}
    </ResolvedFrame>,
  )

  // The type is the whole of what makes a picker useful -- two rows reading
  // "Constantine" and "Constantine" are not a choice.
  expect(screen.getByRole('button', { name: /Constantine.*Person/ })).toBeInTheDocument()
  expect(screen.getByRole('button', { name: /Constantine.*Place/ })).toBeInTheDocument()
})

it('hands a picked candidate back to the widget', () => {
  const picked = vi.fn()
  const { getByRole } = render(
    <ResolvedFrame
      reference={{
        state: 'ambiguous',
        candidates: [node('e1', 'Constantine', 'Person'), node('e2', 'Constantine', 'Place')],
      }}
      name="Constantine"
      onPick={picked}
    >
      {() => <p>never</p>}
    </ResolvedFrame>,
  )

  getByRole('button', { name: /Place/ }).click()

  expect(picked).toHaveBeenCalledWith('e2')
})

it('says nothing at all while the search is in flight', () => {
  render(
    <ResolvedFrame reference={{ state: 'loading' }} name="Constantine">
      {() => <p>never</p>}
    </ResolvedFrame>,
  )

  // Red against a build that folds `loading` into `missing`: that one would
  // flash "not in this project's graph" at a reader on every cold cache.
  expect(screen.queryByText(MISSING_PROSE)).not.toBeInTheDocument()
  expect(screen.getByText('Constantine')).toBeInTheDocument()
})
