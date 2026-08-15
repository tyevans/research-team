import { useMemo, useState } from 'react'

import { laneRows, spanOf, type TimelineBand } from '@domain/knowledge/timeline.ts'

import { colorForType, KIND_TOKENS } from './entity-colors.ts'

/** Height of one packed row, and the gap above a lane's label. Constants
 *  rather than measured: the drawing is an SVG with its own coordinate space,
 *  so these are units in that space and not CSS pixels to be reconciled with
 *  anything. */
const ROW_HEIGHT = 22
const ROW_GAP = 4
const LANE_LABEL_HEIGHT = 18
const LANE_GAP = 12

/** How far outside the data's own span the axis reaches, as a fraction.
 *
 * Without it a band at the earliest date begins exactly on the left edge and
 * reads as clipped rather than as first. */
const AXIS_PADDING = 0.02

/** A band with an open bound runs this far past the axis before being clipped.
 *
 * A fraction of the span rather than "to the edge": drawn to the exact edge it
 * is indistinguishable from a band that merely starts early, and the whole
 * point of an open bound is that the reader can see it does not stop. */
const OPEN_OVERHANG = 0.06

/** The kind palette resolved to CSS colour values, once at module load.
 *
 * `colorForType` returns *an element of whatever palette it is handed* --
 * `KIND_TOKENS` are custom-property names (`'--k-session'`, ...), not
 * colours, so calling it with `KIND_TOKENS` directly yields a token name
 * rather than a paintable value (this is corrected from the brief, which did
 * exactly that). `GraphCanvas` resolves the same tokens with
 * `getComputedStyle` because its canvas painter needs literal colour strings
 * per frame; an SVG has no such per-frame cost, so wrapping each name as
 * `var(--k-session)` and leaving resolution to the CSS engine needs no ref,
 * no effect, and stays correct across a theme change with no JS at all. */
const PALETTE = KIND_TOKENS.map((name) => `var(${name})`)

/** Stroke colour for an unselected band. A fixed dim tone rather than
 *  `transparent`: `strokeDasharray` only draws anything if there is a stroke
 *  to dash, and an uncertain band needs its dashed outline visible whether or
 *  not it is selected -- that is the only way "circa 1850" and "1850" stay
 *  distinguishable, since they are drawn at identical widths by deliberate
 *  design (see `temporal_interval.py`). Selection changes colour and width
 *  on top of this rather than replacing "no stroke" with "a stroke". */
const STROKE_DEFAULT = 'var(--line)'

/** The project's dated entities as bars on a shared axis.
 *
 * Hand-rolled SVG rather than a charting library, and the reason is the bundle
 * budget rather than taste: `scripts/check-size.mjs` is a CI gate,
 * `react-force-graph-2d` already spends most of the allowance on the tab
 * beside this one, and a time axis is a linear scale plus a list of
 * rectangles. A library here would be paid for by whichever feature next runs
 * into the budget.
 *
 * Lazily imported by `TimelinePane` for the same reason `GraphCanvas` is: a
 * reader on a session transcript should not pay for a drawing they are not
 * looking at.
 *
 * Colour and stroke are applied through the `style` prop rather than the SVG
 * `fill=`/`stroke=` attributes: those are presentation attributes, and while
 * modern browsers accept `var(...)` in them inconsistently, the CSS `fill`/
 * `stroke` *properties* are the documented way to hand SVG a custom property,
 * and only the `style` prop reaches them from React.
 */
export const TimelineCanvas = ({
  bands,
  selected,
  onSelect,
}: {
  bands: readonly TimelineBand[]
  selected: string | null
  onSelect: (id: string) => void
}) => {
  // Zoom in axis units, not pixels: the SVG has its own coordinate space, so
  // keeping the transform there means a resize does not move the view.
  // `zoom` is a multiplier on the span. `pan` is read by `positionOf` below
  // but has no setter yet -- panning a zoomed-in timeline is left for a
  // future task, and the constant keeps the maths ready for it rather than
  // hardcoding zero inline everywhere it is used.
  const [zoom, setZoom] = useState(1)
  const pan = 0

  const lanes = useMemo(() => laneRows(bands), [bands])
  const span = useMemo(() => spanOf(bands), [bands])

  if (span === null) return null

  const rawWidth = span.to - span.from
  // A single-instant timeline -- one entity, or several sharing one date --
  // has a zero-width span, and every position in it would divide by zero. A
  // day either side is arbitrary and is the smallest window that still draws
  // the bar somewhere other than a vertical line at x=0.
  const width = rawWidth === 0 ? 86_400_000 : rawWidth
  const padded = width * (1 + AXIS_PADDING * 2)
  const origin = span.from - width * AXIS_PADDING

  /** An instant as a 0-1 position across the drawing, after zoom and pan. */
  const positionOf = (instant: number) => ((instant - origin) / padded) * zoom + pan

  const xOf = (iso: string | null, fallback: number) =>
    iso === null ? fallback : positionOf(Date.parse(iso))

  // Built with `reduce` rather than a `let` accumulator: the lint rule that
  // guards render purity (`react-hooks/immutability`) flags any variable
  // reassigned during render, and stacking lanes top-to-bottom is exactly
  // that shape done imperatively. The fold carries the running `y` as its
  // accumulator instead of a variable that survives across map calls.
  const { layout: laneLayout, total: laneTotal } = lanes.reduce<{
    layout: { lane: (typeof lanes)[number]; top: number }[]
    total: number
  }>(
    (state, lane) => {
      const top = state.total
      return {
        layout: [...state.layout, { lane, top }],
        total: top + LANE_LABEL_HEIGHT + lane.rows * (ROW_HEIGHT + ROW_GAP) + LANE_GAP,
      }
    },
    { layout: [], total: 0 },
  )

  return (
    <svg
      role="img"
      aria-label="Timeline of dated entities"
      viewBox={`0 0 1000 ${Math.max(laneTotal, 1)}`}
      preserveAspectRatio="none"
      className="h-full w-full"
      onWheel={(event) => {
        event.preventDefault()
        // Multiplicative, so a step out undoes a step in exactly. Additive
        // zoom drifts: ten steps in and ten out does not return to 1.
        setZoom((current) => Math.min(Math.max(current * (event.deltaY < 0 ? 1.1 : 1 / 1.1), 1), 50))
      }}
    >
      {laneLayout.map(({ lane, top }) => (
        <g key={lane.entityType} data-lane={lane.entityType}>
          <text
            x={4}
            y={top + 12}
            className="fill-fg-dim text-xs"
            // Not `pointer-events-none` via a utility: this is inside an SVG,
            // where Tailwind's pointer utilities apply but the label is also
            // the only affordance naming the lane, so it stays selectable.
          >
            {lane.entityType}
          </text>
          {lane.bands.map(({ band, row }) => {
            const left = xOf(band.start, positionOf(origin) - OPEN_OVERHANG)
            const right = xOf(band.end, positionOf(origin + padded) + OPEN_OVERHANG)
            const rowTop = top + LANE_LABEL_HEIGHT + row * (ROW_HEIGHT + ROW_GAP)
            const isSelected = band.id === selected
            const isUncertain = band.uncertainty !== 'EXACT' && band.uncertainty !== ''
            return (
              <g key={band.id}>
                <rect
                  data-band={band.id}
                  data-selected={isSelected ? 'true' : undefined}
                  data-uncertainty={band.uncertainty}
                  x={left * 1000}
                  y={rowTop}
                  // Floored at 2 so an instant-precision band is still a
                  // visible mark and still clickable. A zero-width rect is
                  // neither, and an entity that vanishes at some zoom levels
                  // reads as missing data.
                  width={Math.max((right - left) * 1000, 2)}
                  height={ROW_HEIGHT}
                  rx={3}
                  style={{
                    fill: colorForType(band.entityType, PALETTE),
                    // Dashed for anything the extraction was not certain of,
                    // so "circa 1850" and "1850" are distinguishable -- see
                    // `STROKE_DEFAULT` above for why an unselected band still
                    // needs a real stroke to dash.
                    strokeDasharray: isUncertain ? '4 3' : undefined,
                    stroke: isSelected ? 'var(--accent)' : STROKE_DEFAULT,
                    strokeWidth: isSelected ? 2 : 1,
                  }}
                  className="cursor-pointer"
                  onClick={() => onSelect(band.id)}
                >
                  <title>{`${band.name} — ${band.extent}`}</title>
                </rect>
                <text
                  x={left * 1000 + 5}
                  y={rowTop + 15}
                  className="pointer-events-none fill-fg text-xs"
                >
                  {band.name}
                </text>
              </g>
            )
          })}
        </g>
      ))}
    </svg>
  )
}
