import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import type { ReactElement, ReactNode } from 'react'
import { describe, expect, it, vi } from 'vitest'

import type { Container as AppContainer } from '@app/container.ts'
import { ContainerProvider } from '@app/container-context.tsx'
import type { CourseRepository, LessonRepository } from '@application/ports/repositories.ts'
import type { CourseText } from '@domain/knowledge/course.ts'
import type { LessonDocument } from '@domain/lesson/document.ts'
import { ComponentId, ProjectId } from '@domain/shared/identifier.ts'

import { CourseUnit } from './CourseUnit.tsx'

const project = ProjectId('6e7bd68f-68e6-422f-a11d-3c2e4612de55')
const session = '11111111-2222-3333-4444-555555555555'

/** The raw markdown the authoring turns write: prose with a fenced component
 *  block in it. This is the *source*, and the point of the test is that it must
 *  not be what reaches the screen. */
const LESSON_MARKDOWN = [
  'Read this, then answer.',
  '',
  '```component:mcq',
  'id: res-uu1-mcq',
  'prompt: What distinguishes a resolution from a wrap-up?',
  'options:',
  '  - text: It ties the central conflict together.',
  '  - text: It is the last paragraph.',
  '```',
].join('\n')

/** What the server's parse route answers for that file, in the learner view --
 *  the answer key already stripped, which is why `withheld` is non-empty. */
const parsed: LessonDocument = {
  blocks: [
    { kind: 'markdown', text: 'Read this, then answer.\n' },
    {
      kind: 'component',
      id: ComponentId('res-uu1-mcq'),
      type: 'mcq',
      data: {
        prompt: 'What distinguishes a resolution from a wrap-up?',
        options: [
          { text: 'It ties the central conflict together.' },
          { text: 'It is the last paragraph.' },
        ],
      },
      raw: LESSON_MARKDOWN,
      lang: 'component:mcq',
      unknown: false,
      errors: [],
      withheld: ['answer'],
      resolved: false,
    },
  ],
}

const authored = (): CourseText => ({
  slug: 'resolution',
  state: 'authored',
  sessionId: session,
  unitPath: 'course/areas/resolution/unit.md',
  unit: LESSON_MARKDOWN,
  lessons: [{ path: 'course/areas/resolution/lesson-1.md', markdown: LESSON_MARKDOWN }],
})

const show = (lessons: Partial<LessonRepository>) => {
  const courses = {
    courseText: vi.fn<CourseRepository['courseText']>().mockResolvedValue(authored()),
  } as unknown as CourseRepository
  const container = { courses, lessons } as unknown as AppContainer
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } })
  const wrapper = ({ children }: { children: ReactNode }): ReactElement => (
    <QueryClientProvider client={client}>
      <ContainerProvider container={container}>{children}</ContainerProvider>
    </QueryClientProvider>
  )
  return render(<CourseUnit projectId={project} slug="resolution" />, { wrapper })
}

describe('a course page renders its widgets rather than their source', () => {
  /** Red against the build before this fix, and red for the reason that
   *  matters: `CourseUnit` handed the markdown to `<Markdown>`, so the fence
   *  became `<pre><code class="language-component:mcq">` holding `id:
   *  res-uu1-mcq` and the options as yaml. The assertion is deliberately on the
   *  *rendered widget* -- a role, and the option text as a real control -- and
   *  not on "nothing threw": the old path threw nothing at all and drew 19 code
   *  blocks. */
  it('draws the mcq as an operable widget, in the unit and in every lesson', async () => {
    const parse = vi.fn<LessonRepository['parse']>().mockResolvedValue(parsed)
    show({ parse, progress: vi.fn().mockResolvedValue(new Map()) })

    // Two: the unit and its one lesson. A fix that reached only the lessons
    // would settle at one -- and on the measured course that would have been
    // 10 of the 19 blocks still raw. `waitFor` rather than `findAllBy`, which
    // resolves on the *first* match and would pass at one: the two files are
    // separate queries and land on separate renders.
    await waitFor(() => expect(screen.getAllByLabelText('mcq component')).toHaveLength(2))

    expect(screen.getAllByRole('radio', { name: /ties the central conflict/ })).toHaveLength(2)

    // The yaml must be gone, not merely outranked by the widget beside it.
    expect(screen.queryByText(/id: res-uu1-mcq/)).toBeNull()
  })

  /** The parse is asked for as a learner, which is what makes the answer key
   *  the server's business. A page that asked as `author` would render
   *  identically and ship the key to the browser, so this cannot be left to
   *  the widget assertion above. */
  it('asks the server for the learner projection, never the author one', async () => {
    const parse = vi.fn<LessonRepository['parse']>().mockResolvedValue(parsed)
    show({ parse, progress: vi.fn().mockResolvedValue(new Map()) })

    await waitFor(() => expect(screen.getAllByLabelText('mcq component')).toHaveLength(2))
    expect(parse).toHaveBeenCalled()
    for (const call of parse.mock.calls) expect(call[2]).toBe('learner')
    expect(parse.mock.calls.map((call) => call[1].value).sort()).toEqual([
      'course/areas/resolution/lesson-1.md',
      'course/areas/resolution/unit.md',
    ])
  })

  /** A parse that fails must cost the widgets and nothing else. Asserting the
   *  prose is on screen rather than that no error box appeared: an empty page
   *  with no error box would pass the weaker form. */
  it('falls back to prose when the parse fails, rather than losing the course', async () => {
    const parse = vi.fn<LessonRepository['parse']>().mockRejectedValue(new Error('no such file'))
    show({ parse, progress: vi.fn().mockResolvedValue(new Map()) })

    expect(await screen.findAllByText('Read this, then answer.')).toHaveLength(2)
  })
})
