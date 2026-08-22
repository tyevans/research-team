import {
  courseLinks,
  isRunning,
  progressOf,
  type AuthoringStatus,
} from '@domain/knowledge/authoring.ts'
import { SessionId } from '@domain/shared/identifier.ts'
import { FilePath } from '@domain/shared/file-path.ts'
import { AREAS_DIR, PATHS_DIR } from './course-paths.ts'

import { sessionHref } from '../routing/routes.ts'

/** Start writing courses, and see how the writing is going.
 *
 * **Two buttons, and the narrower one is the one that has to be spelled out.**
 * Writing the whole path is the ordinary ask; writing one area is what a reader
 * does when they have picked one. So "write every course" is always available
 * and "write this one" appears only when an area is selected — the reverse
 * would put the expensive action behind a selection nobody made.
 *
 * **The cost is stated before the click, not after.** Authoring an area is
 * three model turns; a path of eight is twenty-four. A button that said only
 * "Write courses" would commit a local model to twenty minutes on one click,
 * and the person who clicked it would find out by waiting.
 */
export const AuthoringBar = ({
  status,
  areaSlug,
  areaTitle,
  pathLength,
  pending,
  error,
  onAuthor,
  courseUrl,
}: {
  status: AuthoringStatus | null
  areaSlug: string | null
  areaTitle: string | null
  pathLength: number
  pending: boolean
  error: string | null
  onAuthor: (request: { area?: string }) => void
  /** Where the finished courses can be downloaded, for the whole project or
   *  one area. A URL rather than a handler: the browser downloads better than
   *  this console can — see `HttpExportRepository`. */
  courseUrl: (area?: string) => string
}) => {
  const running = status !== null && isRunning(status)
  const current = status?.current ?? null
  const last = status?.last ?? null

  return (
    <div className="flex flex-col gap-2 border-0 border-b border-line pb-3">
      <div className="flex flex-wrap items-center gap-2">
        <button
          type="button"
          disabled={running || pending || pathLength === 0}
          onClick={() => onAuthor({})}
          className="rounded focus-visible:lay-ring-inward border border-line bg-bg-panel px-2 py-1 text-xs hover:bg-bg-hover disabled:opacity-50"
        >
          {/* +1 for the path's own overview file, which the run writes last.
              Counted rather than rounded away: the number's whole job is that
              the cost is known before the click, and an estimate a reader can
              catch being wrong is worse than none. */}
          Write every course ({pathLength} areas and an overview, ~{pathLength * 3 + 1} model turns)
        </button>
        {areaSlug !== null && (
          <button
            type="button"
            disabled={running || pending}
            onClick={() => onAuthor({ area: areaSlug })}
            className="rounded focus-visible:lay-ring-inward border border-line bg-bg-panel px-2 py-1 text-xs hover:bg-bg-hover disabled:opacity-50"
          >
            Write “{areaTitle ?? areaSlug}” (~3 model turns)
          </button>
        )}
      </div>

      {/* `aria-live` so a run's progress reaches a screen reader without the
          reader hunting for it. `polite` rather than `assertive`: a course
          finishing is worth knowing and is never worth interrupting. */}
      <div aria-live="polite" className="text-xs text-fg-dim">
        {error !== null && <p className="m-0 text-k-failure">{error}</p>}
        {running && current !== null && (
          <p className="m-0">
            Writing {current.current ?? 'a course'} — {current.completed.length} of{' '}
            {current.targets.length} done
            {progressOf(current) !== null && ` (${Math.round((progressOf(current) ?? 0) * 100)}%)`}.
          </p>
        )}
        {!running && last !== null && (
          <p className="m-0">
            Last run wrote {last.completed.length} of {last.targets.length}.{' '}
            {/* Links, not a count. Each authoring run writes into its **own**
                session's workspace, so without these the files it produced are
                reachable only by finding that session in the tree -- which is
                to say, not reachable. This is the whole way in to the thing the
                feature exists to make. */}
            {courseLinks(last).map(({ target, sessionId }) => (
              <a
                key={target}
                href={sessionHref(
                  SessionId(sessionId),
                  null,
                  FilePath.of(
                    target === 'complete'
                      ? `${PATHS_DIR}/${target}.md`
                      : `${AREAS_DIR}/${target}/unit.md`,
                  ),
                )}
                className="focus-visible:lay-ring-inward mr-2 text-fg underline"
              >
                {target}
              </a>
            ))}
            {/* Failures are listed rather than folded into the status. A run
                that wrote seven of eight is `done`, and reporting it as failed
                would hide seven courses that exist -- but reporting it as done
                with nothing said would hide the one that did not. */}
            {last.failures.length > 0 && (
              <span className="text-k-failure">
                {' '}
                {last.failures.map((f) => `${f.target}: ${f.detail}`).join('; ')}
              </span>
            )}
          </p>
        )}
      </div>

      {/* Offered only once a run has finished, because the archive is
          assembled from that run's per-target session ids — the export answers
          409 while a run is in flight and 409 again when the server has
          restarted since, and a download route's error is a page the browser
          navigates to rather than something this pane can render. Hiding the
          link is how a person is kept out of that. */}
      {!running && last !== null && courseLinks(last).length > 0 && (
        <div className="flex flex-wrap items-center gap-2">
          <a
            href={courseUrl()}
            download
            className="rounded focus-visible:lay-ring-inward border border-line bg-bg-panel px-2 py-1 text-xs text-fg no-underline hover:bg-bg-hover"
          >
            Download all courses (.zip)
          </a>
          {/* Only when the selected area is one this run actually wrote. A
              link offered for an area with no course is a 404 the person finds
              out about by leaving the page. */}
          {areaSlug !== null && courseLinks(last).some((link) => link.target === areaSlug) && (
            <a
              href={courseUrl(areaSlug)}
              download
              className="rounded focus-visible:lay-ring-inward border border-line bg-bg-panel px-2 py-1 text-xs text-fg no-underline hover:bg-bg-hover"
            >
              Download “{areaTitle ?? areaSlug}” (.zip)
            </a>
          )}
        </div>
      )}
    </div>
  )
}
