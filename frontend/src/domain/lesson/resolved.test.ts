/** Turning a name search into one of four render states.
 *
 * The whole reason this is a fold rather than a branch inside the hook: the
 * "exact match wins over a substring" rule is the difference between
 * `Constantine` resolving and `Constantine` being ambiguous with
 * `Constantinople`, and that rule deserves a test that needs no DOM and no
 * fake repository to state.
 */
import { describe, expect, it } from 'vitest'

import type { GraphNode } from '@domain/knowledge/graph.ts'
import { ComponentId } from '@domain/shared/identifier.ts'

import type { ComponentBlock } from './document.ts'
import { matchEntities, readEntityReference } from './resolved.ts'

const node = (id: string, name: string, entityType = 'Person'): GraphNode => ({
  id,
  name,
  entityType,
})

const block = (data: Record<string, unknown>): ComponentBlock => ({
  kind: 'component',
  id: ComponentId('c1'),
  type: 'definition',
  data,
  raw: '',
  lang: 'component:definition',
  unknown: false,
  errors: [],
  withheld: [],
  resolved: true,
})

describe('matchEntities', () => {
  it('resolves when exactly one entity comes back', () => {
    expect(matchEntities('Constantine', [node('e1', 'Constantine')])).toEqual({
      state: 'resolved',
      entity: node('e1', 'Constantine'),
    })
  })

  it('is missing when nothing comes back', () => {
    expect(matchEntities('Nobody', [])).toEqual({ state: 'missing' })
  })

  it('prefers the exact name over the substring that also matched', () => {
    // `/graph/entities?name=` is a substring, case-insensitive filter in
    // Python (`graph_reader.py:314`), so searching "Constantine" really does
    // return Constantinople too. Without this rule the commonest reference a
    // model writes about late antiquity is permanently ambiguous.
    const result = matchEntities('Constantine', [
      node('e1', 'Constantinople', 'Place'),
      node('e2', 'Constantine'),
    ])

    expect(result).toEqual({ state: 'resolved', entity: node('e2', 'Constantine') })
  })

  it('ignores case and surrounding space when judging an exact match', () => {
    const result = matchEntities('  constantine ', [
      node('e1', 'Constantinople', 'Place'),
      node('e2', 'Constantine'),
    ])

    expect(result).toEqual({ state: 'resolved', entity: node('e2', 'Constantine') })
  })

  it('is ambiguous when two entities carry the same exact name', () => {
    // Two real entities genuinely called "Constantine" is the case `entity_id`
    // exists for, and a picker is the only honest answer.
    const result = matchEntities('Constantine', [
      node('e1', 'Constantine', 'Person'),
      node('e2', 'Constantine', 'Place'),
    ])

    expect(result).toEqual({
      state: 'ambiguous',
      candidates: [node('e1', 'Constantine', 'Person'), node('e2', 'Constantine', 'Place')],
    })
  })

  it('is ambiguous when several match loosely and none matches exactly', () => {
    const result = matchEntities('Constant', [node('e1', 'Constantine'), node('e2', 'Constantius')])

    expect(result.state).toBe('ambiguous')
  })
})

describe('readEntityReference', () => {
  it('reads the name and the escape-hatch id', () => {
    expect(readEntityReference(block({ entity: 'Constantine', entity_id: 'e1' }))).toEqual({
      entity: 'Constantine',
      entityId: 'e1',
    })
  })

  it('defaults a missing id to null rather than undefined', () => {
    // `exactOptionalPropertyTypes` is on in this build, and a widget spreading
    // `{...(entityId ? {entityId} : {})}` past this boundary is exactly the
    // kind of drift the null makes impossible.
    expect(readEntityReference(block({ entity: 'Constantine' }))).toEqual({
      entity: 'Constantine',
      entityId: null,
    })
  })

  it('reads a missing entity as the empty string, not a throw', () => {
    // Same defaulting rule as every other reader in `widgets.ts`: a viewer
    // gets a widget that says it found nothing, never a blank page.
    expect(readEntityReference(block({}))).toEqual({ entity: '', entityId: null })
  })
})
