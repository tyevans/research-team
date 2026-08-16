import { describe, expect, it, vi } from 'vitest'

import { ProjectId, SourceId } from '@domain/shared/identifier.ts'

import { HttpDocumentRepository } from './document-repository.ts'
import type { HttpClient } from './http-client.ts'

const row = {
  source_id: 's1',
  // Required rather than defaulted, and that is the point: `documentDto` is a
  // discriminated union now, so a row with no `kind` does not parse at all
  // rather than parsing as text and failing later on a field it lacks.
  kind: 'text' as const,
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

  it('posts media as multipart, with the file under the name the route reads', async () => {
    // The field name is `file` because `upload_media` declares it that way;
    // anything else is a 422 the browser reports as a validation error about a
    // field nobody typed. Sent through `postForm` rather than `post`, because
    // `post` writes a JSON content type and the boundary would be lost.
    const postForm = vi.fn().mockResolvedValue({
      source_id: 'keynote',
      kind: 'media',
      media_type: 'video/mp4',
      byte_count: 12,
      sha256: 'abc',
      uri: null,
      title: null,
      published_at: null,
      note: null,
      dropped_reason: null,
      extracted: false,
    })
    const repository = new HttpDocumentRepository({ postForm } as unknown as HttpClient)
    const file = new File(['x'], 'keynote.mp4', { type: 'video/mp4' })

    const stored = await repository.uploadMedia(project, { sourceId: 'keynote', file })

    const [path, form] = postForm.mock.calls[0] as [string, FormData]
    expect(path).toBe(`/api/projects/${project}/sources/media`)
    expect(form.get('file')).toBe(file)
    expect(form.get('source_id')).toBe('keynote')
    // Absent rather than empty: FastAPI reads a missing form field as `None`
    // and an empty string as a title of "".
    expect(form.get('title')).toBeNull()
    expect(stored.mediaType).toBe('video/mp4')
    expect(stored.byteCount).toBe(12)
  })

  it('builds a content URL through the client, so the base url is applied once', async () => {
    // Fails if a component builds this path itself: the console is served from
    // a different origin than the API in development, and a hand-built path
    // would 404 there while passing every test that never left jsdom.
    const url = vi.fn((path: string) => `http://api.test${path}`)
    const repository = new HttpDocumentRepository({ url } as unknown as HttpClient)

    expect(repository.contentUrl(project, SourceId('a b'))).toBe(
      `http://api.test/api/projects/${project}/sources/a%20b/content`,
    )
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
