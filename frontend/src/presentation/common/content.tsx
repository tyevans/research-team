import clsx from 'clsx'
import { useMemo } from 'react'

import type { ProjectId } from '@domain/shared/identifier.ts'
import { computeDiff, elisionLabel, splitLines } from '@infrastructure/rendering/diff.ts'
import { isEmptyMarkdown, renderMarkdown } from '@infrastructure/rendering/markdown.ts'
import { expandReferences } from '@infrastructure/rendering/references.ts'

/** Markdown, rendered and sanitised.
 *
 * `dangerouslySetInnerHTML` appears exactly once in this application — here —
 * and the html it is given came from `renderMarkdown`, which runs it through
 * DOMPurify with a closed tag allow-list. Everything model-authored that
 * reaches the page goes through this component, which makes the claim
 * checkable by grep rather than by reading every renderer. `expandReferences`
 * runs first and `renderMarkdown` runs second, unchanged, over its output —
 * that order is the security argument: nothing the pre-pass produces skips
 * sanitisation, it only ever adds an `<a>` for `renderMarkdown`'s own
 * allow-list to accept or strip.
 *
 * `projectId` is optional because two callers -- `FileView` and the lesson
 * widgets -- have no project in scope. With none given, a `[[src:...]]`
 * reference simply doesn't expand and renders as the literal text it already
 * falls back to for an unresolvable or malformed one; that is an existing
 * route to an existing behaviour, not a new state.
 *
 * Memoised on the source: a conversation re-renders on every stream frame, and
 * re-parsing every assistant message each time is the difference between a
 * smooth log and a stuttering one. The reference pre-pass lives inside that
 * same memo rather than a second one -- two memos over one input would be two
 * chances to invalidate differently. */
export const Markdown = ({
  source,
  projectId,
  className,
}: {
  source: string
  projectId?: ProjectId
  className?: string
}) => {
  const html = useMemo(
    () => renderMarkdown(projectId ? expandReferences(source, projectId) : source),
    [source, projectId],
  )
  if (isEmptyMarkdown(source)) {
    return (
      <div className={clsx('md', className)}>
        <div className="empty">(empty file)</div>
      </div>
    )
  }
  return <div className={clsx('md', className)} dangerouslySetInnerHTML={{ __html: html }} />
}

/** A file's contents, with line numbers. Text, never markup — the value of a
 *  tool result or a source file is being shown byte-for-byte. */
export const CodeBlock = ({ text, className }: { text: string; className?: string }) => {
  const lines = useMemo(() => splitLines(text), [text])
  if (lines.length === 0) {
    return (
      <pre className={clsx('code', className)}>
        <span className="dl skip"> (empty file)</span>
      </pre>
    )
  }
  return (
    <pre className={clsx('code', className)}>
      {lines.map((line, index) => (
        // A line's identity in a file *is* its position; nothing else
        // distinguishes two blank ones.
        <span key={index}>
          <span className="ln">{index + 1}</span>
          {`${line}\n`}
        </span>
      ))}
    </pre>
  )
}

/** A unified diff with unchanged runs elided.
 *
 * Elisions are labelled rather than silent: "17 unchanged lines" tells a reader
 * that the gap is context and not a rendering failure, which a bare gap does
 * not. */
export const DiffView = ({ before, after }: { before: string; after: string }) => {
  const diff = useMemo(() => computeDiff(before, after), [before, after])

  if (!diff.hasChanges) {
    return (
      <pre className="diff">
        <span className="dl skip"> (no textual change)</span>
      </pre>
    )
  }

  return (
    <pre className="diff">
      {diff.hunks.map((hunk, hunkIndex) => (
        <span key={hunkIndex} className="diff-hunk">
          {hunk.skippedBefore > 0 ? (
            <span className="dl skip">{elisionLabel(hunk.skippedBefore)}</span>
          ) : null}
          {hunk.rows.map((row, rowIndex) => (
            <span key={rowIndex} className={`dl ${row.op}`}>
              <span className="sig">{row.op === 'add' ? '+' : row.op === 'del' ? '-' : ' '}</span>
              {row.text}
            </span>
          ))}
        </span>
      ))}
      {diff.skippedAfter > 0 ? (
        <span className="dl skip">{elisionLabel(diff.skippedAfter)}</span>
      ) : null}
    </pre>
  )
}
