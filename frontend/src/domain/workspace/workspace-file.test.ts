import { describe, expect, it } from 'vitest'

import { FilePath } from '../shared/file-path.ts'
import { EventIndex } from '../session/event-index.ts'
import { diffSubject, findFile, type FileRevision, type WorkspaceFile } from './workspace-file.ts'

const revision = (over: Partial<FileRevision> = {}): FileRevision => ({
  index: EventIndex(1),
  type: 'FileWritten',
  occurredAt: '2026-01-01T00:00:00.000Z',
  content: null,
  oldString: null,
  newString: null,
  replaceAll: null,
  ...over,
})

const file = (path: string): WorkspaceFile => ({
  path: FilePath.of(path),
  size: 0,
  revisions: 1,
})

describe('FilePath', () => {
  it('reads its basename', () => {
    expect(FilePath.of('/course/00-plan.md').basename).toBe('00-plan.md')
    expect(FilePath.of('plan.md').basename).toBe('plan.md')
  })

  it('recognises the markdown extensions the viewer offers a rendered mode for', () => {
    for (const path of ['a.md', 'a.MARKDOWN', 'a.mdown', 'a.mkd']) {
      expect(FilePath.of(path).isMarkdown).toBe(true)
    }
    for (const path of ['a.txt', 'a.py', 'a', 'a.md.bak']) {
      expect(FilePath.of(path).isMarkdown).toBe(false)
    }
  })

  it('does not read a leading dot as an extension', () => {
    expect(FilePath.of('.md').extension).toBe('')
  })

  it('compares by value, since a path arrives fresh from every fold', () => {
    expect(FilePath.of('/a.md').equals(FilePath.of('/a.md'))).toBe(true)
    expect(FilePath.of('/a.md').equals(FilePath.of('/b.md'))).toBe(false)
    expect(FilePath.of('/a.md').equals(null)).toBe(false)
  })
})

describe('findFile', () => {
  const files = [file('/a.md'), file('/b.md')]

  it('finds by value', () => {
    expect(findFile(files, FilePath.of('/b.md'))?.path.value).toBe('/b.md')
  })

  it('is null for a path the workspace does not hold at this point', () => {
    expect(findFile(files, FilePath.of('/c.md'))).toBeNull()
    expect(findFile(files, null)).toBeNull()
  })
})

describe('diffSubject', () => {
  it('uses the recorded edit intent when there is one', () => {
    const subject = diffSubject(revision({ oldString: 'before', newString: 'after' }), null)
    expect(subject).toEqual({ before: 'before', after: 'after', note: null })
  })

  it('diffs a write against the previous revision, since no intent was recorded', () => {
    const subject = diffSubject(revision({ content: 'v2' }), revision({ content: 'v1' }))
    expect(subject).toEqual({ before: 'v1', after: 'v2', note: null })
  })

  it('names a creation, because a diff against nothing reads the same either way', () => {
    expect(diffSubject(revision({ content: 'hello' }), null).note).toBe('created — full contents:')
  })

  it('names a removal for the same reason', () => {
    const subject = diffSubject(revision({ type: 'FileDeleted' }), revision({ content: 'gone' }))
    expect(subject).toEqual({ before: 'gone', after: '', note: 'removed' })
  })

  it('prefers a recorded intent over reconstruction, even when a previous revision exists', () => {
    const subject = diffSubject(
      revision({ oldString: 'x', newString: 'y', content: 'whole file' }),
      revision({ content: 'earlier' }),
    )
    expect(subject.before).toBe('x')
  })

  it('treats an empty edit intent as an intent, not as a missing one', () => {
    // Inserting into an empty region is a real edit the agent recorded.
    expect(diffSubject(revision({ oldString: '', newString: 'added' }), null)).toEqual({
      before: '',
      after: 'added',
      note: null,
    })
  })
})
