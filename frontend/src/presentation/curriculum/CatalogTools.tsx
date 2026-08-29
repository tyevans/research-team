import clsx from 'clsx'
import type { ReactNode } from 'react'

import type { ArtSweepProgress, BlurbSweepProgress } from '@application/ports/repositories.ts'

import { Button } from '../common/primitives.tsx'

/** The two background sweeps that fill the catalog in, and their progress.
 *
 * **They used to be the first two things on the page**, two bordered boxes
 * above the first card, so the front page of a browsing surface opened with two
 * operator controls and their counts. That is the wrong order for the reader
 * this page has most of: somebody browsing what the project could teach, who
 * runs a sweep once a week. The sweeps are at the foot of the page now, under a
 * heading that says what they are, and the one case where they need to be at
 * the top -- a sweep is *running* right now -- is `SweepBanner` instead, which
 * is one line rather than two boxes.
 *
 * **One `SweepControl` rather than two components.** `BlurbSweepControl` and
 * `ArtSweepControl` were 45 lines each and differed in four strings and one
 * extra button. Both carried a copy of the `error`-before-counts rule, which is
 * the part that matters: `progress.error` present must never read as an
 * ordinary finish (see `BlurbSweepProgress.error`'s own docstring), and a rule
 * written twice is a rule that can be fixed once.
 */

/** What the two sweeps have in common on the wire. Both `BlurbSweepProgress`
 *  and `ArtSweepProgress` are structurally this; the alias is here so
 *  `SweepControl` does not name one of them and quietly accept the other. */
interface SweepProgress {
  readonly running: boolean
  readonly done: number
  readonly total: number
  readonly failed: number
  readonly error: string | null
}

export const CatalogTools = ({
  blurb,
  art,
  startingBlurb,
  startingArt,
  onWriteCopy,
  onIllustrate,
  onReIllustrate,
}: {
  blurb: BlurbSweepProgress | null
  art: ArtSweepProgress | null
  startingBlurb: boolean
  startingArt: boolean
  onWriteCopy: () => void
  onIllustrate: () => void
  onReIllustrate: () => void
}) => (
  <section className="crs-tools flex flex-col gap-2 rounded-md border border-solid border-line bg-bg-panel p-3">
    <h2 className="tracking-wide m-0 text-sm font-semibold text-fg uppercase">Catalog upkeep</h2>
    <SweepControl
      progress={blurb}
      starting={startingBlurb}
      description="Write catalog copy and outlines for every candidate whose blurb or outline is missing or out of date."
      idleLabel="Write the missing copy and outlines"
      runningVerb="Writing"
      doneVerb="written"
      onRun={onWriteCopy}
    />
    <SweepControl
      progress={art}
      starting={startingArt}
      description="Illustrate every candidate whose art is missing or out of date."
      idleLabel="Illustrate the catalog"
      runningVerb="Illustrating"
      doneVerb="illustrated"
      onRun={onIllustrate}
      extra={
        // A distinct control from the ordinary run on purpose (see
        // `CourseRepository.startArtSweep`'s docstring): pressing the ordinary
        // button must never suddenly cost a model call per card.
        <Button small tone="quiet" onClick={onReIllustrate} disabled={art?.running ?? startingArt}>
          Re-illustrate everything
        </Button>
      }
    />
  </section>
)

/** One sweep: a description, a button that starts it, and the line it reports.
 *
 * Deliberately the same shape as `DiscoverySweep` (`presentation/research/`):
 * a button that starts a background sweep, a progress line polling the same
 * path, and an error state distinguished from an ordinary slow run. The one
 * difference from that sweep is where the counts come from -- discovery counts
 * a client-side loop over one document at a time, this counts a server-side
 * background task, so `progress` is `null` only before the first poll has
 * answered rather than for a work list not yet loaded.
 */
const SweepControl = ({
  progress,
  starting,
  description,
  idleLabel,
  runningVerb,
  doneVerb,
  onRun,
  extra,
}: {
  progress: SweepProgress | null
  starting: boolean
  description: string
  idleLabel: string
  /** Present tense, for the button while the sweep runs: "Writing 3 of 12". */
  runningVerb: string
  /** Past participle, for the line after it finishes: "3 of 12 written". */
  doneVerb: string
  onRun: () => void
  extra?: ReactNode
}) => {
  const running = starting || (progress?.running ?? false)
  return (
    <div className="flex flex-wrap items-center gap-2">
      <p className="m-0 min-w-[240px] flex-1 text-xs text-fg-dim">{description}</p>
      <Button small onClick={onRun} disabled={running}>
        {running && progress !== null
          ? `${runningVerb} ${progress.done} of ${progress.total}`
          : running
            ? `${runningVerb}…`
            : idleLabel}
      </Button>
      {extra}
      {progress !== null && !running && (
        // `error` present is the one case that must not read as an ordinary
        // finish -- see `BlurbSweepProgress.error`'s own docstring: it is set
        // only when the run itself raised, which `failed` alone does not
        // report. Checked first, so a died sweep can never also print the
        // done/total/failed line as if it had settled normally.
        <p
          className={clsx(
            'm-0 w-full text-xs',
            progress.error !== null ? 'text-k-failure' : 'text-fg-dim',
          )}
        >
          {progress.error !== null
            ? `The sweep failed: ${progress.error}`
            : `${progress.done} of ${progress.total} ${doneVerb}${
                progress.failed > 0 ? `, ${progress.failed} failed` : ''
              }.`}
        </p>
      )}
    </div>
  )
}

/** A running sweep, said once at the top of the page.
 *
 * The whole reason the controls could move to the foot: a reader who started a
 * sweep needs to see it running without scrolling to the thing they pressed,
 * and a reader who did not start one needs no sweep chrome at all. Renders
 * nothing when nothing is running, which is almost always.
 *
 * `role="status"` rather than `role="alert"`: this is progress, and an
 * assertive live region interrupting a screen reader every two seconds as the
 * poll ticks would make the page unusable while a sweep ran.
 */
export const SweepBanner = ({
  blurb,
  art,
}: {
  blurb: BlurbSweepProgress | null
  art: ArtSweepProgress | null
}) => {
  const lines: string[] = []
  if (blurb?.running === true) lines.push(`Writing copy: ${blurb.done} of ${blurb.total}.`)
  if (art?.running === true) lines.push(`Illustrating: ${art.done} of ${art.total}.`)
  if (lines.length === 0) return null

  return (
    <p
      role="status"
      className="crs-sweep-banner m-0 rounded-md border-0 border-l-2 border-solid border-accent bg-bg-raise px-3 py-2 text-sm text-fg-dim"
    >
      {lines.join(' ')} The catalog refreshes itself when it finishes.
    </p>
  )
}
