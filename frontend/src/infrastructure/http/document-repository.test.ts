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

  /** The one place the perceive route's path is written down and checked.
   *
   * Every other test of this feature stubs `DocumentRepository` whole -- the
   * component tests assert that `perceive(project, 'm1')` was called, which is
   * true of a method posting to any string at all. So a typo in the URL would
   * pass the entire frontend suite and 404 in production, and the only thing
   * between those two states was a human having read this file beside
   * `app.py`. That is `CLAUDE.md`'s fixture rule in another key: a test whose
   * arrange phase goes through the same collaborator as the code under test
   * cannot see that collaborator go wrong.
   *
   * The `{}` body is asserted too, because the route takes none and a client
   * that started sending one would be inventing a contract.
   */
  it('posts an empty body to perceive, at the path the route declares', async () => {
    const post = vi.fn().mockResolvedValue({ queued: true, source_id: 'm1' })
    const repository = new HttpDocumentRepository({ post } as unknown as HttpClient)

    await expect(repository.perceive(project, SourceId('m1'))).resolves.toBe(true)

    expect(post).toHaveBeenCalledWith(
      `/api/projects/${project}/sources/m1/perceive`,
      {},
      expect.anything(),
    )
  })

  /** `queued: false` is a 202 and not an error -- the medium is going to be
   *  perceived, because the queue already holds it. A repository that treated
   *  it as a failure would make the caller apologise for a press that worked. */
  it('reports a medium the queue already held without failing', async () => {
    const post = vi.fn().mockResolvedValue({ queued: false, source_id: 'm1' })
    const repository = new HttpDocumentRepository({ post } as unknown as HttpClient)

    await expect(repository.perceive(project, SourceId('m1'))).resolves.toBe(false)
  })
})
