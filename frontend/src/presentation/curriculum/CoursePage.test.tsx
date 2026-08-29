import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { ReactElement, ReactNode } from 'react'
import { describe, expect, it, vi } from 'vitest'

import type { Container as AppContainer } from '@app/container.ts'
import { ContainerProvider } from '@app/container-context.tsx'
import type { CourseRepository, CurriculumRepository } from '@application/ports/repositories.ts'
import type { CourseCandidate } from '@domain/knowledge/catalog.ts'
import type { CourseDetail, CourseText } from '@domain/knowledge/course.ts'
import { ProjectId, SessionId } from '@domain/shared/identifier.ts'

import { OverlayHost } from '../layout/OverlayHost.tsx'
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

const aText = (over: Partial<CourseText> = {}): CourseText => ({
  slug: 'roman-succession',
  state: 'unauthored',
  sessionId: null,
  unitPath: null,
  unit: null,
  lessons: [],
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
  // Resolved rather than throwing, for `fetchArtReroll`'s reason above:
  // `CourseUnit` fetches this on every realized course, so a test about drift
  // or about the abandon button would otherwise have to stub the course text
  // just to render. `unauthored` is the default because it is the state that
  // renders one line and asserts nothing -- a default holding real markdown
  // would put text on the page every unrelated test could accidentally match.
  courseText: vi.fn<CourseRepository['courseText']>().mockResolvedValue(aText()),
  ...over,
})

/** A realized course, since every course-text test needs one to render the
 *  unit at all -- `CoursePage` shows `CourseUnit` only where `course` is not
 *  null, which is the same condition that hides the outline. */
const aRealized = (over: Partial<CourseDetail['course'] & object> = {}): CourseDetail =>
  aDetail({
    course: {
      realizedAt: '2026-01-15T00:00:00Z',
      membershipHash: 'hash-1',
      fit: { kept: [], added: [], dropped: [], orphaned: false },
      authoredSessionId: null,
      ...over,
    },
  })

const wrapperFor = (
  courses: CourseRepository,
  curricula: Partial<CurriculumRepository> = {},
): (({ children }: { children: ReactNode }) => ReactElement) => {
  const container = { courses, curricula } as unknown as AppContainer
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } })
  // `OverlayHost`, because the take-over offer is a `Confirm`, which is a
  // `Drawer`, which is an `Overlay` -- and `Overlay` renders `null` until a
  // host's container ref is set. Without it the dialog is absent rather than
  // broken, which reads in a failure exactly like a page that never offered
  // it. The app has the host in `Shell`; a bare render does not.
  return ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>
      <ContainerProvider container={container}>
        <OverlayHost>{children}</OverlayHost>
      </ContainerProvider>
    </QueryClientProvider>
  )
}

const show = (courses: CourseRepository, curricula: Partial<CurriculumRepository> = {}) =>
  render(<CoursePage projectId={project} slug="roman-succession" onBack={() => {}} />, {
    wrapper: wrapperFor(courses, curricula),
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

  it('offers no session link when nothing has been authored', async () => {
    const withoutSession = fakeCourses({
      course: vi.fn<CourseRepository['course']>().mockResolvedValue(aRealized()),
    })
    show(withoutSession)
    await screen.findByText(/made into a course/i)
    expect(screen.queryByRole('link', { name: /session/i })).not.toBeInTheDocument()
  })

  it('keeps the authoring session reachable, but no longer as the way in', async () => {
    const withSession = fakeCourses({
      course: vi
        .fn<CourseRepository['course']>()
        .mockResolvedValue(aRealized({ authoredSessionId: 'session-1' })),
      courseText: vi
        .fn<CourseRepository['courseText']>()
        .mockResolvedValue(aText({ state: 'authored', unit: '# Succession\n\nThe unit.' })),
    })
    show(withSession)

    const link = await screen.findByRole('link', { name: /authoring session/i })
    expect(link.getAttribute('href')).toContain('session-1')
    // The point of the demotion: the course itself is on the page beside the
    // link, so the transcript is no longer the only door. Fails if the unit
    // ever stops rendering, which is the whole increment.
    expect(await screen.findByRole('heading', { name: 'Succession' })).toBeInTheDocument()
  })

  it('renders the authored unit as prose, not as a download or a transcript link', async () => {
    const courses = fakeCourses({
      course: vi.fn<CourseRepository['course']>().mockResolvedValue(aRealized()),
      courseText: vi.fn<CourseRepository['courseText']>().mockResolvedValue(
        aText({
          state: 'authored',
          sessionId: 'session-1',
          unit: '# Roman Succession\n\nLearners will grasp the *adoptive* principle.',
          lessons: [
            { path: '/course/areas/roman-succession/lesson-01.md', markdown: '# The Five Good' },
          ],
        }),
      ),
    })
    show(courses)

    // Asserted as rendered markdown -- a heading element and an emphasis
    // element -- rather than as the source string. A component that dumped the
    // markdown into a `<p>` would satisfy a text match and would not be a
    // rendered course.
    expect(await screen.findByRole('heading', { name: 'Roman Succession' })).toBeInTheDocument()
    expect(screen.getByText('adoptive').tagName).toBe('EM')
    expect(screen.getByRole('heading', { name: 'The Five Good' })).toBeInTheDocument()
  })

  it('tells a reader nobody has started from a run writing this course right now', async () => {
    const nobody = fakeCourses({
      course: vi.fn<CourseRepository['course']>().mockResolvedValue(aRealized()),
      courseText: vi
        .fn<CourseRepository['courseText']>()
        .mockResolvedValue(aText({ state: 'unauthored' })),
    })
    const { unmount } = show(nobody)
    expect(await screen.findByText(/nobody has written this course yet/i)).toBeInTheDocument()
    unmount()

    // The distinction the outline's nullable field could not carry: one of
    // these is a reason to ask for the course and the other is a reason to
    // wait. Fails against any implementation that renders one line for both.
    const running = fakeCourses({
      course: vi.fn<CourseRepository['course']>().mockResolvedValue(aRealized()),
      courseText: vi
        .fn<CourseRepository['courseText']>()
        .mockResolvedValue(aText({ state: 'authoring' })),
    })
    show(running)
    expect(await screen.findByText(/being written now/i)).toBeInTheDocument()
    expect(screen.queryByText(/nobody has written this course yet/i)).not.toBeInTheDocument()
  })

  it('says the framing is missing rather than hiding lessons that were written', async () => {
    const courses = fakeCourses({
      course: vi.fn<CourseRepository['course']>().mockResolvedValue(aRealized()),
      courseText: vi.fn<CourseRepository['courseText']>().mockResolvedValue(
        aText({
          state: 'authored',
          unit: null,
          lessons: [{ path: '/course/areas/x/lesson-01.md', markdown: '# Orphaned lesson' }],
        }),
      ),
    })
    show(courses)

    expect(await screen.findByText(/framing for this course was not written/i)).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Orphaned lesson' })).toBeInTheDocument()
  })

  it('drops the generated outline once the real course exists', async () => {
    const outline = {
      promise: 'a survey of empire',
      sections: [{ heading: 'Rise', summary: 'How it began.' }],
      membershipHash: 'hash-1',
      model: 'x',
      generatedAt: '2026-01-01T00:00:00Z',
    }
    const courses = fakeCourses({
      course: vi
        .fn<CourseRepository['course']>()
        .mockResolvedValue(aDetail({ outline, course: aRealized().course })),
      courseText: vi
        .fn<CourseRepository['courseText']>()
        .mockResolvedValue(aText({ state: 'authored', unit: '# Succession\n\nThe real thing.' })),
    })
    show(courses)

    // The owner's decision, pinned: the outline was a pitch to help somebody
    // decide, and once they have decided and the course exists the pitch is
    // two descriptions of one thing, free to disagree. Fails if anyone renders
    // both, or adds a toggle.
    expect(await screen.findByRole('heading', { name: 'Succession' })).toBeInTheDocument()
    expect(screen.queryByText('a survey of empire')).not.toBeInTheDocument()
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
      .mockResolvedValue({ realized: true, authoring: null, reason: null, heldBy: null })
    const courses = fakeCourses({
      course: vi.fn<CourseRepository['course']>().mockResolvedValue(aDetail()),
      realize,
    })
    show(courses)

    await user.click(await screen.findByRole('button', { name: 'Make this course' }))

    expect(realize).toHaveBeenCalledWith(project, 'roman-succession')
  })

  /** The console's half of the holding-session defect.
   *
   * `realize` answers 202 whether or not a run started -- the decision is
   * appended either way -- so a page that only watched for an error showed a
   * realized course and never wrote one. Measured on the owner's database on
   * 2026-08-29: three authoring runs failed ~30ms after their 202, all
   * naming one chat session, and nothing on any surface said so.
   *
   * These would pass with the whole dialog deleted if they asserted only
   * that `realize` was called, which is what the pre-existing test above
   * does and why it could not catch this.
   */
  describe('when another session holds the project', () => {
    const heldCourses = () =>
      fakeCourses({
        course: vi.fn<CourseRepository['course']>().mockResolvedValue(aDetail({ course: null })),
        realize: vi.fn<CourseRepository['realize']>().mockResolvedValue({
          realized: true,
          authoring: null,
          reason: 'this project is held by session 049ac30c-3c8f-4ff7-8908-6d0daebaede1',
          heldBy: SessionId('049ac30c-3c8f-4ff7-8908-6d0daebaede1'),
        }),
      })

    it('offers to take the lock, naming the holder', async () => {
      const user = userEvent.setup()
      show(heldCourses())

      await user.click(await screen.findByRole('button', { name: 'Make this course' }))

      expect(await screen.findByText(/another session has this project/i)).toBeInTheDocument()
      expect(screen.getByText(/049ac30c/)).toBeInTheDocument()
    })

    it('authors the one area with take-over when the offer is accepted', async () => {
      const user = userEvent.setup()
      const author = vi.fn().mockResolvedValue({})
      show(heldCourses(), { author })

      await user.click(await screen.findByRole('button', { name: 'Make this course' }))
      await user.click(await screen.findByRole('button', { name: 'Take it and write the course' }))

      expect(author).toHaveBeenCalledWith(project, { area: 'roman-succession', takeOver: true })
    })

    it('keeps the offer open and says why when the holder is mid-turn', async () => {
      const user = userEvent.setup()
      const author = vi
        .fn()
        .mockRejectedValue(new Error('the holding session has a turn running; cancel it first'))
      show(heldCourses(), { author })

      await user.click(await screen.findByRole('button', { name: 'Make this course' }))
      await user.click(await screen.findByRole('button', { name: 'Take it and write the course' }))

      expect(await screen.findByText(/turn running/)).toBeInTheDocument()
      // Still open: a dialog that closed on the refusal would read as a
      // take-over that worked.
      expect(screen.getByText(/another session has this project/i)).toBeInTheDocument()
    })

    it('does not offer the take-over when nothing holds the project', async () => {
      const user = userEvent.setup()
      const courses = fakeCourses({
        course: vi.fn<CourseRepository['course']>().mockResolvedValue(aDetail({ course: null })),
        realize: vi
          .fn<CourseRepository['realize']>()
          .mockResolvedValue({ realized: true, authoring: null, reason: null, heldBy: null }),
      })
      show(courses)

      await user.click(await screen.findByRole('button', { name: 'Make this course' }))

      expect(screen.queryByText(/another session has this project/i)).not.toBeInTheDocument()
    })
  })
})
