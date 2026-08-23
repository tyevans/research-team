import type { Meta, StoryObj } from '@storybook/react-vite'

import type { GraphNode, GraphView } from '@domain/knowledge/graph.ts'

import { GraphLegend } from './GraphLegend.tsx'

/** What the colours on the canvas mean, which is the difference between a
 *  drawing that carries information and one that is decorated.
 *
 * `GraphLegend.tsx` states the problem it was built for: a node's colour is
 * its entity type and a hollow node has an unfetched neighbourhood, and
 * neither fact was written anywhere. A reader could see that some dots were
 * blue and some green with no way to learn which was a `fact` and which a
 * `hypothesis`.
 *
 * Three rules the stories exist to keep checkable, and all three are about
 * *which* types appear rather than about how they look:
 *
 * - **Built from the drawn nodes, not from the corpus.** This is a key to the
 *   picture on screen; listing types that are not in it would make it a
 *   glossary. `TwoTypes` and `ManyTypes` are the same component over different
 *   drawings.
 * - **Commonest first.** The type a reader is looking at most of is the one
 *   worth naming first, and alphabetical order would bury it under whatever
 *   started with an `a`. `ManyTypes` is deliberately ordered so alphabetical
 *   and by-count disagree — if `artefact` is at the top, the sort has been
 *   changed.
 * - **Nothing drawn, nothing shown.** `types.length === 0` returns `null`
 *   rather than an empty panel floating over a blank canvas.
 *
 * **The colour is hashed, not tabled**, so a new entity type gets a stable
 * colour without anyone editing a lookup. What that costs is visible here and
 * nowhere else: two unrelated types can hash near each other, and the legend
 * is the only place a reader would notice. `ManyTypes` is where to look.
 */
const meta: Meta = {
  title: 'research/GraphLegend',
}

export default meta

type Story = StoryObj

const node = (id: string, entityType: string): GraphNode => ({
  id,
  name: id,
  entityType,
  temporal: null,
})

const view = (types: readonly (readonly [string, number])[]): GraphView => ({
  nodes: types.flatMap(([type, count]) =>
    Array.from({ length: count }, (_, i) => node(`${type}-${String(i)}`, type)),
  ),
  links: [],
  expanded: new Set(),
})

const Stage = ({ heading, children }: { heading: string; children: React.ReactNode }) => (
  <section style={{ padding: 'var(--space-3)' }}>
    <h3 style={{ font: 'inherit', color: 'var(--fg-faint)', margin: '0 0 var(--space-2)' }}>
      {heading}
    </h3>
    {/* A stage with something on it, because the legend is translucent on
        purpose -- it sits over the drawing, and a solid panel would hide
        whatever the simulation put underneath. Judged on a blank page it is
        being judged on the one thing it is not. */}
    <div
      style={{
        position: 'relative',
        height: 260,
        background:
          'repeating-linear-gradient(45deg, var(--bg-panel) 0 12px, var(--bg-panel-2) 12px 24px)',
        border: '1px solid var(--line)',
        borderRadius: 'var(--radius)',
      }}
    >
      {children}
    </div>
  </section>
)

/** The ordinary case: a drawing with two kinds of thing on it. */
export const TwoTypes: Story = {
  render: () => (
    <Stage heading="two types">
      <GraphLegend
        view={view([
          ['concept', 12],
          ['fact', 5],
        ])}
      />
    </Stage>
  ),
}

/** **Six types, ordered so alphabetical and by-count disagree.**
 *
 *  `person` is the commonest and must be first; `artefact` is the
 *  alphabetically first and must not be. If the list reads
 *  artefact/concept/event/… the sort has been changed to alphabetical and the
 *  reader is being shown whatever happened to start with an `a`.
 *
 *  This is also the story to look at for the hashing's cost: six types is
 *  enough for two of them to land on adjacent colours, and the legend is the
 *  only surface where a reader would ever notice that they had. */
export const ManyTypes: Story = {
  render: () => (
    <Stage heading="six types — commonest first, not alphabetical">
      <GraphLegend
        view={view([
          ['person', 41],
          ['place', 22],
          ['event', 14],
          ['concept', 9],
          ['artefact', 4],
          ['hypothesis', 2],
        ])}
      />
    </Stage>
  ),
}

/** One type. The legend still earns its place — it is the only thing that
 *  says what the single colour on screen means. */
export const OneType: Story = {
  render: () => (
    <Stage heading="one type">
      <GraphLegend view={view([['person', 30]])} />
    </Stage>
  ),
}

/** Nothing drawn.
 *
 *  The component returns `null` rather than an empty panel. A key to a picture
 *  that does not exist is worse than no key: it reads as a control that has
 *  failed to load. The stage below should be empty. */
export const NothingDrawn: Story = {
  render: () => (
    <Stage heading="empty graph — the legend draws nothing at all">
      <GraphLegend view={view([])} />
    </Stage>
  ),
}
