import type { ReactNode } from 'react'

import { SHAPE_GLYPH, type Shape } from '@domain/conversation/artifact.ts'

import { Tooltip } from '../../common/Tooltip.tsx'

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
 * chrome is most of what makes the current feed feel heavy. Where an enclosing
 * box already draws a boundary the spine's rule is suppressed rather than the
 * row restructured — the `[.provisional_&]` variant on the gutter below, and
 * `.msg.bare` in `conversation.css` for a shaped result inside a run.
 *
 * The row takes a **shape**, not a character. `SHAPE_GLYPH` is the registry
 * and a call carries the same mark its result does; seven components each
 * writing `'⌕'` into a prop is seven places for that pairing to come apart,
 * silently and one shape at a time, since nothing renders a call and its
 * result side by side for a test to compare. */
export const Row = ({
  shape,
  glyph,
  phase,
  tone,
  children,
}: {
  shape: Shape
  /** A mark the registry cannot hold, because it is a state of the *result*
   *  rather than of the shape.
   *
   * One caller: an `acknowledgement` whose write failed. `SHAPE_GLYPH` is
   * `Record<Shape, string>` and its test asserts one distinct glyph per shape,
   * so a second acknowledgement mark cannot live there without making the
   * registry mean something else. */
  glyph?: string
  phase: Phase
  tone?: 'ok' | 'fail'
  children: ReactNode
}) => (
  <div className="grid grid-cols-[15px_1fr] gap-3" data-phase={phase}>
    {/* The spine sits *under* the glyph rather than at the row's left edge, so
        the gutter is half its own width and offset by the other half. Its run
        into the next row comes from the body's padding rather than a negative
        offset, so the last row needs no `:last-child` case.

        `border-l` with no `border-solid`: Tailwind v4 emits the style longhand
        beside the width for one side and leaves the other three at
        `border-style: none`. Adding `border-solid` would give three sides a
        style with no width and let them fall back to the browser's `medium`,
        which is the box-instead-of-an-edge trap CLAUDE.md records.

        `[.provisional_&]` suppresses the rule and only the rule. `.provisional`
        already draws a 2px accent rail 16px to the left, and two vertical rules
        closing on the same content is the doubled boundary this design objects
        to — of the two the rail is the one carrying meaning, since it says *not
        recorded yet*, which a spine cannot say. Transparent rather than a width
        of zero: the width is what positions the glyph's halo over the line, and
        a gutter that narrowed by a pixel inside a provisional bubble would move
        the whole card when its turn committed. */}
    <div
      className="relative ml-[7px] w-[8px] border-l border-l-line [.provisional_&]:border-l-transparent"
      data-testid="stream-gutter"
    >
      {/* Punched through the spine with the page's own background, which is
          what makes the line read as passing behind the glyph rather than
          stopping at it. `bg-bg-panel` rather than `bg-bg`: the stream is drawn
          on a panel, and a glyph haloed in the wrong background is a smudge.

          The live edge is this animation and this colour, and nothing else. If
          a phase ever adds a pixel, every card in a turn jumps at the instant
          it commits, which is the exact defect "phase is position" was adopted
          to remove — `a-card-does-not-change-when-its-turn-commits.browser.test.tsx`
          holds it. Motion here is decorative, since the row's position already
          says "still arriving", so a reader who asked for less of it loses
          nothing. */}
      <span
        className="absolute top-0 -left-[8px] block w-[15px] bg-bg-panel text-center text-[10px] leading-[15px] text-accent data-[phase=live]:animate-stream-pulse data-[tone=fail]:text-tint-fail data-[tone=ok]:text-tint-ok motion-reduce:data-[phase=live]:animate-none"
        data-testid="stream-glyph"
        data-phase={phase}
        {...(tone ? { 'data-tone': tone } : {})}
        aria-hidden="true"
      >
        {glyph ?? SHAPE_GLYPH[shape]}
      </span>
    </div>
    <div className="min-w-0 pb-[7px]" data-testid="stream-body">
      {children}
    </div>
  </div>
)

/** The argument's own box: one line, ellipsised, taking the room the name and
 *  the count leave.
 *
 * A constant because it is worn by two different elements — a bare `<span>`
 * when there is nothing to explain, and the `Tooltip`'s trigger when there is.
 * The trigger *is* the box rather than sitting inside one, which is what keeps
 * the element count the same either way and stops the header's flex row
 * collapsing around an inline-sized button. */
const ARG_CLASS = 'min-w-0 flex-1 overflow-hidden text-ellipsis whitespace-nowrap text-fg'

/** `tool_name · argument · count`, and the call and its result are one row.
 *
 * `arg` is the source's *title*, resolved from the artifact —
 * `manuscriptreport.com · types of fictional genres`, not
 * `manuscriptreport-com-blog-types-of-fictional-genres-42e281d8`.
 *
 * The raw id goes to `explanation`, and it used to go to a `title` attribute.
 * That is the pattern the S-D3 deletion removed repo-wide and
 * `check-deleted.mjs` fails the build over: a `title` is announced on hover
 * after a delay the operating system owns, and on nothing else — not on focus,
 * not on touch, not to a screen reader reading a `<span>`. A bug report needing
 * the raw id is precisely a reader who may not be holding a mouse.
 *
 * The cost, since `Tooltip` states it and it applies here: with no
 * `OverlayHost` in scope the explanation does not render at all. Every shape's
 * unit test mounts bare, so those tests see the trigger and no content; the
 * console mounts inside `Shell`, which has the host. */
export const Header = ({
  name,
  arg,
  count,
  explanation,
}: {
  name: string
  arg?: ReactNode
  count?: ReactNode
  explanation?: string
}) => (
  <div className="flex items-baseline gap-[8px]" data-testid="stream-header">
    <b className="font-normal whitespace-nowrap text-fg-faint">{name}</b>
    {arg === undefined ? null : explanation ? (
      <Tooltip explanation={explanation} className={ARG_CLASS}>
        {arg}
      </Tooltip>
    ) : (
      <span className={ARG_CLASS} data-testid="stream-arg">
        {arg}
      </span>
    )}
    {count === undefined ? null : (
      <span className="flex items-center gap-[4px] text-xs whitespace-nowrap text-fg-faint">
        {count}
      </span>
    )}
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
  <div
    className="grid grid-cols-[1fr_54px_20px] items-center gap-[12px] py-[0.5px]"
    {...(testId ? { 'data-testid': testId } : {})}
    data-name={name}
  >
    {/* An entity the graph knows by name and has connected to nothing is the
        most actionable thing a `graph_search` returns, and in the paragraph
        this replaces it was the least visible: dimmed and below a rule is what
        `data-linked="false"` buys. */}
    <span
      className="overflow-hidden text-ellipsis whitespace-nowrap text-fg-dim data-[linked=false]:text-fg-faint [&_em]:text-xs [&_em]:text-fg-faint [&_em]:not-italic"
      data-testid="stream-name"
      data-linked={String(linked)}
    >
      {name}
      {detail ? <em> {detail}</em> : null}
    </span>
    {mark}
    <span className="text-right text-xs text-fg-faint" data-testid="stream-value">
      {value}
    </span>
  </div>
)

/** A proportion drawn against the list's shared maximum.
 *
 * The track and the fill are separately addressable, and the measurement is
 * why: the track is what has to share a left edge with every other track for
 * the list to be one axis, and the fill is what has to be in proportion to the
 * value. Asserting both on one element would confuse "the column is aligned"
 * with "the number is drawn", and only the second can go wrong quietly.
 *
 * The fill is styled through `[&>i]` on the track rather than by classing the
 * `<i>`, because `EntityList` renders the same track *empty* for an unlinked
 * entity — one class constant, two call sites, and no way for the empty one to
 * drift. */
export const BAR_CLASS =
  'block h-[5px] overflow-hidden rounded-md bg-bg-raise [&>i]:block [&>i]:h-full [&>i]:bg-accent [&>i]:opacity-80'

export const Bar = ({ value, max }: { value: number; max: number }) => (
  <span className={BAR_CLASS} data-testid="bar">
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
  <span
    className="relative block h-[8px] [&>i]:absolute [&>i]:top-0 [&>i]:-ml-px [&>i]:block [&>i]:h-[8px] [&>i]:w-[2px] [&>i]:bg-accent [&>i]:opacity-80"
    data-testid="spark"
  >
    {positions.map((position, index) => (
      <i key={index} style={{ left: `${percent(position, total)}%` }} />
    ))}
  </span>
)

/** The control behind the cap of five.
 *
 * Utilities, and every one of the four resets is load-bearing rather than
 * decoration. `tokens.css` gives a bare `button` a `background`, a `color` and
 * `font: inherit`, and this build imports no Tailwind preflight, so the user
 * agent's border and padding survive too. Those rules are in `@layer base`
 * since #313, so the utilities here beat them — but only because they are
 * layered, and `spine.browser.test.tsx` measures the size and the background
 * rather than trusting it. Unlayer that rule again and every class below is in
 * the attribute, in the bundle, and never applied, which looks exactly like a
 * utility that worked.
 *
 * `text-[10px]` is an arbitrary value rather than `text-xs` (10.5px) because
 * the measurement asserts an exact number and half a pixel of type is not a
 * scale step anyone chose. */
export const Expander = ({
  label,
  expanded,
  onToggle,
}: {
  label: string
  expanded: boolean
  onToggle: () => void
}) => (
  <button
    type="button"
    className="mt-[4px] inline-block cursor-pointer border-0 bg-transparent p-0 font-mono text-[10px] leading-[1.4] text-accent-dim hover:text-accent"
    aria-expanded={expanded}
    onClick={onToggle}
  >
    <span aria-hidden="true">{expanded ? '▾' : '▸'}</span> {label}
  </button>
)

/** Text from a source, set in the stream's serif.
 *
 * Serif because it is prose the reader is meant to read, against machinery
 * they are meant to skim — the same split the whole design rests on, applied
 * inside one card. */
export const Quote = ({ children }: { children: ReactNode }) => (
  <div
    className="mt-[5px] border-l border-l-line-soft pl-[9px] font-serif text-md leading-[1.5] [overflow-wrap:anywhere] whitespace-pre-wrap text-fg-dim"
    data-testid="stream-quote"
  >
    {children}
  </div>
)
