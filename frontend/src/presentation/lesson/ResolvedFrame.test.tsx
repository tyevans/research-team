/** The three non-resolved states, drawn once so five widgets cannot drift
 *  into five different ways of saying "not found".
 *
 * Every assertion here is about *prose*. `missing` and `unavailable` must
 * degrade to a readable sentence and never to an error panel: a model writing
 * about an entity the extraction pipeline has not reached yet is normal, not
 * a defect. `queryByRole('alert')` is what pins that -- an alert is what an
 * error panel would be.
 */
import { act, render, screen } from '@testing-library/react'
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
  render(
    <ResolvedFrame
      reference={{
        state: 'ambiguous',
        candidates: [node('e1', 'Constantine', 'Person'), node('e2', 'Constantine', 'Place')],
        truncated: false,
      }}
      name="Constantine"
    >
      {() => <p>never</p>}
    </ResolvedFrame>,
  )

  // The type is the whole of what makes a picker useful -- two rows reading
  // "Constantine" and "Constantine" are not a choice.
  expect(screen.getByRole('button', { name: /Constantine.*Person/ })).toBeInTheDocument()
  expect(screen.getByRole('button', { name: /Constantine.*Place/ })).toBeInTheDocument()
})

it('yields to its child on the candidate a reader picked', () => {
  const { getByRole } = render(
    <ResolvedFrame
      reference={{
        state: 'ambiguous',
        candidates: [node('e1', 'Constantine', 'Person'), node('e2', 'Constantine', 'Place')],
        truncated: false,
      }}
      name="Constantine"
    >
      {(entity) => <p>definition of {entity.id}</p>}
    </ResolvedFrame>,
  )

  act(() => getByRole('button', { name: /Place/ }).click())

  // The author's name, not the candidate's: the reference is the prose the
  // widget degrades to, and a pick decides the id and nothing else.
  expect(screen.getByText(/definition of e2/)).toBeInTheDocument()
})

it('drops a pick a later search result no longer offers', () => {
  // Red against holding the pick unconditionally -- which is what
  // `DefinitionWidget` did before this state moved in here, and what the
  // obvious `picked ? {id: picked} : reference` restores. That build keeps
  // drawing `e2` below: an id the current answer does not name, with the
  // picker gone and no way back to it. A search refetching to a different set
  // is ordinary here, because extraction runs while a reader has the answer
  // open.
  const child = (entity: GraphNode) => <p>drawing {entity.id}</p>
  const { getByRole, rerender } = render(
    <ResolvedFrame
      reference={{
        state: 'ambiguous',
        candidates: [node('e1', 'Constantine', 'Person'), node('e2', 'Constantine', 'Place')],
        truncated: false,
      }}
      name="Constantine"
    >
      {child}
    </ResolvedFrame>,
  )
  act(() => getByRole('button', { name: /Place/ }).click())
  expect(screen.getByText(/drawing e2/)).toBeInTheDocument()

  rerender(
    <ResolvedFrame
      reference={{
        state: 'ambiguous',
        candidates: [node('e7', 'Constantine', 'Event'), node('e8', 'Constantine', 'Work')],
        truncated: false,
      }}
      name="Constantine"
    >
      {child}
    </ResolvedFrame>,
  )

  expect(screen.queryByText(/drawing e2/)).not.toBeInTheDocument()
  expect(screen.getByRole('button', { name: /Event/ })).toBeInTheDocument()
})

it('lets a resolved answer overtake a pick', () => {
  // Passes structurally rather than by the scoping above: the `resolved` arm
  // returns before the pick is read at all, so this would stay green with the
  // candidate lookup removed. It is here because that arm being first is the
  // half of the fix a refactor could quietly reorder -- moving the pick check
  // above it makes this the only test that fails.
  const child = (entity: GraphNode) => <p>drawing {entity.id}</p>
  const { getByRole, rerender } = render(
    <ResolvedFrame
      reference={{
        state: 'ambiguous',
        candidates: [node('e1', 'Constantine', 'Person'), node('e2', 'Constantine', 'Place')],
        truncated: false,
      }}
      name="Constantine"
    >
      {child}
    </ResolvedFrame>,
  )
  act(() => getByRole('button', { name: /Place/ }).click())

  rerender(
    <ResolvedFrame
      reference={{ state: 'resolved', entity: node('e9', 'Constantine') }}
      name="Constantine"
    >
      {child}
    </ResolvedFrame>,
  )

  expect(screen.getByText(/drawing e9/)).toBeInTheDocument()
})

it('caps the picker and says how many it is showing', () => {
  // `/graph/entities?name=` is a substring filter, so twenty matches needs an
  // ordinary short name, not a pathological one. Red against an uncapped
  // picker: that one draws twenty buttons inside a paragraph of prose and
  // never says it did.
  const candidates = Array.from({ length: 20 }, (_unused, index) =>
    node(`e${String(index)}`, `Constantine ${String(index)}`),
  )
  render(
    <ResolvedFrame reference={{ state: 'ambiguous', candidates, truncated: false }} name="Constant">
      {() => <p>never</p>}
    </ResolvedFrame>,
  )

  expect(screen.getAllByRole('button')).toHaveLength(8)
  expect(screen.getByText(/20 entities in this project match that name/)).toBeInTheDocument()
  // The count of what was left out is the whole point: a reader who does not
  // find their entity among eight must not conclude it is absent.
  expect(screen.getByText(/showing the first 8/)).toBeInTheDocument()
})

it('says the count is a floor when the server held matches back', () => {
  // A capped search page cannot support a flat "12 entities share that name",
  // which is a claim about the graph rather than about what came back.
  const candidates = Array.from({ length: 12 }, (_unused, index) =>
    node(`e${String(index)}`, `Constantine ${String(index)}`),
  )
  render(
    <ResolvedFrame reference={{ state: 'ambiguous', candidates, truncated: true }} name="Constant">
      {() => <p>never</p>}
    </ResolvedFrame>,
  )

  expect(screen.getByText(/At least 12 entities/)).toBeInTheDocument()
})

it('says nothing about a cap when every candidate fits', () => {
  render(
    <ResolvedFrame
      reference={{
        state: 'ambiguous',
        candidates: [node('e1', 'Constantine', 'Person'), node('e2', 'Constantine', 'Place')],
        truncated: false,
      }}
      name="Constantine"
    >
      {() => <p>never</p>}
    </ResolvedFrame>,
  )

  expect(screen.queryByText(/showing the first/)).not.toBeInTheDocument()
  expect(screen.queryByText(/At least/)).not.toBeInTheDocument()
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
