import clsx from 'clsx'

import type { CourseCandidate } from '@domain/knowledge/catalog.ts'
import { blurbAge } from '@domain/knowledge/catalog.ts'
import { titleCase } from '@domain/knowledge/title-case.ts'

import { FeatureToggle } from './FeatureToggle.tsx'

/** One course candidate, drawn as a card, in one of three densities.
 *
 * `size` is a computed style -- width, art aspect, font scale -- and is
 * asserted only in `course-card-sizing.browser.test.tsx`, which measures the
 * rendered geometry. jsdom lays nothing out, so a test here comparing class
 * names between sizes would prove nothing about what the cascade did with
 * them; this file gives each size its own class and stops there.
 *
 * **The variants are three `Record<Size, string>` tables rather than a chain of
 * `size === …` clauses**, which is what this file was. The chain had one
 * property varying per size and read fine; the card now varies width, art
 * aspect and title scale together, and three independent chains over the same
 * union is exactly how a fourth comes to be added for only two of the three
 * values. A `Record` keyed on the union puts the columns beside each other and
 * makes a missing cell a type error rather than a card with no width.
 *
 * **Not `class-variance-authority`, though it is installed and this is what it
 * is for.** Ruled out for this slice by the library-adoption decision
 * (`docs/design/frontend-library-adoption.md`): the palette is currently
 * written twice, in `tokens.css`'s `:root` and `theme.css`'s `@theme`, and
 * components are mid-migration from stylesheet rules to utilities. A `cva`
 * table on top of that makes one component's appearance readable in three
 * places at once. It lands after the `:root` collapse. These tables are what
 * `cva` will replace, and they are deliberately shaped like it -- one row per
 * size, so the swap is mechanical.
 *
 * **`rounded-md`, not `rounded-lg`, and this is a fix rather than a
 * preference.** `theme.css` deliberately omits Tailwind's default theme and
 * declares one radius, `--radius-md`. `rounded-lg` therefore generates no rule
 * at all -- the card had square corners for as long as it has existed, and
 * nothing failed, which is the silent-utility failure `check-tailwind.mjs`
 * exists for and does not yet cover the radius family.
 *
 * **The card is an `<article>` with an overlay button rather than one big
 * `<button>`**, and the reason is structural: a card now carries its own
 * feature toggle, and a `<button>` inside a `<button>` is invalid markup that
 * browsers resolve by dropping one of them. The overlay is a real button with
 * an accessible name, and the toggle is its *later sibling* so it paints on top
 * without a `z-index` -- positioned siblings paint in DOM order, and a
 * `z-index` in a utility would escape `scripts/stacking.test.ts` entirely
 * (`tokens.css` names that as the loophole).
 *
 * The cost of the overlay: the blurb text under it cannot be selected with a
 * mouse. Accepted -- a card is a link to somewhere the whole text lives, and
 * the alternative (title-only hit area) is the small-target UX this redesign
 * is replacing.
 */

type CardSize = 'hero' | 'highlight' | 'filed'

const CARD_SHAPE = clsx(
  'crs-card group relative flex flex-col items-stretch overflow-hidden rounded-md text-left',
  // `border-0` zeroes the three sides the directional width would otherwise
  // leave at the browser's ~3px default (no Tailwind preflight here); see
  // CLAUDE.md's border-solid entry. Never paired with a plain `border`.
  'border-0 border-t-2 border-solid border-line bg-bg-panel',
  // Lifts on hover and on keyboard focus alike. `focus-within` rather than
  // `focus`: the thing that takes focus is the overlay button inside, so a
  // `:focus` on the article would never fire.
  'transition-[transform,border-color] hover:border-line-strong',
  'focus-within:-translate-y-[2px] focus-within:border-accent hover:-translate-y-[2px]',
  // Switched *off* under reduced motion rather than slowed, matching
  // `course.css`'s own reduced-motion block and the reasoning there: the lift
  // carries no information -- the border colour already says "this one" -- so
  // there is nothing to preserve at a reduced amplitude.
  'motion-reduce:transition-none motion-reduce:focus-within:translate-y-0 motion-reduce:hover:translate-y-0',
)

const CARD_WIDTH: Record<CardSize, string> = {
  hero: 'crs-card-hero w-[420px]',
  highlight: 'crs-card-highlight w-[260px]',
  filed: 'crs-card-filed w-[184px]',
}

/** The art's aspect ratio moved to `course.css` on 2026-08-29, and this note is
 *  the reason rather than a redirection.
 *
 *  It was `aspect-[16/9]` / `aspect-[3/2]` here, and the browser test that
 *  measures it failed once in three local full-suite runs and again in CI, with
 *  the computed `aspect-ratio` reading `auto` -- the class in the attribute, no
 *  rule anywhere. The production build has both rules
 *  (`grep aspect-ratio` over a fresh `npm run build`), so the utilities are
 *  correct and the *bundle the browser suite is served* is what was
 *  incomplete: Tailwind's dev-time scan of `@source '../**\/*.tsx'` had not
 *  reached this file when the stylesheet was first requested, and a vitest
 *  browser page never picks up the invalidation.
 *
 *  So this is not a card bug and the fix is not to the card. An arbitrary-value
 *  utility whose only occurrence in the repository is one string in one file is
 *  the most fragile thing that scan can be asked for, and the ratio is the one
 *  property of this component a test asserts. A rule in `course.css` cannot be
 *  half-generated. The three size marker classes it keys off
 *  (`crs-card-hero` and friends) already existed for the test to select on. */

const CARD_TITLE: Record<CardSize, string> = {
  hero: 'text-xl',
  highlight: 'text-lg',
  filed: 'text-md',
}

export const CourseCard = ({
  candidate,
  size,
  onOpen,
  onFeature,
  onUnfeature,
}: {
  candidate: CourseCandidate
  size: CardSize
  onOpen: (slug: string) => void
  /** Curation, optional. Absent on a surface that is browsing rather than
   *  curating -- the toggle is simply not rendered, rather than rendered
   *  disabled, because a control that can never be pressed is a control a
   *  reader has to work out the rules of. */
  onFeature?: (candidate: CourseCandidate) => void
  onUnfeature?: (slug: string) => void
}) => {
  const featured = candidate.featuredRank !== null
  const stale = blurbAge(candidate) === 'stale'
  const curatable = onFeature !== undefined && onUnfeature !== undefined

  return (
    <article className={clsx(CARD_SHAPE, CARD_WIDTH[size], featured && 'border-accent')}>
      <div className="relative">
        <img
          src={candidate.art.url}
          alt={candidate.art.alt}
          className="crs-card-art w-full object-cover"
        />
        {/* The scrim. An arbitrary `linear-gradient` rather than Tailwind's
            `bg-gradient-to-t` + `from-*`: the stops here are alpha over
            whatever the art is, and there is no token for "the panel colour at
            0%". Its job is to keep the badges below legible over art nobody
            chose the brightness of. */}
        <div
          aria-hidden="true"
          className="absolute inset-0 bg-[linear-gradient(to_top,rgba(11,13,16,0.85)_0%,rgba(11,13,16,0.15)_45%,rgba(11,13,16,0)_75%)]"
        />
        <div className="absolute bottom-0 left-0 flex flex-wrap items-center gap-1 p-2">
          {featured && (
            // Text, not colour alone -- a border tint says nothing to a screen
            // reader, and `featuredRank` is the fact this line reports.
            <span className="crs-card-featured tracking-wide rounded-md bg-accent px-2 py-px text-xs font-semibold text-accent-fg uppercase">
              Featured
            </span>
          )}
          {stale && (
            <span className="crs-card-stale rounded-md border border-solid border-line bg-bg-raise px-2 py-px text-xs text-fg-dim">
              out of date
            </span>
          )}
        </div>
      </div>

      <div className="flex min-w-0 flex-col gap-1 px-3 py-2">
        <span className={clsx('crs-card-title font-semibold text-fg', CARD_TITLE[size])}>
          {titleCase(candidate.title)}
        </span>
        {candidate.blurb !== null && (
          <p className="crs-card-blurb m-0 line-clamp-3 text-sm text-fg-dim">
            {candidate.blurb.text}
          </p>
        )}
        <ProminenceMeter candidate={candidate} />
      </div>

      {/* Painted over the content above and under the toggle below, by DOM
          order. `rounded-md` so the focus ring traces the card rather than a
          square inside it. */}
      <button
        type="button"
        onClick={() => onOpen(candidate.slug)}
        aria-label={`Open ${titleCase(candidate.title)}`}
        className="crs-card-open focus-visible:lay-ring-inward absolute inset-0 cursor-pointer rounded-md border-0 bg-[transparent]"
      />

      {curatable && (
        <div
          // Revealed on hover and whenever anything in the card has focus, so
          // it is never a control only a mouse can find. `opacity` rather than
          // `hidden`: a display-toggled button cannot be tabbed to, which is
          // the same defect wearing a nicer transition.
          className={clsx(
            'crs-card-curate absolute top-2 right-2 transition-opacity',
            featured
              ? 'opacity-100'
              : // `group-focus-within`, not `focus-within`. The focus lands on
                // the overlay button, which is this div's *sibling* -- a bare
                // `focus-within` here asks whether the toggle itself has focus,
                // which it never does until somebody has already found it.
                // Measured, not reasoned: with `focus-within` the browser test
                // read opacity 0 after focusing the card, and every jsdom test
                // in this directory passed either way.
                'opacity-0 group-focus-within:opacity-100 group-hover:opacity-100',
          )}
        >
          <FeatureToggle candidate={candidate} onFeature={onFeature} onUnfeature={onUnfeature} />
        </div>
      )}
    </article>
  )
}

/** How central this cluster is to the project, as a bar and a number.
 *
 * `prominence` and `size` are both on the wire and neither had a surface --
 * the catalog fetched them on every request and rendered neither, so a reader
 * comparing two candidates had the server's own ranking available to it and
 * not to them. The bar is the comparison; the entity count is the thing that
 * makes the bar mean something rather than being a decoration.
 *
 * `aria-hidden` on the bar and the numbers as text: a non-visual reading gets
 * the same two facts in words, and a `<meter>` here would announce a range
 * nobody stated.
 */
const ProminenceMeter = ({ candidate }: { candidate: CourseCandidate }) => {
  const pct = Math.round(Math.min(1, Math.max(0, candidate.prominence)) * 100)
  return (
    <div className="crs-card-meter mt-1 flex items-center gap-2">
      <div
        aria-hidden="true"
        className="h-[3px] min-w-0 flex-1 overflow-hidden rounded-md bg-bg-raise"
      >
        <div className="h-full bg-accent-dim" style={{ width: `${pct}%` }} />
      </div>
      <span className="font-mono text-xs whitespace-nowrap text-fg-faint">
        {candidate.size} {candidate.size === 1 ? 'entity' : 'entities'}
      </span>
    </div>
  )
}
