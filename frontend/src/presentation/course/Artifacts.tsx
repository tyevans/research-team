import {
  formatSpan,
  type ArtifactSlot,
  type Course,
  type Provenance,
  type SourceSpan,
} from '@domain/project/course.ts'
import { FilePath } from '@domain/shared/file-path.ts'

import { Chip } from '../common/primitives.tsx'
import { sessionHref } from '../routing/routes.ts'

/** One declared artifact, in one of four states a naive row would flatten into
 *  two: missing; present but with no readable frontmatter; present and claiming
 *  sources; present and claiming its thinking was the model's own. The last two
 *  are both legitimate and must not look alike. */
export const Artifact = ({ slot, course }: { slot: ArtifactSlot; course: Course }) => {
  const name = FilePath.of(slot.path).basename
  return (
    <li className={`artifact${slot.present ? '' : ' artifact-missing'}`}>
      <div className="artifact-top">
        <span className="artifact-name">
          {slot.present ? (
            <CourseFileLink course={course} path={slot.path} text={name} />
          ) : (
            <span className="muted">{name}</span>
          )}
        </span>
        <span className="artifact-type">
          {slot.artifactType}
          {slot.subtype ? ` (${slot.subtype})` : ''}
        </span>
        <span className="muted artifact-card">{slot.cardinality}</span>
        {slot.present ? (
          <Chip tone="present">written</Chip>
        ) : (
          <Chip
            tone="missing"
            title={`The preset declares this artifact and no file is at ${slot.path}`}
          >
            not written
          </Chip>
        )}
      </div>

      {slot.present && !slot.hasFrontmatter ? (
        <div className="artifact-note bad">
          No readable frontmatter, so nothing can tell what this is or what it rests on.
        </div>
      ) : slot.present ? (
        <>
          {slot.missingFields.length > 0 ? (
            <div className="artifact-note">
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
  if (!provenance) return <div className="artifact-note">No provenance block at all.</div>

  return (
    <div className="artifact-prov">
      <span className="muted">rests on: </span>
      {provenance.sources.map((span, index) => (
        <a
          key={index}
          className="prov-src"
          href={sourceHref(course, span)}
          title="Open this source at the offsets this artifact cites"
        >
          {formatSpan(span)}
        </a>
      ))}
      {provenance.inferred ? (
        <Chip
          tone="inferred"
          title="Some of this was reasoned rather than drawn from a source, and says so."
        >
          inferred
        </Chip>
      ) : null}
      {provenance.unreadable > 0 ? (
        <Chip tone="bad" title="Entries that are neither a source span nor the inference flag.">
          {provenance.unreadable} unreadable
        </Chip>
      ) : null}
      {provenance.empty ? (
        <Chip
          tone="bad"
          title={
            'Neither a source nor an admission of inference — indistinguishable from an ' +
            'artifact never checked against anything.'
          }
        >
          claims nothing
        </Chip>
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
      <span
        className="muted"
        title="No session is holding this project, so there is nothing to open the file in. Join the project to read it."
      >
        {label}
      </span>
    )
  }
  return (
    <a href={sessionHref(course.holdingSessionId, undefined, FilePath.of(path))} title={path}>
      {label}
    </a>
  )
}
