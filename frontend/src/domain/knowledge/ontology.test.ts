import { expect, it } from 'vitest'

import type { OntologyPayload } from './ontology.ts'
import { childrenOf, foldOntology } from './ontology.ts'

const aClass = (over: Partial<OntologyPayload['classes'][number]> = {}) => ({
  id: 'c1',
  name: 'Difficulty',
  kind: 'ordered_scale',
  declaredCount: null,
  memberCount: 0,
  parentClassId: null,
  evidence: { sourceId: 'songs', start: 0, end: 66 },
  rejectedMembers: [],
  stale: false,
  evidenceQuoted: true,
  members: [],
  ...over,
})

const payload = (...classes: OntologyPayload['classes'][number][]): OntologyPayload => ({
  classes,
})

/** Fold one class and hand it back, asserting exactly one came out.
 *
 * `const [x] = foldOntology(...)` types `x` as possibly undefined under
 * `noUncheckedIndexedAccess`, and every test below would need its own
 * non-null assertion. This puts the check in one place and makes it a real
 * assertion rather than a `!`. */
const only = (...classes: OntologyPayload['classes'][number][]) => {
  const folded = foldOntology(payload(...classes))
  expect(folded).toHaveLength(1)
  return folded[0] as NonNullable<(typeof folded)[number]>
}

it('orders an ordered scale by ordinal, not by arrival', () => {
  // `D C B A S` is the case the design turns on: not alphabetical, not the
  // order it arrived in, and not recoverable from anything else on the row. A
  // fixture already in stated order would pass against a fold that never
  // sorted, which is why this one is deliberately scrambled.
  const rank = only(
    aClass({
      name: 'Rank',
      declaredCount: 5,
      members: [
        { name: 'B rank', ordinal: 2 },
        { name: 'S rank', ordinal: 4 },
        { name: 'D rank', ordinal: 0 },
        { name: 'C rank', ordinal: 1 },
        { name: 'A rank', ordinal: 3 },
      ],
    }),
  )

  expect(rank.members.map((member) => member.name)).toEqual([
    'D rank',
    'C rank',
    'B rank',
    'A rank',
    'S rank',
  ])
})

it('leaves an unordered set in arrival order', () => {
  // The inverse of the case above, and the reason `kind` is carried rather
  // than inferred from whether ordinals happen to be present: sorting a bag
  // would invent a sequence the document never stated.
  const cults = only(
    aClass({
      name: 'Cult',
      kind: 'unordered_set',
      members: [
        { name: 'Official cults', ordinal: null },
        { name: 'Mystery cults', ordinal: null },
      ],
    }),
  )

  expect(cults.members.map((member) => member.name)).toEqual(['Official cults', 'Mystery cults'])
})

it('sorts an unnumbered member to the end of a scale rather than the front', () => {
  // A partially-numbered scale still reads from its known end. Sorting nulls
  // first would put the one member whose position is unknown at the position
  // that looks most deliberate.
  const rank = only(
    aClass({
      members: [
        { name: 'unplaced', ordinal: null },
        { name: 'first', ordinal: 0 },
      ],
    }),
  )

  expect(rank.members.map((member) => member.name)).toEqual(['first', 'unplaced'])
})

it('reports a class whose members fall short of its stated count', () => {
  const difficulty = only(
    aClass({
      declaredCount: 6,
      members: [
        { name: 'EASY', ordinal: 0 },
        { name: 'MASTER', ordinal: 4 },
      ],
    }),
  )

  expect(difficulty.complete).toBe(false)
  expect(difficulty.declaredCount).toBe(6)
  expect(difficulty.members).toHaveLength(2)
})

it('treats a class that stated no count as complete', () => {
  // There is nothing to disagree with. Marking every uncounted class
  // incomplete would make the flag meaningless on the majority of them --
  // most documents name a group without counting it.
  const difficulty = only(aClass({ declaredCount: null, members: [{ name: 'EASY', ordinal: 0 }] }))

  expect(difficulty.complete).toBe(true)
})

it('keeps a class that samples a much larger set, with both numbers intact', () => {
  // Measured 2026-08-15 in `wiki-roman-economy`: "Inscriptions record 268
  // different occupations ... including fishermen, salt merchants, olive oil
  // dealers". Kept rather than dropped at some ratio threshold -- a threshold
  // would be a number nobody could justify, and a reader sees "9 of 268" for
  // what it is faster than any rule could classify it.
  const occupations = only(
    aClass({
      name: 'Occupation',
      kind: 'unordered_set',
      declaredCount: 268,
      members: Array.from({ length: 9 }, (_unused, index) => ({
        name: `trade ${index}`,
        ordinal: null,
      })),
    }),
  )

  expect(occupations.complete).toBe(false)
  expect(occupations.declaredCount).toBe(268)
  expect(occupations.members).toHaveLength(9)
})

it('carries rejections alongside the class that lost them', () => {
  // A short class with no explanation is unjudgeable: the reader cannot tell
  // an invented member from a document genuinely missing one, and those are
  // opposite conclusions about whether to trust the pass.
  const difficulty = only(
    aClass({
      declaredCount: 6,
      members: [{ name: 'EASY', ordinal: 0 }],
      rejectedMembers: [{ name: 'LEGEND', reason: 'not found in the document, verbatim' }],
    }),
  )

  expect(difficulty.rejectedMembers).toEqual([
    { name: 'LEGEND', reason: 'not found in the document, verbatim' },
  ])
})

it('reads an unknown kind as an unordered set rather than crashing', () => {
  // Unreachable through the ordinary path -- the server refuses a kind it does
  // not know. It exists so a future server vocabulary does not break an older
  // bundle, and `unordered_set` is the safe landing: it is the only kind that
  // asserts nothing, where `ordered_scale` would claim an ordering.
  const odd = only(aClass({ kind: 'spectrum', members: [{ name: 'one', ordinal: 3 }] }))

  expect(odd.kind).toBe('unordered_set')
  expect(odd.members.map((member) => member.name)).toEqual(['one'])
})

it('groups nested classes under their parent', () => {
  const classes = foldOntology(
    payload(
      aClass({ id: 'version', name: 'Song version', kind: 'taxonomy' }),
      aClass({ id: 'purchased', name: 'Purchased separately', parentClassId: 'version' }),
    ),
  )

  expect(childrenOf(classes, null).map((klass) => klass.id)).toEqual(['version'])
  expect(childrenOf(classes, 'version').map((klass) => klass.id)).toEqual(['purchased'])
})
