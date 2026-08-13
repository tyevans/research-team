import type { GateContext, GateFinding } from '@domain/approval/approval.ts'
import { severityLabel } from '@domain/project/course.ts'
import { FilePath } from '@domain/shared/file-path.ts'
import type { SessionId } from '@domain/shared/identifier.ts'

import { unimplementedChecksWarning } from '../common/findings-copy.ts'
import { Chip } from '../common/primitives.tsx'
import { Tooltip } from '../common/Tooltip.tsx'
import { sessionHref } from '../routing/routes.ts'

/** What a stage gate is asking a person to decide about.
 *
 * Read-only on purpose: the decision buttons belong to the card that owns the
 * approval, and this component owns only the case for the decision. Splitting
 * them means the same review can later be shown where no decision is being
 * taken — a settled gate in history — without the buttons coming with it.
 *
 * Styled with Tailwind utilities rather than a stylesheet. This is the first
 * surface under that rule, so it is worth saying what it costs: the class
 * strings here are longer than the `.gate-*` selectors they replace, and a
 * reader looking for "the gate styles" will find them nowhere but this file.
 * The trade is that there is no second file to keep in step, and no dead
 * selector left behind when a row is deleted.
 */
export const GateReview = ({
  context,
  sessionId,
}: {
  context: GateContext
  sessionId: SessionId
}) => (
  <section className="flex flex-col gap-3 rounded-md border border-line bg-bg-panel-2 p-3 text-md">
    <header className="flex flex-wrap items-center gap-2">
      <span className="text-fg-dim">stage</span>
      <b className="font-mono">{context.stage}</b>
      {context.blocked ? (
        // Loud because it is the one fact that changes what the reader should
        // do: a blocked gate is asking to be unblocked, not rubber-stamped.
        <Tooltip explanation="A blocking finding stands against this stage.">
          <Chip tone="fail">blocked</Chip>
        </Tooltip>
      ) : null}
    </header>

    <p className="text-fg-dim">
      reviewed {context.artifactsReviewed} artifact{context.artifactsReviewed === 1 ? '' : 's'} and{' '}
      {context.linksReviewed} link{context.linksReviewed === 1 ? '' : 's'}
    </p>

    <Findings findings={context.findings} />

    {context.unimplementedChecks.length > 0 ? (
      <p className="rounded-md border border-tint-held bg-tint-held p-2 text-fg">
        {unimplementedChecksWarning(context.unimplementedChecks)}
      </p>
    ) : null}

    {context.unreadableArtifacts.length > 0 ? (
      // An artifact the reviewer could not read is not an artifact that passed.
      <p className="rounded-md border border-tint-fail-line bg-tint-fail p-2 text-fg">
        Could not be read, so nothing here judged them:{' '}
        <span className="font-mono">{context.unreadableArtifacts.join(', ')}</span>
      </p>
    ) : null}

    {context.findingsArtifact.length > 0 ? (
      <p>
        <FileLink
          sessionId={sessionId}
          path={context.findingsArtifact}
          label="full findings report"
        />
      </p>
    ) : null}

    {/* Empty is not "no artifacts": on the hand-driven tool path the files
        genuinely are not written yet, and `gate_context()` passes no paths
        rather than paths that would answer 404. A "none" row here would read
        as a claim that the stage produced nothing, which is a different and
        wrong statement, so an empty list renders nothing at all. */}
    {context.artifactPaths.length > 0 ? (
      <div className="flex flex-col gap-1">
        <span className="text-fg-dim">what it wrote</span>
        <ul className="m-0 flex list-none flex-col gap-1 p-0">
          {context.artifactPaths.map((path) => (
            <li key={path}>
              <FileLink sessionId={sessionId} path={path} label={path} />
            </li>
          ))}
        </ul>
      </div>
    ) : null}
  </section>
)

/** Findings, grouped by severity, in the order the severities first appear.
 *
 * Grouped rather than listed because severity is what a reader triages on, and
 * first-appearance order rather than a ranking because `GateFinding.severity`
 * is a plain string authored by the reviewer prompts — a rank table would have
 * to guess where a level it has never seen belongs, and guessing wrong sorts a
 * new blocking level below advisory.
 *
 * Zero findings says so out loud. Unlike `artifactPaths`, a gate with no
 * findings is a real and meaningful state — the stage passed clean — and
 * rendering nothing would make it indistinguishable from a gate whose findings
 * failed to load.
 */
const Findings = ({ findings }: { findings: readonly GateFinding[] }) => {
  if (findings.length === 0) {
    return <p className="text-fg-dim">No check raised anything against this stage.</p>
  }

  const groups = new Map<string, GateFinding[]>()
  for (const finding of findings) {
    const group = groups.get(finding.severity)
    if (group) group.push(finding)
    else groups.set(finding.severity, [finding])
  }

  return (
    <div className="flex flex-col gap-3">
      {[...groups].map(([severity, group]) => (
        <div key={severity} className="flex flex-col gap-2">
          <h4 className="font-normal m-0 flex items-center gap-2 text-sm text-fg-dim">
            <Chip tone={severity}>{severityLabel(severity)}</Chip>
            {group.length}
          </h4>
          <ul className="m-0 flex list-none flex-col gap-2 p-0">
            {group.map((finding, index) => (
              // A finding has no id; within one severity its position is the
              // only thing separating two identically worded ones.
              <li
                key={index}
                className="flex flex-col gap-1 border-l-2 border-line-strong pl-2"
                data-severity={severity}
              >
                <span className="font-mono text-sm text-fg-dim">{finding.check}</span>
                <span>{finding.message}</span>
                {finding.suggestedEdit ? (
                  <span className="text-accent">→ {finding.suggestedEdit}</span>
                ) : null}
                {finding.cites.length > 0 ? (
                  <span className="font-mono text-sm text-fg-faint">
                    cites {finding.cites.join(', ')}
                  </span>
                ) : null}
              </li>
            ))}
          </ul>
        </div>
      ))}
    </div>
  )
}

/** A workspace path, opened in the session that holds it.
 *
 * Guarded on the path being non-empty rather than trusting the server: a link
 * to `#/s/<id>/file/` opens the file pane on nothing, which looks like the
 * viewer is broken rather than like the field was blank.
 *
 * The path is a `Tooltip` only when the label is not already the path, which
 * is #126's triage applied to the two call sites this has: "full findings
 * report" genuinely does not say where it goes, and a path labelled with
 * itself would be an explanation that repeats the text beside it. CSS
 * truncation is not an accessibility problem, so the second case gets nothing
 * rather than a tooltip nobody needs.
 */
const FileLink = ({
  sessionId,
  path,
  label,
}: {
  sessionId: SessionId
  path: string
  label: string
}) => {
  if (path.length === 0) return null

  const link = <a href={sessionHref(sessionId, undefined, FilePath.of(path))}>{label}</a>

  // `asChild`: the trigger is a real `<a href>`, already focusable and already
  // saying what it does with its own cursor. The default wrapper would put a
  // `<button>` around an anchor, which is both invalid and a second tab stop.
  return label === path ? (
    link
  ) : (
    <Tooltip asChild explanation={path}>
      {link}
    </Tooltip>
  )
}
