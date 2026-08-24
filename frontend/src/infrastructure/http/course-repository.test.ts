import { expect, it, vi } from 'vitest'

import { ProjectId } from '@domain/shared/identifier.ts'

import { HttpCourseRepository } from './course-repository.ts'

const PROJECT = ProjectId('11111111-1111-4111-8111-111111111111')

const CANDIDATE = {
  slug: 'rome',
  title: 'the fall of rome',
  category: 'history',
  prominence: 1,
  size: 3,
  membershipHash: 'hash-1',
  anchors: [],
  art: { url: '/a.png', alt: '' },
  blurb: null,
  featuredRank: null,
}

it('fetches one course by slug', async () => {
  const http = {
    get: vi.fn().mockResolvedValue({
      candidate: CANDIDATE,
      outline: null,
      members: [],
      course: null,
    }),
  }
  const repository = new HttpCourseRepository(http as never)

  const detail = await repository.course(PROJECT, 'rome')

  const [url] = http.get.mock.calls[0] as [string]
  expect(url).toBe(`/api/projects/${PROJECT}/catalog/rome`)
  expect(detail.candidate.slug).toBe('rome')
  expect(detail.outline).toBeNull()
  expect(detail.course).toBeNull()
})

it('maps a realized course and its drift fit', async () => {
  const http = {
    get: vi.fn().mockResolvedValue({
      candidate: CANDIDATE,
      outline: {
        promise: 'p',
        sections: [{ heading: 'h', summary: 's' }],
        membershipHash: 'hash-1',
        model: 'x',
        generatedAt: '2026-01-01T00:00:00Z',
      },
      members: [
        { entity_id: '1', name: 'Rome', entity_type: 'Place', centrality: 0.5, temporal: null },
      ],
      course: {
        realizedAt: '2026-01-02T00:00:00Z',
        membershipHash: 'hash-1',
        fit: {
          kept: [{ entity_id: '1', name: 'Rome' }],
          added: [],
          dropped: ['2'],
          orphaned: false,
        },
        authoredSessionId: 'sess-1',
      },
    }),
  }
  const repository = new HttpCourseRepository(http as never)

  const detail = await repository.course(PROJECT, 'rome')

  expect(detail.outline?.sections).toEqual([{ heading: 'h', summary: 's' }])
  expect(detail.members[0]?.name).toBe('Rome')
  expect(detail.course?.fit.dropped).toEqual(['2'])
  expect(detail.course?.authoredSessionId).toBe('sess-1')
})

it('realizes a course, resolving through to authoring and reason', async () => {
  const http = {
    post: vi.fn().mockResolvedValue({ realized: true, authoring: null, reason: 'not configured' }),
  }
  const repository = new HttpCourseRepository(http as never)

  const result = await repository.realize(PROJECT, 'rome')

  const [url] = http.post.mock.calls[0] as [string]
  expect(url).toBe(`/api/projects/${PROJECT}/catalog/rome/realize`)
  expect(result).toEqual({ realized: true, authoring: null, reason: 'not configured' })
})

it('abandons a course', async () => {
  const http = { post: vi.fn().mockResolvedValue({ slug: 'rome', realized: false }) }
  const repository = new HttpCourseRepository(http as never)

  await repository.abandon(PROJECT, 'rome')

  const [url] = http.post.mock.calls[0] as [string]
  expect(url).toBe(`/api/projects/${PROJECT}/catalog/rome/abandon`)
})

it('starts and reads a blurb sweep', async () => {
  const progress = { running: true, done: 1, total: 4, failed: 0, error: null }
  const http = {
    post: vi.fn().mockResolvedValue(progress),
    get: vi.fn().mockResolvedValue(progress),
  }
  const repository = new HttpCourseRepository(http as never)

  await repository.startBlurbSweep(PROJECT)
  await repository.fetchBlurbSweep(PROJECT)

  expect(http.post.mock.calls[0]?.[0]).toBe(`/api/projects/${PROJECT}/catalog/blurbs`)
  expect(http.get.mock.calls[0]?.[0]).toBe(`/api/projects/${PROJECT}/catalog/blurbs`)
})
