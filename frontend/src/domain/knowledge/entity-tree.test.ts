import { describe, expect, it } from 'vitest'

import type { GraphNode } from './graph.ts'
import { groupByType } from './entity-tree.ts'

const node = (id: string, name: string, entityType: string): GraphNode => ({
  id,
  name,
  entityType,
})

describe('groupByType', () => {
  it('puts each entity under its own type, with the types in name order', () => {
    const groups = groupByType([
      node('1', 'Hinton', 'person'),
      node('2', 'Backprop', 'concept'),
      node('3', 'LeCun', 'person'),
    ])

    expect(
      groups.map((group) => ({
        entityType: group.entityType,
        names: group.entities.map((entity) => entity.name),
      })),
    ).toEqual([
      { entityType: 'concept', names: ['Backprop'] },
      { entityType: 'person', names: ['Hinton', 'LeCun'] },
    ])
  })

  it('sorts entities by name rather than by arrival', () => {
    const groups = groupByType([node('1', 'Zeta', 'concept'), node('2', 'Alpha', 'concept')])

    expect(groups.map((group) => group.entities.map((entity) => entity.name))).toEqual([
      ['Alpha', 'Zeta'],
    ])
  })

  /** Not a code-point sort: `Ångström` before `Zeta` is what a reader expects,
   *  and `'Å' > 'Z'` is what a naive comparison gives. Fails if `localeCompare`
   *  is replaced with `<`. */
  it('orders accented names the way a reader reads them', () => {
    const groups = groupByType([node('1', 'Zeta', 'concept'), node('2', 'Ångström', 'concept')])

    expect(groups.map((group) => group.entities.map((entity) => entity.name))).toEqual([
      ['Ångström', 'Zeta'],
    ])
  })

  it('filters on the name, case-insensitively, before grouping', () => {
    const groups = groupByType(
      [
        node('1', 'Hinton', 'person'),
        node('2', 'Backprop', 'concept'),
        node('3', 'LeCun', 'person'),
      ],
      'hint',
    )

    expect(
      groups.map((group) => ({
        entityType: group.entityType,
        names: group.entities.map((entity) => entity.name),
      })),
    ).toEqual([{ entityType: 'person', names: ['Hinton'] }])
  })

  /** The whole reason filtering happens before grouping: a filter that matched
   *  nothing in a type must remove that type's heading, not leave an empty one
   *  for the reader to open. Fails if the filter moves inside the groups. */
  it('leaves no empty group behind when a filter excludes a whole type', () => {
    const groups = groupByType(
      [node('1', 'Hinton', 'person'), node('2', 'Backprop', 'concept')],
      'hint',
    )

    expect(groups.map((group) => group.entityType)).toEqual(['person'])
  })

  it('is empty for no entities, and for a filter that matches none', () => {
    expect(groupByType([])).toEqual([])
    expect(groupByType([node('1', 'Hinton', 'person')], 'zzz')).toEqual([])
  })

  /** A blank or whitespace-only box is not a filter. Fails if the pane's
   *  empty-string term is passed straight through as a predicate. */
  it('treats a blank filter as no filter', () => {
    expect(groupByType([node('1', 'Hinton', 'person')], '   ')).toHaveLength(1)
  })
})
