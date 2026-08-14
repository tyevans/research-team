import { useMemo } from 'react'

import type { GraphView } from '@domain/knowledge/graph.ts'

import { colorForType, KIND_TOKENS } from './entity-colors.ts'

/** A rule about the drawing rather than another category, ruled off from the
 *  swatches above it. Both notes below share it, which is why it is a constant:
 *  they can appear together, and the second's top edge is what separates them.
 *
 * `border-0` before `border-t border-solid`, per the house rule: `border-solid`
 * styles all four sides, so without the zero the three sides with no explicit
 * width fall back to the browser's `medium` and a rule for one edge draws a
 * box. `graph-legend.browser.test.tsx` measures exactly that. */
const NOTE =
  'mx-0 mb-0 mt-2 border-0 border-t border-solid border-t-line pt-2 leading-[1.4] text-fg-dim'

/** What the colours and the two node shapes on the canvas mean.
 *
 * The drawing already carried both facts -- a node's colour is its entity
 * type, and a hollow node has a neighbourhood nobody has pulled in yet -- and
 * neither was written down anywhere. A reader could see that some dots were
 * blue and some were green without any way to learn which was a `fact` and
 * which a `hypothesis`, so the colour was decoration rather than information.
 *
 * Built from the drawn nodes rather than from every type in the corpus: this
 * is a key to the picture on screen, and listing types that are not in it
 * would be a glossary instead.
 */
export const GraphLegend = ({ view }: { view: GraphView }) => {
  const palette = useMemo(() => {
    const styles = getComputedStyle(document.documentElement)
    return KIND_TOKENS.map((name) => styles.getPropertyValue(name).trim() || '#6ba7f5')
  }, [])

  const types = useMemo(() => {
    const counts = new Map<string, number>()
    for (const node of view.nodes) {
      counts.set(node.entityType, (counts.get(node.entityType) ?? 0) + 1)
    }
    // Commonest first: the type a reader is looking at most of is the one
    // worth naming first, and alphabetical order would bury it under whatever
    // happened to start with an `a`.
    return [...counts.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
  }, [view.nodes])

  if (types.length === 0) return null

  return (
    // Bottom left, opposite the detail panel and below the command bar: the
    // three floating things on this stage each take a corner rather than
    // competing for one, and the legend is the one a reader consults least.
    //
    // `bg-[color-mix(…)]` rather than `bg-bg`: translucent on purpose, because
    // it sits over the drawing and a solid panel would hide whatever the
    // simulation put underneath it. There is no utility for a mix, and the
    // literal is the same one the rule carried.
    //
    // `text-[11px]` is the one size on this page that is not a step of the
    // scale, and it was not one before either -- `--text-xs` is 10.5px and
    // `--text-sm` is 12px, so rounding it to either would change the legend's
    // size rather than merely respell it. Carried across as an arbitrary value
    // so this rewrite stays a rewrite.
    //
    // `pointer-events-none`: it overlaps the canvas, and the canvas is the
    // thing being dragged.
    <aside
      className="lay-region-float pointer-events-none absolute bottom-3 left-3 max-w-[min(240px,calc(100%_-_20px))] rounded-md border border-solid border-line bg-[color-mix(in_srgb,var(--color-bg)_88%,transparent)] px-3 py-[8px] text-[11px]"
      aria-label="What the canvas colours mean"
    >
      <ul className="m-0 flex list-none flex-col gap-1 p-0">
        {types.map(([type, count]) => (
          <li key={type} className="grid grid-cols-[10px_1fr_auto] items-center gap-2">
            <span
              className="size-[8px] rounded-full"
              style={{ background: colorForType(type, palette) }}
              aria-hidden="true"
            />
            <span className="overflow-hidden text-ellipsis whitespace-nowrap text-fg">{type}</span>
            <span className="text-fg-dim tabular-nums">{count}</span>
          </li>
        ))}
      </ul>
      {/* The shape rule, in the one place somebody would look for it. Worth a
          line of prose rather than a second swatch column: it is a rule about
          what to do next -- click the hollow ones -- not another category.
          Withheld when there are none: on a graph drawn whole every node is
          filled, and a key explaining a shape that is not on the canvas sends
          the reader hunting for one. */}
      {view.nodes.some((node) => !view.expanded.has(node.id)) ? (
        <p className={NOTE}>Hollow nodes have more to pull in. Click one to expand it.</p>
      ) : null}
      {/* A sibling of the note above, on the same terms: prose rather than a
          swatch, because a dashed line is a rule about where an edge came
          from, not another category to swatch alongside entity types. And
          withheld the same way, when the drawn graph has no inferred edge --
          otherwise this key would explain a mark nobody can see. */}
      {view.links.some((link) => link.inferred) ? (
        <p className={NOTE}>
          Dashed edges are inferred from dates, not asserted by a document. Hover one to see the
          arithmetic.
        </p>
      ) : null}
    </aside>
  )
}
