import { describe, expect, it, vi } from 'vitest'

import { ProjectId, SourceId } from '@domain/shared/identifier.ts'

import { HttpDocumentRepository } from './document-repository.ts'
import type { HttpClient } from './http-client.ts'

const row = {
  source_id: 's1',
  char_count: 5,
  sha256: 'abc',
  uri: null,
  title: 'Hello',
  published_at: null,
  note: null,
  dropped_reason: null,
  extracted: false,
}

const project = ProjectId('11111111-1111-4111-8111-111111111111')

describe('HttpDocumentRepository writes', () => {
  it('posts a draft to the collection', async () => {
    const post = vi.fn().mockResolvedValue(row)
    const repository = new HttpDocumentRepository({ post } as unknown as HttpClient)

    const created = await repository.create(project, { sourceId: 's1', text: 'hello' })

    expect(post).toHaveBeenCalledWith(
      `/api/projects/${project}/sources`,
      { source_id: 's1', text: 'hello' },
      expect.anything(),
    )
    expect(created.title).toBe('Hello')
  })

  it('omits fields an edit did not set, so the server keeps them', async () => {
    // The client half of the design: a metadata-only edit sends no `text`,
    // and the server reads the stored text back rather than the browser
    // round-tripping the whole document to change a title.
    const patch = vi.fn().mockResolvedValue(row)
    const repository = new HttpDocumentRepository({ patch } as unknown as HttpClient)

    await repository.revise(project, SourceId('s1'), { title: 'Fixed' })

    expect(patch).toHaveBeenCalledWith(
      `/api/projects/${project}/sources/s1`,
      { title: 'Fixed' },
      expect.anything(),
    )
  })

  it('sends the reason on a drop', async () => {
    const post = vi.fn().mockResolvedValue({ ...row, dropped_reason: 'off topic' })
    const repository = new HttpDocumentRepository({ post } as unknown as HttpClient)

    const dropped = await repository.drop(project, SourceId('s1'), 'off topic')

    expect(post).toHaveBeenCalledWith(
      `/api/projects/${project}/sources/s1/drop`,
      { reason: 'off topic' },
      expect.anything(),
    )
    expect(dropped.droppedReason).toBe('off topic')
  })

  it('posts an empty body to restore', async () => {
    const post = vi.fn().mockResolvedValue(row)
    const repository = new HttpDocumentRepository({ post } as unknown as HttpClient)

    await repository.restore(project, SourceId('s1'))

    expect(post).toHaveBeenCalledWith(
      `/api/projects/${project}/sources/s1/restore`,
      {},
      expect.anything(),
    )
  })
})
