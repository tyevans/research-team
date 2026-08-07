import { describe, expect, it } from 'vitest'

import { computeDiff, splitLines } from './diff.ts'

const lines = (n: number, prefix = 'line') =>
  Array.from({ length: n }, (_, i) => `${prefix} ${i}`).join('\n')

describe('computeDiff', () => {
  it('reports no changes for identical text', () => {
    const diff = computeDiff('a\nb\n', 'a\nb\n')
    expect(diff.hasChanges).toBe(false)
    expect(diff.hunks).toEqual([])
  })

  it('marks added and removed lines', () => {
    const diff = computeDiff('a\nb\n', 'a\nc\n')
    const ops = diff.hunks.flatMap((hunk) => hunk.rows.map((row) => `${row.op}:${row.text}`))
    expect(ops).toContain('del:b')
    expect(ops).toContain('add:c')
    expect(ops).toContain('ctx:a')
  })

  it('elides unchanged runs beyond the context window', () => {
    const before = `${lines(20)}\n`
    const after = `${lines(20)}\nappended\n`
    const diff = computeDiff(before, after)

    const kept = diff.hunks.flatMap((hunk) => hunk.rows)
    expect(kept.some((row) => row.op === 'add' && row.text === 'appended')).toBe(true)
    // 20 unchanged lines, 3 of context kept — the rest elided.
    expect(diff.hunks[0]!.skippedBefore).toBe(17)
    expect(kept).toHaveLength(4)
  })

  it('reports a creation as every line added', () => {
    const diff = computeDiff('', 'one\ntwo\n')
    const rows = diff.hunks.flatMap((hunk) => hunk.rows)
    expect(rows.every((row) => row.op === 'add')).toBe(true)
    expect(rows).toHaveLength(2)
  })

  it('handles a large file without degrading to a whole-block replace', () => {
    const before = `${lines(4000)}\n`
    const after = before.replace('line 2000', 'line 2000 changed')
    const diff = computeDiff(before, after)
    const rows = diff.hunks.flatMap((hunk) => hunk.rows)
    // One changed line plus context, not 8000 rows.
    expect(rows.length).toBeLessThan(12)
  })
})

describe('splitLines', () => {
  it('drops the phantom line a trailing newline produces', () => {
    expect(splitLines('a\nb\n')).toEqual(['a', 'b'])
  })

  it('keeps a genuine trailing blank line', () => {
    expect(splitLines('a\n\n')).toEqual(['a', ''])
  })

  it('is empty for nothing at all', () => {
    expect(splitLines(null)).toEqual([])
  })
})
