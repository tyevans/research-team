import clsx from 'clsx'

import { extractedFraction, isBehind, type Scale } from '@domain/project/board.ts'
import type { ProjectSummary } from '@domain/project/project.ts'

/** The four things a project holds, drawn as three tracks.
 *
 * **This is the page's one idea and everything else is quiet around it.**
 * The previous index gave every project the same two numbers — a session count
 * and a file count, neither of which is a fact about a project — so six rows
 * drew identically and the list conveyed nothing that the six names did not.
 * These tracks are scaled to the *board's* maximum rather than to each
 * project's own total, which is what turns three bars per row into three
 * columns down the page: the comparison a list exists to support is available
 * without reading a digit.
 *
 * **Three tracks for four stages, and the fold is the point.** Sources and
 * extraction count the same rows — extraction is a subset of ingest — so they
 * share one track, where the filled part is what has reached the graph and the
 * tail is what has not. That tail is the only thing on this page a reader can
 * act on immediately, and no arrangement of two separate bars says it as
 * directly: One Piece drew 3 of 6 on the real database, which is a visible
 * amber tail and was previously not on the page at all.
 *
 * Topics and courses get their own tracks because they count unrelated things
 * and a shared scale between them would be a comparison that means nothing.
 *
 * **Utilities rather than a stylesheet**, per the policy `check-deleted.mjs`
 * records: new surfaces are dressed in Tailwind and the remaining stylesheets
 * die with the screens they dress. This shipped as a `board.css` for one draft
 * and the check caught it, which is what that frozen list is for.
 *
 * **Props-only, no fetching.** Everything it needs is passed, including the
 * scale — which it cannot compute, because the scale is a fact about the whole
 * board and this component sees one row. That is the constraint that keeps the
 * scale honest: it is derived once, in the view, from the same array the rows
 * are drawn from.
 */
export const ProjectPipeline = ({ summary, scale }: { summary: ProjectSummary; scale: Scale }) => {
  const behind = isBehind(summary)
  return (
    // Three equal columns, which is what makes the bars comparable *down* the
    // page — the entire argument for scaling them to the board's maximum.
    // `auto`-sized columns would give each project's bars a different track
    // length and quietly undo it.
    <div className="grid grid-cols-3 gap-5" data-pipe>
      <Track
        label="topics"
        value={summary.topics}
        /* The open ones as a second figure, not a second track. They are a
           subset of `topics`, so a track of their own would double-count the
           same questions; and unlike every other number here this one goes
           *down* as work happens, so it is set apart in words rather than
           given a bar that would read as progress. */
        note={summary.topicsOpen > 0 ? `${summary.topicsOpen} queued` : null}
        fill={summary.topics / scale.topics}
      />
      <Track
        label="sources"
        value={summary.sources}
        note={behind ? `${summary.sources - summary.extracted} not extracted` : null}
        fill={summary.sources / scale.sources}
        /* The inner fill is a fraction of the *outer bar*, not of the track,
           which is why it is a nested element rather than a second one at its
           own percentage of the track. Written as a percentage of the parent,
           the arithmetic cannot drift: whatever width the outer bar resolves
           to, the extracted part is that width times this fraction, and the
           tail is the remainder by construction. A second bar at
           `extracted / scale.sources` would be the same number today and would
           come apart the moment either scale changed. */
        inner={extractedFraction(summary)}
        tone={behind ? 'behind' : undefined}
      />
      <Track
        label="courses"
        value={summary.courses}
        note={null}
        fill={summary.courses / scale.courses}
      />
    </div>
  )
}

/** One stage: its name, its count, and a bar as wide as its share of the board.
 *
 * **Label, value and bar on one line rather than stacked.** Stacked, a row was
 * 148px and five projects filled a 900px viewport — no denser than the card
 * grid this replaced, which was half the complaint. Inline, the row is 103px
 * and all six projects sit above the fold, with the bars still forming columns
 * because every track uses the same three-column template.
 *
 * The note takes a second line spanning the value and bar columns, and is
 * rendered whether or not there is one to show, so every row is the same
 * height. A note that came and went would give the virtualized list two row
 * heights and turn an exact estimate into a measurement.
 */
const Track = ({
  label,
  value,
  note,
  fill,
  inner,
  tone,
}: {
  label: string
  value: number
  note: string | null
  fill: number
  inner?: number | undefined
  /** `| undefined` explicitly: `exactOptionalPropertyTypes` is on, and the
   *  caller passes the result of a conditional rather than omitting the
   *  prop. */
  tone?: 'behind' | undefined
}) => (
  // `max-content max-content 1fr`: the value column sizes to its digits, which
  // keeps the three bars starting at the same x while every count is one or
  // two digits in the same tabular face. A four-digit count in one project
  // would push that track's bar a few pixels left of its neighbours' — the
  // known limit of this arrangement, and not worth a subgrid until a project
  // has a thousand of something.
  <div
    className="grid min-w-0 grid-cols-[max-content_max-content_1fr] items-center gap-x-2 gap-y-px"
    data-pipe-track={label}
  >
    <div className="font-mono text-xs tracking-[0.08em] text-fg-faint uppercase">{label}</div>
    {/* Tabular figures so the digits sit in the same columns from row to row.
        On a list whose whole job is comparison this is not typographic
        fussiness: proportional figures start `11` and `2` at different
        x-positions, and the ragged left edge reads as noise before the numbers
        read as numbers.

        `text-md` rather than the `text-xl` this started at. Three tracks times
        six rows is eighteen numerals, and at `text-xl` they were collectively
        louder than the six project names — so the page led with its readout
        and buried the thing a reader is scanning for. */}
    <div
      className={clsx(
        'min-w-[2ch] text-right font-mono text-md tabular-nums',
        value === 0 ? 'text-fg-faint' : 'text-fg',
      )}
      data-pipe-value
    >
      {value}
    </div>
    {/* `role="img"` with a label rather than a `progressbar`: this is not a
        task advancing toward completion, it is a quantity next to its peers,
        and `progressbar` would have a screen reader announce a percentage of a
        maximum that is another project's total. The label below is the whole
        of what the bar says, and the count is already in the row as text, so a
        reader who cannot see it loses nothing. */}
    <div
      // `h-2` is `--spacing-2`, 6px. Not `h-1.5`: this project omits Tailwind's
      // default theme, so only the `--spacing-1..6` steps it declares exist and
      // a fractional step generates nothing at all — which `check-tailwind.mjs`
      // caught here, and which would otherwise have left the bar at its
      // content height of zero.
      className="h-2 overflow-hidden rounded-[3px] bg-line-soft"
      role="img"
      aria-label={note ? `${value} ${label}, ${note}` : `${value} ${label}`}
      data-pipe-bar
    >
      {/* Inline widths because they are data. A percentage computed from a
          count cannot be a utility class, and the alternative — a custom
          property set inline and read by a rule — is the same inline style
          with an indirection in front of it.

          **The two tones were the wrong way round in the first draft**, and a
          screenshot is what caught it: with the extracted part painted in the
          accent and the outer bar in the plain tone, a fully-extracted project
          drew a 100% inner and came out entirely accent-coloured — so the four
          projects with nothing outstanding were the loudest rows on the page
          and the marker meant its own opposite. jsdom could not have seen it;
          every class was exactly as intended.

          The arrangement now: the outer bar is amber only when behind, and the
          inner paints the extracted part back over it in the same tone every
          other completed bar uses. What stays amber is exactly the shortfall,
          by construction. A project that is not behind gets no amber at all,
          so both layers are `bg-fg-dim` and the bar is uniform.

          `bg-k-tool` is the amber the timeline already spends on tool activity
          — work outstanding is work in flight. It was `bg-tint-held` for one
          draft, which is a near-white background wash (`#faf1de`), so the
          shortfall was indistinguishable from the empty track behind it. */}
      <div
        className={clsx('h-full rounded-[3px]', tone === 'behind' ? 'bg-k-tool' : 'bg-fg-dim')}
        style={{ width: pct(fill) }}
        data-pipe-fill={tone ?? 'plain'}
      >
        {inner === undefined ? null : (
          <div
            className="h-full rounded-[3px] bg-fg-dim"
            style={{ width: pct(inner) }}
            data-pipe-done
          />
        )}
      </div>
    </div>
    <div
      className={clsx(
        'col-start-2 col-end-[-1] min-h-[1.1em] font-mono text-xs',
        tone === 'behind' ? 'text-fg-dim' : 'text-fg-faint',
      )}
      aria-hidden={note === null}
      data-pipe-note
    >
      {note ?? ' '}
    </div>
  </div>
)

/** A 0–1 fraction as a CSS width, clamped and rounded to a tenth of a percent.
 *
 * Clamped because a fraction outside 0–1 draws a bar outside its track: the
 * mapper already clamps `extracted` to `sources`, and this is the second half
 * of the same guard, at the only place where a number becomes a length.
 *
 * Rounded because an unrounded fraction produces widths like
 * `9.090909090909092%`, which is seventeen characters of noise in the DOM for
 * a difference no display can resolve — and which makes a browser test's
 * assertion on a width a string comparison nobody can read.
 */
const pct = (fraction: number): string =>
  `${(Math.round(Math.min(1, Math.max(0, fraction)) * 1000) / 10).toString()}%`
