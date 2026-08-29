import type { ReactNode } from 'react'

/** The stream's shared primitives.
 *
 * Seven shape components must not each invent a bar. The reason is the same
 * one that rejected a multi-column grid: a bar means something only if every
 * bar on the page is drawn on one axis with one baseline, and seven private
 * implementations of "a track with a fill in it" is how that stops being true
 * without anything going red.
 *
 * Nothing here reads an artifact. A part takes numbers and text, so a shape
 * component stays the only place that knows what a field is called. */

/** Which end of the stream a row is at.
 *
 * The console's three states collapse to two renderings: a turn in flight, and
 * everything settled — committed and scrubbed-to are identical, because the
 * scrub position is the pane's state and `ScrubBar` already shows it. Saying
 * it per row would be the banner defect again.
 *
 * **No geometry may differ between the two.** */
export type Phase = 'live' | 'settled'

/** What every shape component takes.
 *
 * `tool` is `message.name` — the tool that actually produced this artifact,
 * not the tool the shape was designed around. A shape is a visual grammar
 * shared by several tools (`hit_list` serves both `search_sources` and
 * `web_search`), so a hard-coded name in the header is wrong for every tool
 * but one, and wrong in a way that reads as authoritative. The fallback is the
 * commonest producer, for the messages written before `name` reached the
 * browser. */
export interface ShapeProps<T> {
  artifact: T
  phase: Phase
  tool?: string | null
}

const clamp = (value: number) => Math.max(0, Math.min(100, value))

/** A proportion, to two places.
 *
 * Two rather than none because a ruler over a 25,000-character document moves
 * by less than a whole percent per paragraph, and rounding to integers there
 * makes two different excerpts draw the same mark. Zero when the denominator
 * is missing or zero, which is what a tool that found nothing reports. */
export const percent = (value: number, total: number): number =>
  total > 0 ? Number(clamp((value / total) * 100).toFixed(2)) : 0

/** `1529` as `1.5k`.
 *
 * Character offsets are the excerpt shape's unit and they are four and five
 * digits wide; printed in full they push the header's argument off the line,
 * which is the field a reader is actually scanning for. */
export const compact = (n: number): string => {
  if (!Number.isFinite(n)) return '—'
  if (Math.abs(n) < 1000) return String(Math.round(n))
  if (Math.abs(n) < 1_000_000) return `${(n / 1000).toFixed(1)}k`
  return `${(n / 1_000_000).toFixed(1)}m`
}

/** One row of the stream: the spine, its glyph, and an indented body.
 *
 * The spine replaces per-card borders. A border around content already
 * indented behind a rule draws the same boundary twice, and that doubled
 * chrome is most of what makes the current feed feel heavy. */
export const Row = ({
  glyph,
  phase,
  tone,
  children,
}: {
  glyph: string
  phase: Phase
  tone?: 'ok' | 'fail'
  children: ReactNode
}) => (
  <div className="stream-row" data-phase={phase}>
    <div className="stream-gutter" data-testid="stream-gutter">
      <span
        className="stream-glyph"
        data-testid="stream-glyph"
        data-phase={phase}
        {...(tone ? { 'data-tone': tone } : {})}
        aria-hidden="true"
      >
        {glyph}
      </span>
    </div>
    <div className="stream-body" data-testid="stream-body">
      {children}
    </div>
  </div>
)

/** `tool_name · argument · count`, and the call and its result are one row.
 *
 * `arg` is the source's *title*, resolved from the artifact —
 * `manuscriptreport.com · types of fictional genres`, not
 * `manuscriptreport-com-blog-types-of-fictional-genres-42e281d8`. The raw id
 * goes to `title`, because that is what a bug report needs and nothing else
 * does. */
export const Header = ({
  name,
  arg,
  count,
  title,
}: {
  name: string
  arg?: ReactNode
  count?: ReactNode
  title?: string
}) => (
  <div className="stream-h">
    <b className="stream-name">{name}</b>
    {arg === undefined ? null : (
      <span className="stream-arg" {...(title ? { title } : {})}>
        {arg}
      </span>
    )}
    {count === undefined ? null : <span className="stream-cnt">{count}</span>}
  </div>
)

/** One list line: name, bar, value, on the three columns every list shares. */
export const Item = ({
  name,
  detail,
  linked = true,
  mark,
  value,
  testId,
}: {
  name: string
  detail?: string | null
  linked?: boolean
  mark: ReactNode
  value: ReactNode
  testId?: string
}) => (
  <div className="stream-item" {...(testId ? { 'data-testid': testId } : {})} data-name={name}>
    <span className="stream-nm" data-linked={String(linked)}>
      {name}
      {detail ? <em> {detail}</em> : null}
    </span>
    {mark}
    <span className="stream-v">{value}</span>
  </div>
)

/** A proportion drawn against the list's shared maximum.
 *
 * The track and the fill are separately addressable, and the measurement is
 * why: the track is what has to share a left edge with every other track for
 * the list to be one axis, and the fill is what has to be in proportion to the
 * value. Asserting both on one element would confuse "the column is aligned"
 * with "the number is drawn", and only the second can go wrong quietly. */
export const Bar = ({ value, max }: { value: number; max: number }) => (
  <span className="stream-bar" data-testid="bar">
    {value > 0 && max > 0 ? (
      <i data-testid="bar-fill" style={{ width: `${percent(value, max)}%` }} />
    ) : null}
  </span>
)

/** Where in a document its matches fell, each tick at `start / char_count`.
 *
 * `total` is that document's own length rather than the longest document in
 * the result, which is the only denominator that makes a tick mean "9% of the
 * way into this source". Every sparkline is therefore its own scale, which is
 * correct here and is exactly what would be wrong on a `Bar`. */
export const Sparkline = ({
  positions,
  total,
}: {
  positions: readonly number[]
  total: number
}) => (
  <span className="stream-spark" data-testid="spark">
    {positions.map((position, index) => (
      <i key={index} style={{ left: `${percent(position, total)}%` }} />
    ))}
  </span>
)

/** The control behind the cap of five.
 *
 * A `<button>` with a *named class*, and that is not a style preference.
 * `tokens.css` gives every bare `button` an unlayered `background`, `color`
 * and `font: inherit`; because `font` is a shorthand it sets `font-size` too,
 * so `text-xs bg-transparent` here would be present in the class attribute,
 * present in the bundle, and never applied. It fails silently and looks
 * identical to a utility that worked. */
export const Expander = ({
  label,
  expanded,
  onToggle,
}: {
  label: string
  expanded: boolean
  onToggle: () => void
}) => (
  <button type="button" className="stream-exp" aria-expanded={expanded} onClick={onToggle}>
    <span aria-hidden="true">{expanded ? '▾' : '▸'}</span> {label}
  </button>
)

/** Text from a source, set in the stream's serif.
 *
 * Serif because it is prose the reader is meant to read, against machinery
 * they are meant to skim — the same split the whole design rests on, applied
 * inside one card. */
export const Quote = ({ children }: { children: ReactNode }) => (
  <div className="stream-q">{children}</div>
)
