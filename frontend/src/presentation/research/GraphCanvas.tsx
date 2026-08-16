import { memo, useEffect, useMemo, useRef, useState } from 'react'
import ForceGraph2D, { type ForceGraphMethods } from 'react-force-graph-2d'

import type { GraphView } from '@domain/knowledge/graph.ts'

import { colorForType, KIND_TOKENS } from './entity-colors.ts'
import { framing, nodeRadius } from './graph-framing.ts'

/** A node as `react-force-graph-2d` hands it back once its simulation has
 *  positioned it: the `GraphNode` fields, plus the `x`/`y` the simulation
 *  wrote in and the `fx`/`fy` it will read to pin a node in place. */
interface SimulatedNode {
  id: string
  x?: number
  y?: number
  fx?: number
  fy?: number
}

/** How close focusing a node brings the view, and how long the move takes.
 *
 * A floor rather than a fixed zoom: `focusOn` never zooms *out* to reach it.
 * On a graph of four nodes the fitted view is already closer than this, and
 * pulling back to a fixed level as the reward for clicking something would
 * be the opposite of the ask.
 */
const FOCUS_ZOOM = 2.5
const FOCUS_MS = 600

/** The whole-graph framing's transition and its margin, unchanged from the
 *  `zoomToFit(400, 48)` this replaced. */
const FIT_MS = 400
const FIT_PADDING = 48

/** The force-directed drawing of a `GraphView`. The only module in this
 *  console that imports `react-force-graph-2d` -- `GraphPane` loads this
 *  one lazily, so the ~60 kB canvas/d3-force bundle is fetched only when a
 *  reader actually opens the research page's graph pane, never as part of
 *  rendering a session transcript.
 *
 * `graphData` is memoised on `view` rather than rebuilt every render.
 * `expand`'s node-identity guarantee (existing nodes keep their object
 * reference) means the underlying d3-force simulation keeps each node's
 * `x`/`y` regardless of whether `graphData` is a fresh object -- but
 * `react-force-graph-2d` re-ingests and reheats its simulation whenever the
 * `graphData` *object itself* changes identity, independently of whether
 * the nodes inside it did. `GraphPane` re-renders on every keystroke in its
 * search box (typing changes `results`/`searching`, not `view`), so without
 * this memo the graph would reheat and visibly shake while a reader typed,
 * even though nothing about the drawn graph had changed.
 */
export const GraphCanvas = memo(function GraphCanvas({
  view,
  selected,
  onNodeClick,
}: {
  view: GraphView
  /** Ringed on the canvas, so the panel describing an entity and the drawing
   *  agree about which one it is. Without it the reader has a name in a panel
   *  and a field of identical dots, and no way to tell which dot it is. */
  selected: string | null
  onNodeClick: (id: string) => void
}) {
  const graphData = useMemo(() => ({ nodes: [...view.nodes], links: [...view.links] }), [view])

  /** How big a node is drawn, which depends on how many there are -- see
   *  `nodeRadius`. Read by the painter, the hit area and the library's own
   *  bounding-box maths, all three of which have to agree. */
  const radius = nodeRadius(view.nodes.length)

  // Measured, not left to the library: force-graph defaults `width` to
  // `window.innerWidth`, and this canvas lives in one column of a two-column
  // grid. That default draws a canvas several times the pane's width and
  // centres the simulation at `width / 2`, which puts the whole graph off to
  // the right of the only part of it a reader can see -- the drawing is there,
  // just not where they are looking.
  //
  // A `ResizeObserver` rather than a one-off measurement on mount: the pane is
  // a grid column, so it changes width whenever the window does, and a width
  // captured once would be wrong for the rest of the session.
  // Height is measured for the same reason, and it is why there is no fixed
  // pixel height here any more: the canvas fills the stage it is given, so the
  // graph gets whatever room the viewport has rather than a hardcoded 360px
  // box inside a page that scrolls past it.
  const container = useRef<HTMLDivElement | null>(null)
  const [size, setSize] = useState<{ width: number; height: number } | null>(null)

  // The number of nodes the view was last framed at. An expansion drops new
  // nodes wherever the simulation happens to fling them, which for a
  // well-connected entity is mostly outside the stage -- so the graph grows and
  // the reader watches the part they were already looking at, with no way to
  // know anything arrived. Refitting when the count changes puts the whole
  // drawing back in view.
  //
  // Keyed on the count rather than fitting on every settle: the simulation
  // re-settles after a drag or a zoom too, and refitting there would yank the
  // view back from wherever the reader had just put it.
  const graph = useRef<ForceGraphMethods | undefined>(undefined)
  const framedAt = useRef<number>(0)

  /** The zoom the last frame was painted at. The node painter is told it; the
   *  hit-area painter is not, and both have to agree on how big a node is. */
  const scale = useRef<number>(1)

  /** The node the view has already been moved to, so a re-render does not
   *  re-run the move and a settle does not repeat it. */
  const focused = useRef<string | null>(null)

  /** Bring `id` to the middle of the stage, close enough to read.
   *
   * `false` when the node has no position yet -- d3-force writes `x`/`y`
   * during the first tick, so a node selected before the simulation has run
   * (a pasted `/entity/<id>` link, say) cannot be centred at the moment it
   * is asked for. `onEngineStop` picks that case up once there is somewhere
   * to centre on.
   */
  const focusOn = (id: string): boolean => {
    const node = graphData.nodes.find((candidate) => candidate.id === id) as
      SimulatedNode | undefined
    if (!node || node.x === undefined || node.y === undefined) return false

    const api = graph.current
    if (!api) return false
    api.centerAt(node.x, node.y, FOCUS_MS)
    api.zoom(Math.max(api.zoom(), FOCUS_ZOOM), FOCUS_MS)
    return true
  }

  /** Put the whole drawing on the stage, at a bounded distance.
   *
   * Not `zoomToFit`, which is the library's version of this and has no ceiling
   * -- see `MAX_FIT_ZOOM` for the measurement. Everything else here is what
   * `zoomToFit` does: its own bounding box, its own centre, its own padding.
   */
  const fit = () => {
    const api = graph.current
    if (!api || size === null) return
    const frame = framing(api.getGraphBbox(), size.width, size.height, FIT_PADDING)
    if (!frame) return
    api.centerAt(frame.x, frame.y, FIT_MS)
    api.zoom(frame.zoom, FIT_MS)
  }

  /** Move to the selection as soon as there is one.
   *
   * Selecting a node and having the view stay where it was is the reason a
   * reader has to go hunting for the thing they just clicked -- on a graph
   * drawn whole that is a ringed dot somewhere in a field of five hundred.
   * Every selection arrives here, whichever gesture made it: a canvas click,
   * a search result, or the entity named in the URL on load.
   */
  useEffect(() => {
    if (selected === null) {
      focused.current = null
      return
    }
    if (focused.current === selected) return
    if (focusOn(selected)) focused.current = selected
    // `size` is in here because the library is not rendered at all until the
    // container has been measured (see below), so on the very first pass
    // there is no handle to drive and the move silently does nothing. The
    // measurement landing is what makes the retry possible.
    //
    // `focusOn` itself is left out: it closes over `graphData`, which is
    // already a dependency, and including a function rebuilt every render
    // would re-issue the move mid-animation on every keystroke in the search
    // box above.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selected, graphData, size])

  // Resolved once from the stylesheet. `getComputedStyle` is a layout read, and
  // the canvas painter runs per node per frame -- doing it there would be a
  // forced reflow sixty times a second.
  const theme = useMemo(() => {
    const styles = getComputedStyle(document.documentElement)
    const token = (name: string, fallback: string) =>
      styles.getPropertyValue(name).trim() || fallback
    return {
      palette: KIND_TOKENS.map((name) => token(name, '#6ba7f5')),
      label: token('--fg', '#d7dee7'),
      accent: token('--accent', '#e2a457'),
      mono: token('--mono', 'monospace'),
      link: token('--link', 'rgba(138, 149, 163, 0.35)'),
      linkInferred: token('--link-inferred', 'rgba(138, 149, 163, 0.18)'),
    }
  }, [])

  useEffect(() => {
    const element = container.current
    if (!element) return

    const measure = () =>
      setSize((previous) =>
        previous?.width === element.clientWidth && previous?.height === element.clientHeight
          ? // Same box: returning the previous object keeps this from
            // re-rendering, which matters because a re-render that changed
            // `size` identity would rebuild nothing but would still run on
            // every observer callback during a drag-resize.
            previous
          : { width: element.clientWidth, height: element.clientHeight },
      )
    measure()

    // Absent in some test environments, where the single measurement above is
    // all this needs to do.
    if (typeof ResizeObserver === 'undefined') return
    const observer = new ResizeObserver(measure)
    observer.observe(element)
    return () => observer.disconnect()
  }, [])

  return (
    // `absolute inset-0` against `GraphBrowser`'s `relative`, which is what
    // gives this element a real box for the `ResizeObserver` above to measure.
    // The canvas keeps reading its palette through `getComputedStyle` on the
    // document element (see `entity-colors.ts`): a `<canvas>` inherits no class,
    // so utilities can dress its container and nothing else.
    <div ref={container} data-graph-canvas className="absolute inset-0">
      {/* Withheld until the container has been measured: handing the library
          no width at all lets it fall back to the window for one frame, which
          is the very layout this is avoiding. */}
      {size === null ? null : (
        <ForceGraph2D
          ref={graph}
          width={size.width}
          height={size.height}
          graphData={graphData}
          // Fired when the simulation comes to rest, which is the first moment
          // the node positions are worth framing. `zoomToFit` before then
          // frames wherever the nodes were mid-flight.
          // force-graph's default is 15 seconds, which is how long the
          // simulation keeps running after it has visibly stopped moving --
          // and, because the framing below waits for it, how long the graph
          // used to sit unframed after an expansion. A neighbourhood of this
          // size settles in well under two.
          cooldownTime={1800}
          onEngineStop={() => {
            const settledAt = graphData.nodes.length

            // A selection made before the simulation had positioned anything
            // -- a pasted `/entity/<id>` link -- is only centreable now. This
            // is the one place that case gets picked up.
            if (selected !== null && focused.current !== selected && focusOn(selected)) {
              focused.current = selected
              framedAt.current = settledAt
              return
            }

            // Nothing is re-framed while a node is selected. Expanding one
            // pulls in new nodes and settles again, and fitting the whole
            // graph at that moment would zoom straight back out from the node
            // the reader had just clicked to look at -- undoing the move
            // above, every time, a moment after it finished.
            if (selected !== null) {
              framedAt.current = settledAt
              return
            }

            if (framedAt.current === settledAt) return
            framedAt.current = settledAt
            fit()
          }}
          // A node's date, appended when it has one: a temporal edge points
          // at two nodes, and a reader checking what it asserts needs the
          // dates on both ends, not just the derivation text on the line
          // between them. Most entities are not events and carry no date --
          // the ordinary case leaves the label as it was, not "(undated)".
          // The painted label on the canvas itself is untouched; see its own
          // comment for why it stays short.
          nodeLabel={(node) =>
            node.temporal
              ? `${String(node.name)} (${String(node.entityType)}) -- ${String(node.temporal)}`
              : `${String(node.name)} (${String(node.entityType)})`
          }
          // An inferred edge's label is the arithmetic that produced it (e.g.
          // "1923 contains November 1923"), not `relationshipType` -- the
          // dashes below already say "inferred", so restating that word on
          // hover would tell a reader nothing the line hadn't already.
          // `derivation` can be null for an edge that predates the field
          // (schema-evolution case, not defensive boilerplate) -- fall back
          // to `relationshipType` rather than let `String(null)` render the
          // literal text "null" in the hover tooltip.
          linkLabel={(link) =>
            link.inferred && link.derivation
              ? String(link.derivation)
              : String(link.relationshipType)
          }
          linkDirectionalArrowLength={4}
          // Dashed rather than a different hue: colour on this canvas already
          // means entity type (see the node painter's selection-ring comment
          // below), so giving inferred edges a second colour would trade that
          // fact for this one instead of adding it. The dimming is a change
          // of alpha within the same grey, not a new colour -- both literals
          // now live in `tokens.css` as `--link`/`--link-inferred`.
          //
          // Not asserted by any test: jsdom paints nothing to a `<canvas>`,
          // and a browser-mode test screenshotting one would be asserting on
          // pixels rather than on anything this suite can judge. Verified by
          // eye instead -- see the task report.
          linkColor={(link) => (link.inferred ? theme.linkInferred : theme.link)}
          linkLineDash={(link) => (link.inferred ? [2, 2] : null)}
          // Told to the library as well as used by the painter below, because
          // `getGraphBbox` -- and so the framing -- pads the box by this
          // number. A graph framed as if its marks were 5px while they are
          // drawn at 10px clips half of every node on the edge of the drawing.
          nodeRelSize={radius}
          // Names are drawn on the canvas rather than left to the hover
          // tooltip: a field of identical unlabelled dots gives a reader
          // nothing to aim at, so finding anything means hovering every node
          // in turn. The label is what makes the drawing readable at a glance
          // and the click worth making.
          nodeCanvasObject={(node, ctx, globalScale) => {
            const { x = 0, y = 0 } = node as SimulatedNode
            const color = colorForType(String(node.entityType), theme.palette)

            // Remembered for the hit area below, which is painted on a
            // separate pass that is not told the zoom.
            scale.current = globalScale

            // Divided by the zoom, so the dot is the same size on screen at
            // every zoom level. Drawn in graph units it would be a 5px mark
            // when the graph was small and a blob wider than its own label
            // once the view was fitted to a handful of nodes.
            const r = radius / globalScale

            // Filled means explored, hollow means there is more behind it.
            //
            // Every dot looked the same whether its neighbourhood had already
            // been pulled in or not, so the only way to find the edge of what
            // you had drawn was to click nodes at random and watch for one
            // that added something. On a graph of thirty nodes that is thirty
            // clicks to find the frontier. The ring is the frontier.
            ctx.beginPath()
            ctx.arc(x, y, r, 0, 2 * Math.PI)
            if (view.expanded.has(String(node.id))) {
              ctx.fillStyle = color
              ctx.fill()
            } else {
              ctx.strokeStyle = color
              ctx.lineWidth = 1.5 / globalScale
              ctx.stroke()
            }

            // A ring rather than a different fill: the fill already carries
            // the entity type, and overriding it to show selection would trade
            // one fact for another instead of adding one.
            if (node.id === selected) {
              ctx.beginPath()
              ctx.arc(x, y, r + 3.5 / globalScale, 0, 2 * Math.PI)
              ctx.strokeStyle = theme.accent
              ctx.lineWidth = 1.5 / globalScale
              ctx.stroke()
            }

            // Below a certain zoom the labels collide into an unreadable mat,
            // and the shape of the graph is the only thing left worth seeing.
            if (globalScale < 0.7) return

            const name = String(node.name)
            // Long entity names are whole sentences in this corpus -- a fact
            // node is a full clause -- and drawing one in full would cover the
            // nodes around it.
            const label = name.length > 28 ? `${name.slice(0, 27)}…` : name

            ctx.font = `${11 / globalScale}px ${theme.mono}`
            ctx.textAlign = 'center'
            ctx.textBaseline = 'top'
            ctx.fillStyle = theme.label
            ctx.fillText(label, x, y + (radius + 3) / globalScale)
          }}
          // The painted circle is 5px, but the hit area should not be: a
          // reader aiming at a labelled node is aiming at the label too.
          nodePointerAreaPaint={(node, color, ctx) => {
            const { x = 0, y = 0 } = node as SimulatedNode
            ctx.fillStyle = color
            ctx.beginPath()
            // Tracks the painted dot, and is a little larger than it: a reader
            // aiming at a labelled node is aiming at the label too. Derived
            // from `radius` rather than the 9 it used to be a constant of, so
            // the two stay in step when density changes the mark's size.
            ctx.arc(x, y, (radius + 4) / scale.current, 0, 2 * Math.PI)
            ctx.fill()
          }}
          onNodeClick={(node) => {
            // Pin the focused node at its current simulated position so it
            // stays put while the neighbourhood pulled in around it settles --
            // without this, expanding a node lets the whole graph drift, since
            // nothing anchors the point the reader is actually looking at.
            const pinned = node as SimulatedNode
            if (pinned.x !== undefined) pinned.fx = pinned.x
            if (pinned.y !== undefined) pinned.fy = pinned.y
            onNodeClick(String(node.id))
          }}
        />
      )}
    </div>
  )
})
