import clsx from 'clsx'

import {
  formatSpan,
  type ArtifactSlot,
  type Course,
  type Provenance,
  type SourceSpan,
} from '@domain/project/course.ts'
import { FilePath } from '@domain/shared/file-path.ts'

import { Chip } from '../common/primitives.tsx'
import { Tooltip } from '../common/Tooltip.tsx'
import { sessionHref } from '../routing/routes.ts'

/** The four artifact chip tones, as utility dressing carried by the component
 *  that renders them.
 *
 * They were `.chip-present`, `.chip-missing`, `.chip-inferred` and `.chip-bad`
 * in `course.css`, and they leave for the reason `GateReview`'s `SEVERITY_DRESS`
 * left: the tones have to come out with the block that dressed them, the
 * standing policy forbids relocating a rule into another stylesheet, and a
 * `tone` whose class resolves to nothing raises no error and fails no test — it
 * collapses four tones into one grey and looks like a design decision.
 *
 * `dress` **replaces** `Chip`'s default trio rather than adding to it. Two
 * colour utilities on one element are both in `@layer utilities`, where the
 * winner is Tailwind's own sort order and not the class attribute's; passing
 * one string or the other has one answer. `Chip` documents this at the prop.
 *
 * The values are `course.css`'s own, named where a token holds them:
 * `#131f17`/`#24402c` are `--color-tint-ok`/`--color-tint-ok-line`,
 * `#241417`/`#45272a` are the fail pair. `inferred`'s two have no token and stay
 * arbitrary rather than being rounded to a neighbour — claimed inference is not
 * a defect and must not wear the colour "claims nothing" wears.
 * `missing` set only a colour, so it keeps the base hairline and no fill.
 */
const PRESENT_DRESS = 'text-k-file border-tint-ok-line bg-tint-ok'
const MISSING_DRESS = 'text-fg-faint border-line'
const INFERRED_DRESS = 'text-k-message border-[#24365a] bg-[#111a2a]'
const BAD_DRESS = 'text-k-failure border-tint-fail-line bg-tint-fail'

/** One declared artifact, in one of four states a naive row would flatten into
 *  two: missing; present but with no readable frontmatter; present and claiming
 *  sources; present and claiming its thinking was the model's own. The last two
 *  are both legitimate and must not look alike. */
export const Artifact = ({
  slot,
  course,
  open = false,
}: {
  slot: ArtifactSlot
  course: Course
  /** Whether the route's `artifact` id names this row. `aria-current` as well
   *  as a fill, because "the one you followed a link to" is a fact a screen
   *  reader needs and a background colour is not one. Optional: `StageRail`
   *  renders these rows too and has no selection to pass. */
  open?: boolean
}) => {
  const name = FilePath.of(slot.path).basename
  return (
    // `clsx` rather than a template literal, still, and not as a matter of
    // taste: `prettier-plugin-tailwindcss@0.8.1` rewrites
    // `` `a${open ? ' b' : ''}` `` by deleting the leading space inside the
    // conditional, which yields the single class `ab` and silently unstyles the
    // row. `clsx` is handled correctly and is listed in `tailwindFunctions` in
    // `.prettierrc.json`.
    //
    // **`data-missing` rather than the old `artifact-missing` class.**
    // `course.css` had carried that name with no rule behind it since the
    // opacity was removed -- its comment called it "the hook anything later
    // would hang off". A class with no rule in a file of classes with rules is
    // indistinguishable from one whose rule was lost, which is the whole defect
    // `check-deleted.mjs` exists about; a `data-` attribute says "state, not
    // dressing" and cannot be mistaken for either.
    //
    // `border-0` before `border-b`, which is the rule this repository has paid
    // for twice: `border-solid` sets a style on all four sides, and the three
    // with no explicit width fall back to the browser's `medium` (~3px). One
    // rule meant for one edge draws a box without it.
    <li
      className={clsx(
        'flex flex-col gap-[4px] border-0 border-b border-solid border-line-soft px-3 py-[8px] last:border-b-0',
        open && 'bg-bg-raise',
      )}
      data-missing={!slot.present}
      aria-current={open ? 'true' : undefined}
    >
      <div className="flex flex-wrap items-center gap-[8px]">
        <span className="font-mono text-sm">
          {slot.present ? (
            <CourseFileLink course={course} path={slot.path} text={name} />
          ) : (
            <span className="text-fg-dim">{name}</span>
          )}
        </span>
        <span className="text-sm text-fg-dim">
          {slot.artifactType}
          {slot.subtype ? ` (${slot.subtype})` : ''}
        </span>
        <span className="font-mono text-xs text-fg-dim">{slot.cardinality}</span>
        {slot.present ? (
          <Chip dress={PRESENT_DRESS}>written</Chip>
        ) : (
          <Tooltip explanation={`The preset declares this artifact and no file is at ${slot.path}`}>
            <Chip dress={MISSING_DRESS}>not written</Chip>
          </Tooltip>
        )}
      </div>

      {slot.present && !slot.hasFrontmatter ? (
        <div className="text-sm text-k-failure">
          No readable frontmatter, so nothing can tell what this is or what it rests on.
        </div>
      ) : slot.present ? (
        <>
          {slot.missingFields.length > 0 ? (
            <div className="text-sm text-fg-dim">
              Frontmatter is missing {slot.missingFields.join(', ')}.
            </div>
          ) : null}
          <ProvenanceRow provenance={slot.provenance} course={course} />
        </>
      ) : null}
    </li>
  )
}

/** What an artifact says it rests on, shown as claims rather than as a score.
 *
 * Spans link into the source reader at the offsets the file claims —
 * unresolved, because whether a span still says what it said is a check's
 * question, and answering it here would cost a document read per row. */
const ProvenanceRow = ({
  provenance,
  course,
}: {
  provenance: Provenance | null
  course: Course
}) => {
  if (!provenance) return <div className="text-sm text-fg-dim">No provenance block at all.</div>

  return (
    <div className="flex flex-wrap items-center gap-2 text-sm">
      <span className="text-fg-dim">rests on: </span>
      {/* The two trigger modes side by side, which is why this row was the one
          the bridge landed on first — `asChild` over an anchor that is already
          focusable and already passes a ref, and the default wrapper over a
          `Chip`, which renders a `<span>` and is reachable by no keyboard at
          all without one. */}
      {provenance.sources.map((span, index) => (
        <Tooltip
          key={index}
          asChild
          explanation="Open this source at the offsets this artifact cites"
        >
          <a className="font-mono text-xs text-k-message" href={sourceHref(course, span)}>
            {formatSpan(span)}
          </a>
        </Tooltip>
      ))}
      {provenance.inferred ? (
        <Tooltip explanation="Some of this was reasoned rather than drawn from a source, and says so.">
          <Chip dress={INFERRED_DRESS}>inferred</Chip>
        </Tooltip>
      ) : null}
      {provenance.unreadable > 0 ? (
        <Tooltip explanation="Entries that are neither a source span nor the inference flag.">
          <Chip dress={BAD_DRESS}>{provenance.unreadable} unreadable</Chip>
        </Tooltip>
      ) : null}
      {provenance.empty ? (
        <Tooltip
          explanation={
            'Neither a source nor an admission of inference — indistinguishable from an ' +
            'artifact never checked against anything.'
          }
        >
          <Chip dress={BAD_DRESS}>claims nothing</Chip>
        </Tooltip>
      ) : null}
    </div>
  )
}

const sourceHref = (course: Course, span: SourceSpan): string => {
  const base = `/api/projects/${encodeURIComponent(course.projectId)}/sources/${encodeURIComponent(
    span.sourceId,
  )}`
  if (span.start === null || span.end === null) return base
  return `${base}?start=${span.start}&end=${span.end}`
}

/** Course files are read through the session that holds them, because that is
 *  where the file viewer lives and it already renders markdown, diffs and
 *  per-file history. A second reader here would be a worse copy of it. */
export const CourseFileLink = ({
  course,
  path,
  text,
}: {
  course: Course
  path: string
  text?: string
}) => {
  const label = text ?? FilePath.of(path).basename
  if (!course.holdingSessionId) {
    return (
      <Tooltip explanation="No session is holding this project, so there is nothing to open the file in. Join the project to read it.">
        <span className="text-fg-dim">{label}</span>
      </Tooltip>
    )
  }
  // The explanation is the full path, because the link shows a basename. Not a
  // duplicate of the visible text and not deletable for that reason.
  return (
    <Tooltip asChild explanation={path}>
      <a href={sessionHref(course.holdingSessionId, undefined, FilePath.of(path))}>{label}</a>
    </Tooltip>
  )
}
