import { describe, expect, it } from 'vitest'

import { countMatching, groupMembers } from './course-members.ts'
import type { AreaMember } from './curriculum.ts'

const member = (over: Partial<AreaMember> & { name: string }): AreaMember => ({
  entityId: `id-${over.name}`,
  entityType: 'person',
  centrality: 1,
  temporal: null,
  ...over,
})

describe('groupMembers', () => {
  it('puts the largest type first, whatever order the server sent', () => {
    const groups = groupMembers([
      member({ name: 'Rubicon', entityType: 'place' }),
      member({ name: 'Caesar', entityType: 'person' }),
      member({ name: 'Pompey', entityType: 'person' }),
      member({ name: 'Crassus', entityType: 'person' }),
    ])

    expect(groups.map((group) => group.entityType)).toEqual(['person', 'place'])
  })

  /** The ordering this file exists to pin, and the one an alphabetical sort
   *  would silently satisfy on the case above: 'person' precedes 'place'
   *  alphabetically *and* is the larger group there, so that test passes under
   *  either rule. Here the larger group sorts later alphabetically, which is
   *  the only shape that tells the two apart -- CLAUDE.md's rule about
   *  parametrising over what distinguishes the candidate formulas rather than
   *  over a representative example. */
  it('puts the largest type first even when it sorts last by name', () => {
    const groups = groupMembers([
      member({ name: 'Caesar', entityType: 'person' }),
      member({ name: 'Rubicon', entityType: 'place' }),
      member({ name: 'Alesia', entityType: 'place' }),
      member({ name: 'Pharsalus', entityType: 'place' }),
    ])

    expect(groups.map((group) => group.entityType)).toEqual(['place', 'person'])
  })

  it('breaks a tie in size by type name, not by the order sent', () => {
    const groups = groupMembers([
      member({ name: 'Rubicon', entityType: 'place' }),
      member({ name: 'Caesar', entityType: 'person' }),
    ])

    expect(groups.map((group) => group.entityType)).toEqual(['person', 'place'])
  })

  it('orders a group by centrality, highest first', () => {
    const groups = groupMembers([
      member({ name: 'Crassus', centrality: 2 }),
      member({ name: 'Caesar', centrality: 9 }),
      member({ name: 'Pompey', centrality: 5 }),
    ])

    expect(groups[0]?.members.map((m) => m.name)).toEqual(['Caesar', 'Pompey', 'Crassus'])
  })

  /** Centrality first and name only as a tie-break. A sort on name alone would
   *  pass the previous test by coincidence -- 'Caesar' < 'Crassus' < 'Pompey'
   *  disagrees with it, so it would not, but this case makes the intent
   *  explicit: equal centrality is where the name is allowed to decide. */
  it('breaks equal centrality by name', () => {
    const groups = groupMembers([
      member({ name: 'Pompey', centrality: 4 }),
      member({ name: 'Caesar', centrality: 4 }),
    ])

    expect(groups[0]?.members.map((m) => m.name)).toEqual(['Caesar', 'Pompey'])
  })

  it('filters before grouping, so a type with no match loses its heading', () => {
    const groups = groupMembers(
      [
        member({ name: 'Caesar', entityType: 'person' }),
        member({ name: 'Rubicon', entityType: 'place' }),
      ],
      'caesar',
    )

    expect(groups.map((group) => group.entityType)).toEqual(['person'])
    expect(groups[0]?.members).toHaveLength(1)
  })

  it('matches a substring case-insensitively and ignores surrounding space', () => {
    expect(groupMembers([member({ name: 'Caesar' })], '  ESA  ')).toHaveLength(1)
  })

  it('treats a blank filter as no filter', () => {
    expect(countMatching([member({ name: 'Caesar' }), member({ name: 'Pompey' })], '   ')).toBe(2)
  })
})

describe('countMatching', () => {
  it('counts members across every group the filter keeps', () => {
    const members = [
      member({ name: 'Caesar', entityType: 'person' }),
      member({ name: 'Caesarea', entityType: 'place' }),
      member({ name: 'Pompey', entityType: 'person' }),
    ]

    expect(countMatching(members, 'caesar')).toBe(2)
    expect(countMatching(members)).toBe(3)
  })
})
