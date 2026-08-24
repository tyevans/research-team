import type { AreaMember } from './curriculum.ts'
import type { CourseCandidate } from './catalog.ts'

/** One heading and its summary, in reading order -- `outline_view`'s
 *  `sections`, already unzipped from `(heading, summary)` server-side. */
export interface OutlineSection {
  readonly heading: string
  readonly summary: string
}

/** A generated (or cached) course outline, and the membership it was
 *  written against.
 *
 * `membershipHash` is the hash the *outline* was written against, not the
 * candidate's current one -- `outlineAge` below compares the two, mirroring
 * `Blurb`/`blurbAge` in `catalog.ts` exactly: neither hash alone says
 * anything, the comparison is the whole reason both are carried.
 */
export interface Outline {
  readonly promise: string
  readonly sections: readonly OutlineSection[]
  readonly membershipHash: string
  readonly model: string
  readonly generatedAt: string
}

/** One entity a fit comparison resolved a name for -- `kept` and `added`
 *  only. `dropped` (below) cannot carry a name: those ids are no longer in
 *  the cluster to look a name up against, matching `course_fit_view`'s own
 *  reasoning server-side. */
export interface FitEntity {
  readonly entityId: string
  readonly name: string
}

/** How a realized course's frozen membership compares to its cluster now.
 *
 * `dropped` is bare ids for the reason `FitEntity` above states. `orphaned`
 * is true when the cluster this course was drawn from no longer exists at
 * all -- distinct from an ordinary drift, and `fitSummary` below reads it
 * first, before either count, because there is nothing to diff against once
 * it is true.
 */
export interface CourseFit {
  readonly kept: readonly FitEntity[]
  readonly added: readonly FitEntity[]
  readonly dropped: readonly string[]
  readonly orphaned: boolean
}

/** The decision that a cluster is a course, and what has happened to that
 *  cluster since. `authoredSessionId` is `null` until an authoring run for
 *  this course has actually written a session -- a course can be realized
 *  with no session yet, and a caller needing to tell those apart reads this
 *  field directly rather than inferring it from `fit`. */
export interface RealizedCourse {
  readonly realizedAt: string
  readonly membershipHash: string
  readonly fit: CourseFit
  readonly authoredSessionId: string | null
}

/** One course's detail page: its candidate card, its outline, its full
 *  current membership, and -- if realized -- how it has drifted since.
 *  Mirrors `course_detail_view` in `presenters.py`. */
export interface CourseDetail {
  readonly candidate: CourseCandidate
  readonly outline: Outline | null
  readonly members: readonly AreaMember[]
  readonly course: RealizedCourse | null
}

/** One authored file of a course, as the turn wrote it. `path` is the
 *  workspace path (`/course/areas/<slug>/lesson-01.md`), kept rather than
 *  reduced to a label because it is the only stable identity a lesson has --
 *  two lessons can open with the same heading, and a React key built from the
 *  heading would collapse them. */
export interface AuthoredFile {
  readonly path: string
  readonly markdown: string
}

/** Which of three states a course's *authored text* is in.
 *
 * Three words rather than a nullable field, and that is the whole reason this
 * type exists. `Outline` above is deliberately allowed to conflate "refused"
 * with "never generated" (see `outlineAge`), because both render as "no
 * outline yet" and nothing downstream cares. A course cannot afford the same
 * conflation: "nobody has written this" is a button to press and "it is being
 * written right now" is a reason to wait, and a reader who cannot tell them
 * apart presses the button on a run already in flight.
 *
 * `authored` is decided server-side by files existing, not by a run having
 * settled -- see `read_course_unit` in `app.py` for why a course that exists
 * is served even while a later run rewrites it.
 */
export type CourseTextState = 'authored' | 'authoring' | 'unauthored'

/** The markdown the three UbD authoring turns wrote for one course.
 *
 * `unit` is Stage 1 and Stage 2; `lessons` are the rest, in path order. Both
 * are empty for every state but `authored`, and a reader should branch on
 * `state` rather than on `unit === null`: a run that wrote lessons and lost
 * its framing turn is `authored` with a null unit, which is a real state and
 * not an absence.
 */
export interface CourseText {
  readonly slug: string
  readonly state: CourseTextState
  readonly sessionId: string | null
  readonly unit: string | null
  readonly lessons: readonly AuthoredFile[]
}

/** Whether a detail's outline is current or behind the candidate it
 *  describes -- `blurbAge` in `catalog.ts`, applied to `outline` rather than
 *  `blurb`. `null` covers "no outline yet" and "current" both, for the same
 *  reason `blurbAge` does: nothing downstream needs the two told apart, only
 *  "stale" needs its own word. */
export function outlineAge(detail: CourseDetail): 'stale' | null {
  if (detail.outline === null) return null
  return detail.outline.membershipHash === detail.candidate.membershipHash ? null : 'stale'
}

/** A short phrase for the drift banner on a realized course's page.
 *
 * `orphaned` is checked first and returns on its own -- once the cluster
 * this course was drawn from is gone, `added`/`dropped` counts describe
 * nothing a reader can go look at, so there is no diff to report alongside
 * it, only the fact itself.
 */
export function fitSummary(fit: CourseFit): string {
  if (fit.orphaned) return 'The cluster this course was drawn from is gone.'
  const added = fit.added.length
  const dropped = fit.dropped.length
  if (added === 0 && dropped === 0) {
    return 'The cluster has not changed since this course was made.'
  }
  const parts: string[] = []
  if (added > 0) parts.push(`${added} added`)
  if (dropped > 0) parts.push(`${dropped} dropped`)
  return `The cluster has drifted since: ${parts.join(', ')}.`
}
