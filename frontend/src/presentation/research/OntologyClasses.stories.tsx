import type { Meta, StoryObj } from '@storybook/react-vite'

import type { OntologyClass } from '@domain/knowledge/ontology.ts'

import { OntologyClasses } from './OntologyClasses.tsx'

/** Discovered classes, drawn so a reader can decide whether to believe them.
 *
 * `OntologyClasses.tsx` says why this exists when the classes are already on
 * the canvas: **a force-directed drawing cannot show order.** Five
 * `instance_of` spokes into a `Rank` hub are five identical lines whether or
 * not the ranks form a scale. So this list is the only surface where the
 * difference between a scale, a set and a taxonomy is visible at all — and
 * that difference is the whole claim a discovery pass makes.
 *
 * Three rules, each of which a single card cannot show:
 *
 * - **A set must not read as a sequence.** `OntologyMember.ordinal` is `null`
 *   in a set and is deliberately *not* derived from array order, because "a
 *   reader who saw an unordered set sorted by arrival would be reading a
 *   sequence into a bag". `AScale` beside `ASet` is the only place that is
 *   checkable.
 * - **`complete` is `true` when no count was stated.** Most documents name a
 *   group without counting it, and marking every uncounted class incomplete
 *   would make the flag meaningless on the majority. So an incompleteness
 *   marker means "the document said five and we found four", never "we did not
 *   count". `Incomplete` and `NoCountStated` are that pair.
 * - **A rejected member keeps its reason.** Verification refusing a proposal
 *   is information about the pass, not something to hide — a class with three
 *   accepted and two refused members is a different object from one with
 *   three.
 */
const meta: Meta = {
  title: 'research/OntologyClasses',
}

export default meta

type Story = StoryObj

const klass = (over: Partial<OntologyClass> & { id: string; name: string }): OntologyClass => ({
  kind: 'unordered_set',
  declaredCount: null,
  members: [],
  rejectedMembers: [],
  evidence: { sourceId: 'src-1', start: 120, end: 260 },
  parentClassId: null,
  stale: false,
  evidenceQuoted: true,
  complete: true,
  ...over,
})

const ordered = (names: readonly string[]) => names.map((name, index) => ({ name, ordinal: index }))

const unordered = (names: readonly string[]) => names.map((name) => ({ name, ordinal: null }))

const sourceHref = () => '#source'

const Frame = ({ heading, children }: { heading: string; children: React.ReactNode }) => (
  <section style={{ padding: 'var(--space-3)', maxWidth: 640 }}>
    <h3 style={{ font: 'inherit', color: 'var(--fg-faint)', margin: '0 0 var(--space-2)' }}>
      {heading}
    </h3>
    {children}
  </section>
)

/** **The pair the component exists for.** A scale and a set, one above the
 *  other.
 *
 *  The scale's members are positions and their order carries meaning. The
 *  set's are members of a bag and their order carries none — which is why
 *  `ordinal` is `null` there rather than being inferred from the array. On the
 *  canvas these two are the same five spokes.
 *
 *  What to check: the two read as different *kinds* of thing, not as one list
 *  with different labels. If a reader could mistake the set for a ranking, the
 *  distinction has stopped being drawn. */
export const AScaleAgainstASet: Story = {
  render: () => (
    <>
      <Frame heading="an ordered scale — position means something">
        <OntologyClasses
          classes={[
            klass({
              id: 'c1',
              name: 'Senatorial ranks',
              kind: 'ordered_scale',
              members: ordered(['Quaestor', 'Aedile', 'Praetor', 'Consul', 'Censor']),
            }),
          ]}
          sourceHref={sourceHref}
        />
      </Frame>
      <Frame heading="an unordered set — position means nothing">
        <OntologyClasses
          classes={[
            klass({
              id: 'c2',
              name: 'Tetrarchic capitals',
              kind: 'unordered_set',
              members: unordered(['Nicomedia', 'Sirmium', 'Mediolanum', 'Augusta Treverorum']),
            }),
          ]}
          sourceHref={sourceHref}
        />
      </Frame>
    </>
  ),
}

/** A taxonomy, which nests. `childrenOf` builds the tree from
 *  `parentClassId`, so a class with a parent must not also appear at the top
 *  level — a duplicated branch is the failure this shape can have. */
export const ATaxonomy: Story = {
  render: () => (
    <Frame heading="a taxonomy">
      <OntologyClasses
        classes={[
          klass({
            id: 'p1',
            name: 'Roman magistracies',
            kind: 'taxonomy',
            members: unordered(['Cursus honorum', 'Extraordinary commands']),
          }),
          klass({
            id: 'p2',
            name: 'Cursus honorum',
            kind: 'ordered_scale',
            parentClassId: 'p1',
            members: ordered(['Quaestor', 'Aedile', 'Praetor', 'Consul']),
          }),
          klass({
            id: 'p3',
            name: 'Extraordinary commands',
            kind: 'unordered_set',
            parentClassId: 'p1',
            members: unordered(['Dictator', 'Interrex']),
          }),
        ]}
        sourceHref={sourceHref}
      />
    </Frame>
  ),
}

/** **The other pair.** The document said five; four were found.
 *
 *  This is what an incompleteness marker is *for*, and it is only meaningful
 *  because the story below it exists. */
export const Incomplete: Story = {
  render: () => (
    <Frame heading="the document stated a count and the members do not match it">
      <OntologyClasses
        classes={[
          klass({
            id: 'c3',
            name: 'The five good emperors',
            kind: 'ordered_scale',
            declaredCount: 5,
            complete: false,
            members: ordered(['Nerva', 'Trajan', 'Hadrian', 'Antoninus Pius']),
          }),
        ]}
        sourceHref={sourceHref}
      />
    </Frame>
  ),
}

/** No count stated, which is the ordinary case.
 *
 *  `complete` is `true` here and the class carries no incompleteness marker —
 *  there is nothing to disagree with. Marking every uncounted class incomplete
 *  would make the flag meaningless on the majority of them, which is the
 *  reasoning `ontology.ts` records. Read this next to `Incomplete`: the marker
 *  has to be absent here or it means nothing there. */
export const NoCountStated: Story = {
  render: () => (
    <Frame heading="no count stated — not incomplete, just uncounted">
      <OntologyClasses
        classes={[
          klass({
            id: 'c4',
            name: 'Provinces mentioned',
            members: unordered(['Africa', 'Asia', 'Baetica', 'Gallia Narbonensis']),
          }),
        ]}
        sourceHref={sourceHref}
      />
    </Frame>
  ),
}

/** Members verification refused, with the reasons.
 *
 *  A class with three accepted and two refused members is a different object
 *  from one with three, and hiding the refusals would make the pass look more
 *  confident than it was. */
export const WithRejectedMembers: Story = {
  render: () => (
    <Frame heading="proposals verification refused">
      <OntologyClasses
        classes={[
          klass({
            id: 'c5',
            name: 'Tetrarchs',
            declaredCount: 4,
            members: unordered(['Diocletian', 'Maximian', 'Galerius', 'Constantius']),
            rejectedMembers: [
              { name: 'Constantine', reason: 'acclaimed after the tetrarchy had lapsed' },
              { name: 'Licinius', reason: 'named in the source as a successor, not a tetrarch' },
            ],
          }),
        ]}
        sourceHref={sourceHref}
      />
    </Frame>
  ),
}

/** The graph beneath the class has moved since it was found.
 *
 *  A stale class is not a wrong one — it is one whose evidence may no longer
 *  match the entities under it. It must read as "check this", not as
 *  "discard this". */
export const Stale: Story = {
  render: () => (
    <Frame heading="the graph moved under it">
      <OntologyClasses
        classes={[
          klass({
            id: 'c6',
            name: 'Tetrarchic capitals',
            stale: true,
            members: unordered(['Nicomedia', 'Sirmium', 'Mediolanum']),
          }),
        ]}
        sourceHref={sourceHref}
      />
    </Frame>
  ),
}

/** Nothing found yet. Names the action that would change that, rather than
 *  reporting an absence and stopping. */
export const NothingFound: Story = {
  render: () => (
    <Frame heading="no classes">
      <OntologyClasses classes={[]} sourceHref={sourceHref} />
    </Frame>
  ),
}
