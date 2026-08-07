import { diffLines } from 'diff'

/** Line diffs, from `jsdiff` rather than from a hand-rolled LCS table.
 *
 * The replaced implementation was a correct O(n·m) dynamic program with a
 * hand-tuned bail-out to a whole-block replace above 1.5M cells, because the
 * table got unpleasant. `jsdiff` implements Myers' algorithm, which is
 * O((n+m)·d) in the size of the *difference* — so the large-file case that
 * forced the bail-out is the case it is fastest on, and the degraded output
 * that bail-out produced is simply gone.
 */

export type DiffOp = 'add' | 'del' | 'ctx'

export interface DiffRow {
  readonly op: DiffOp
  readonly text: string
}

/** How many unchanged lines to keep either side of a change. */
const DIFF_CONTEXT = 3

export interface DiffHunk {
  readonly rows: readonly DiffRow[]
  /** Unchanged lines elided immediately *before* this hunk. */
  readonly skippedBefore: number
}

export interface Diff {
  readonly hunks: readonly DiffHunk[]
  /** Unchanged lines elided after the last hunk. */
  readonly skippedAfter: number
  readonly hasChanges: boolean
}

export const computeDiff = (before: string, after: string): Diff => {
  const rows = toRows(before, after)
  const keep = markContext(rows)
  const hasChanges = rows.some((row) => row.op !== 'ctx')
  if (!hasChanges) return { hunks: [], skippedAfter: 0, hasChanges: false }

  const hunks: DiffHunk[] = []
  let current: DiffRow[] = []
  let skipped = 0
  let skippedBefore = 0

  for (const [index, row] of rows.entries()) {
    if (!keep[index]) {
      if (current.length > 0) {
        hunks.push({ rows: current, skippedBefore })
        current = []
        skippedBefore = 0
      }
      skipped += 1
      continue
    }
    if (current.length === 0) {
      skippedBefore = skipped
      skipped = 0
    }
    current.push(row)
  }
  if (current.length > 0) hunks.push({ rows: current, skippedBefore })

  return { hunks, skippedAfter: skipped, hasChanges: true }
}

const toRows = (before: string, after: string): readonly DiffRow[] => {
  const rows: DiffRow[] = []
  for (const part of diffLines(before ?? '', after ?? '')) {
    const op: DiffOp = part.added ? 'add' : part.removed ? 'del' : 'ctx'
    for (const line of splitLines(part.value)) rows.push({ op, text: line })
  }
  return rows
}

/** Which rows survive elision: every change, plus its context either side. */
const markContext = (rows: readonly DiffRow[]): readonly boolean[] => {
  const keep = new Array<boolean>(rows.length).fill(false)
  for (const [index, row] of rows.entries()) {
    if (row.op === 'ctx') continue
    const from = Math.max(0, index - DIFF_CONTEXT)
    const to = Math.min(rows.length - 1, index + DIFF_CONTEXT)
    for (let k = from; k <= to; k += 1) keep[k] = true
  }
  return keep
}

/** Lines without the phantom empty one a trailing newline produces. */
export const splitLines = (text: string | null | undefined): readonly string[] => {
  const lines = String(text ?? '').split('\n')
  if (lines.length > 0 && lines[lines.length - 1] === '') lines.pop()
  return lines
}

export const elisionLabel = (count: number): string =>
  `  ⋯ ${count} unchanged line${count === 1 ? '' : 's'}`
