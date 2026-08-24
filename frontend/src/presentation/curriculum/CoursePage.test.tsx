import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { ReactElement, ReactNode } from 'react'
import { describe, expect, it, vi } from 'vitest'

import type { Container as AppContainer } from '@app/container.ts'
import { ContainerProvider } from '@app/container-context.tsx'
import type { CourseRepository } from '@application/ports/repositories.ts'
import type { CourseCandidate } from '@domain/knowledge/catalog.ts'
import type { CourseDetail } from '@domain/knowledge/course.ts'
import { ProjectId } from '@domain/shared/identifier.ts'

import { CoursePage } from './CoursePage.tsx'

const project = ProjectId('11111111-1111-1111-1111-111111111111')

const aCandidate = (over: Partial<CourseCandidate> = {}): CourseCandidate => ({
  slug: 'roman-succession',
  title: 'the roman succession crisis',
  category: 'antiquity',
  prominence: 0.8,
  size: 12,
  membershipHash: 'hash-1',
  anchors: [],
  art: { url: '/art/roman-succession.png', alt: 'A mosaic of an imperial court' },
  blurb: null,
  featuredRank: null,
  ...over,
})

const aDetail = (over: Partial<CourseDetail> = {}): CourseDetail => ({
  candidate: aCandidate(),
  outline: null,
  members: [],
  course: null,
  ...over,
})

/** Every method throws until a test stubs it, matching `CatalogPane.test.tsx`'s
 *  fakes: a page calling something it did not mean to fails loudly rather than
 *  resolving `undefined` and rendering an empty state that looks correct. */
const fakeCourses = (over: Partial<CourseRepository> = {}): CourseRepository => ({
  course: vi.fn(() => {
    throw new Error('course was not stubbed for this test')
  }),
  realize: vi.fn(() => {
    throw new Error('realize was not stubbed for this test')
  }),
  abandon: vi.fn(() => {
    throw new Error('abandon was not stubbed for this test')
  }),
  startBlurbSweep: vi.fn(() => {
    throw new Error('startBlurbSweep was not stubbed for this test')
  }),
  fetchBlurbSweep: vi.fn(() => {
    throw new Error('fetchBlurbSweep was not stubbed for this test')
  }),
  startArtSweep: vi.fn(() => {
    throw new Error('startArtSweep was not stubbed for this test')
  }),
  fetchArtSweep: vi.fn(() => {
    throw new Error('fetchArtSweep was not stubbed for this test')
  }),
  // `CoursePage` polls this on every render regardless of what a test is
  // about, matching `courseDetail`'s own always-fetched shape -- a resolved
  // default, not a throwing one, so a test unrelated to rerolling does not
  // have to stub it just to render.
  startArtReroll: vi.fn(() => {
    throw new Error('startArtReroll was not stubbed for this test')
  }),
  fetchArtReroll: vi.fn().mockResolvedValue({
    running: false,
    done: 0,
    total: 0,
    failed: 0,
    error: null,
  }),
  ...over,
})

const wrapperFor = (
  courses: CourseRepository,
): (({ children }: { children: ReactNode }) => ReactElement) => {
  const container = { courses } as unknown as AppContainer
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } })
  return ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>
      <ContainerProvider container={container}>{children}</ContainerProvider>
    </QueryClientProvider>
  )
}

const show = (courses: CourseRepository) =>
  render(<CoursePage projectId={project} slug="roman-succession" onBack={() => {}} />, {
    wrapper: wrapperFor(courses),
  })

describe('CoursePage', () => {
  it('renders the title in Title Case from a stored sentence-case string', async () => {
    const courses = fakeCourses({
      course: vi.fn<CourseRepository['course']>().mockResolvedValue(aDetail()),
    })
    show(courses)

    expect(await screen.findByText('The Roman Succession Crisis')).toBeInTheDocument()
  })

  it('offers to make an unrealized course real', async () => {
    const courses = fakeCourses({
      course: vi.fn<CourseRepository['course']>().mockResolvedValue(aDetail({ course: null })),
    })
    show(courses)

    expect(await screen.findByRole('button', { name: 'Make this course' })).toBeInTheDocument()
  })

  it('shows when a realized course was realized, and does not offer to make it again', async () => {
    const courses = fakeCourses({
      course: vi.fn<CourseRepository['course']>().mockResolvedValue(
        aDetail({
          course: {
            realizedAt: '2026-01-15T00:00:00Z',
            membershipHash: 'hash-1',
            fit: { kept: [], added: [], dropped: [], orphaned: false },
            authoredSessionId: null,
          },
        }),
      ),
    })
    show(courses)

    expect(await screen.findByText(/made into a course/i)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Make this course' })).not.toBeInTheDocument()
  })

  it('names what the cluster added and dropped when a realized course has drifted', async () => {
    const courses = fakeCourses({
      course: vi.fn<CourseRepository['course']>().mockResolvedValue(
        aDetail({
          course: {
            realizedAt: '2026-01-15T00:00:00Z',
            membershipHash: 'hash-2',
            fit: {
              kept: [{ entityId: '1', name: 'Rome' }],
              added: [{ entityId: '2', name: 'Byzantium' }],
              dropped: ['3'],
              orphaned: false,
            },
            authoredSessionId: null,
          },
        }),
      ),
    })
    show(courses)

    const summary = await screen.findByText(/drifted/i)
    expect(summary.textContent).toContain('1 added')
    expect(summary.textContent).toContain('1 dropped')
  })

  it('says the cluster is gone rather than showing a diff when the course is orphaned', async () => {
    const courses = fakeCourses({
      course: vi.fn<CourseRepository['course']>().mockResolvedValue(
        aDetail({
          course: {
            realizedAt: '2026-01-15T00:00:00Z',
            membershipHash: 'hash-2',
            fit: {
              kept: [],
              added: [{ entityId: '2', name: 'Byzantium' }],
              dropped: ['3'],
              orphaned: true,
            },
            authoredSessionId: null,
          },
        }),
      ),
    })
    show(courses)

    const summary = await screen.findByText(/gone/i)
    expect(summary.textContent).not.toContain('added')
  })

  it('links the authored session when one exists, and offers to author when none does', async () => {
    const withoutSession = fakeCourses({
      course: vi.fn<CourseRepository['course']>().mockResolvedValue(
        aDetail({
          course: {
            realizedAt: '2026-01-15T00:00:00Z',
            membershipHash: 'hash-1',
            fit: { kept: [], added: [], dropped: [], orphaned: false },
            authoredSessionId: null,
          },
        }),
      ),
    })
    show(withoutSession)
    expect(await screen.findByText(/not authored yet/i)).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: /authored session/i })).not.toBeInTheDocument()
  })

  it('links the authored session when one exists', async () => {
    const withSession = fakeCourses({
      course: vi.fn<CourseRepository['course']>().mockResolvedValue(
        aDetail({
          course: {
            realizedAt: '2026-01-15T00:00:00Z',
            membershipHash: 'hash-1',
            fit: { kept: [], added: [], dropped: [], orphaned: false },
            authoredSessionId: 'session-1',
          },
        }),
      ),
    })
    show(withSession)

    const link = await screen.findByRole('link', { name: /authored session/i })
    expect(link.getAttribute('href')).toContain('session-1')
  })

  it('marks the outline stale when its hash disagrees with the candidate', async () => {
    const courses = fakeCourses({
      course: vi.fn<CourseRepository['course']>().mockResolvedValue(
        aDetail({
          outline: {
            promise: 'a survey of empire',
            sections: [{ heading: 'Rise', summary: 'How it began.' }],
            membershipHash: 'stale-hash',
            model: 'x',
            generatedAt: '2026-01-01T00:00:00Z',
          },
        }),
      ),
    })
    show(courses)

    expect(await screen.findByText('a survey of empire')).toBeInTheDocument()
    expect(screen.getByText('(out of date)')).toBeInTheDocument()
  })

  it('does not mark a current outline stale', async () => {
    const courses = fakeCourses({
      course: vi.fn<CourseRepository['course']>().mockResolvedValue(
        aDetail({
          outline: {
            promise: 'a survey of empire',
            sections: [{ heading: 'Rise', summary: 'How it began.' }],
            membershipHash: 'hash-1',
            model: 'x',
            generatedAt: '2026-01-01T00:00:00Z',
          },
        }),
      ),
    })
    show(courses)

    expect(await screen.findByText('a survey of empire')).toBeInTheDocument()
    expect(screen.queryByText('(out of date)')).not.toBeInTheDocument()
  })

  it('realizes a course when "Make this course" is clicked', async () => {
    const user = userEvent.setup()
    const realize = vi
      .fn<CourseRepository['realize']>()
      .mockResolvedValue({ realized: true, authoring: null, reason: null })
    const courses = fakeCourses({
      course: vi.fn<CourseRepository['course']>().mockResolvedValue(aDetail()),
      realize,
    })
    show(courses)

    await user.click(await screen.findByRole('button', { name: 'Make this course' }))

    expect(realize).toHaveBeenCalledWith(project, 'roman-succession')
  })
})
