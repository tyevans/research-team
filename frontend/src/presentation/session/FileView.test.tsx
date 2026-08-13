import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { ReactNode } from 'react'
import { expect, it, vi } from 'vitest'

import type { Container as AppContainer } from '@app/container.ts'
import { ContainerProvider } from '@app/container-context.tsx'
import { ApiError } from '@application/ports/errors.ts'
import { ScrubPoint } from '@domain/session/scrub-point.ts'
import { EventIndex } from '@domain/session/event-index.ts'
import { FilePath } from '@domain/shared/file-path.ts'
import type { SessionId } from '@domain/shared/identifier.ts'

import { FileView } from './FileView.tsx'

/** The file viewer: three tab groups, one of them keyed, and a 404 that is
 *  information rather than a failure.
 *
 * The last of phase 4's six prerequisites (§10), and the largest. Three of its
 * rules are the kind that break silently and were untested:
 *
 * 1. **The open tab is stamped with the file it belongs to.** Switching files
 *    while `history` is open must show the *new* file's contents, not its
 *    history -- and must do it on the render that changes files. The component
 *    carries a key rather than clearing in an effect precisely because the
 *    effect version left the history tab showing against the new file for one
 *    paint. A test that only checked "the tab resets eventually" would pass
 *    against the version this replaced.
 *
 * 2. **A 404 is an empty state, not an error.** The path simply had not been
 *    written yet at that point in the log. Rendering `ErrorBox` there would
 *    tell a reader something broke when nothing did, and the retry button
 *    would re-ask an unchanging question.
 *
 * 3. **The audience toggle only appears when there is something to withhold.**
 *    A control that does nothing, in a header that is already crowded.
 *
 * **Proved red** against four breaks: the tab no longer keyed to the file; a
 * 404 falling through to `ErrorBox` (fails two cases, since both 404 sentences
 * go through it); the audience toggle shown without `lesson.interactive`; and
 * the render toggle offered for a non-markdown path.
 *
 * A fifth break -- removing the local `TabGroup`'s `if (option.id !== active)`
 * guard -- failed nothing. That component is gone; the comment block at the end
 * of this file records where the guard went and why the successor is testable
 * where this one was not.
 *
 * **What this does not assert:** how markdown renders (`content.tsx`), how a
 * lesson document renders (`LessonDocument`), or the revision history
 * (`FileHistory`, which has its own test). The `lessons` port is faked to
 * return a document with no components unless a case is specifically about the
 * audience toggle, which keeps every other case on the plain-markdown path the
 * component is careful to leave alone.
 */

const SESSION = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee' as SessionId
const README = FilePath.of('/README.md')
const SCRIPT = FilePath.of('/run.py')

const container = (over: Record<string, unknown> = {}) =>
  ({
    workspace: {
      readFile: vi.fn().mockResolvedValue('# Title\n\nbody text'),
      history: vi.fn().mockResolvedValue([]),
    },
    lessons: {
      // No components: `hasComponents` is false, so `interactive` is false and
      // the audience toggle stays away. The plain-markdown path.
      parse: vi.fn().mockResolvedValue({ blocks: [] }),
      // `progress`, not `attempts`: `useAttempts` folds the learner's existing
      // answers back in and reads this unconditionally, so a fake without it
      // throws during render rather than failing an assertion.
      progress: vi.fn().mockResolvedValue([]),
    },
    ...over,
  }) as unknown as AppContainer

const view = (
  props: Partial<Parameters<typeof FileView>[0]> = {},
  parts: Record<string, unknown> = {},
) => {
  const deps = container(parts)
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } })
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>
      <ContainerProvider container={deps}>{children}</ContainerProvider>
    </QueryClientProvider>
  )
  const result = render(
    <FileView sessionId={SESSION} path={README} scrub={ScrubPoint.head()} {...props} />,
    { wrapper },
  )
  return { ...result, deps, wrapper }
}

it('says to pick a file rather than showing an empty frame', () => {
  view({ path: null })

  expect(screen.getByText('No file selected.')).toBeInTheDocument()
  // The detail names both things a reader can do next. "Empty states that do
  // not say what to do next" is a defect named in two of the four reports.
  expect(screen.getByText(/Pick a file above/)).toBeInTheDocument()
})

it('starts a newly opened file on its contents, not on the last file’s tab', async () => {
  const user = userEvent.setup()
  const { rerender, wrapper } = view()

  await screen.findByText(/body text/)
  await user.click(screen.getByRole('tab', { name: 'history' }))
  expect(screen.getByRole('tab', { name: 'history' })).toHaveAttribute('aria-selected', 'true')

  rerender(<FileView sessionId={SESSION} path={SCRIPT} scrub={ScrubPoint.head()} />)

  // Immediately, on the render that changes files -- not one render later.
  // The tab is stamped with the path it belongs to, so a mismatched key reads
  // as `content` during the same render rather than being corrected by an
  // effect afterwards. The version this replaced showed the *previous* file's
  // history against the new file for one paint, and an assertion that waited
  // would have passed against it.
  expect(screen.getByRole('tab', { name: 'contents' })).toHaveAttribute('aria-selected', 'true')
  expect(screen.getByRole('tab', { name: 'history' })).toHaveAttribute('aria-selected', 'false')
  void wrapper
})

it('offers rendered and source for markdown only', async () => {
  const { unmount } = view()
  await screen.findByText(/body text/)
  expect(screen.getByRole('radio', { name: 'rendered' })).toBeInTheDocument()
  unmount()

  // A `.py` file has nothing to render. Absent rather than disabled, which is
  // the same choice `ScrubBar` makes for controls that cannot work.
  view({ path: SCRIPT })
  await screen.findByText(/body text/)
  expect(screen.queryByRole('radio', { name: 'rendered' })).not.toBeInTheDocument()
})

it('hides the render toggle while the history tab is open', async () => {
  const user = userEvent.setup()
  view()
  await screen.findByText(/body text/)

  await user.click(screen.getByRole('tab', { name: 'history' }))

  // There is nothing being rendered to toggle. Leaving it up would offer a
  // control whose effect is invisible until the reader switches back.
  expect(screen.queryByRole('radio', { name: 'rendered' })).not.toBeInTheDocument()
})

it('shows the raw bytes in source mode', async () => {
  const user = userEvent.setup()
  view()
  await screen.findByText(/body text/)

  await user.click(screen.getByRole('radio', { name: 'source' }))

  // `# Title` as literal text: rendered, it is a heading and the hash is gone.
  // Asserting the hash survives is what distinguishes the two modes without
  // reaching into how markdown renders, which is `content.tsx`'s business.
  expect(screen.getByText(/# Title/)).toBeInTheDocument()
})

it('does not offer the audience toggle for a document with nothing to withhold', async () => {
  view()
  await screen.findByText(/body text/)

  // `interactive` is false, so there is no answer or rationale to hide and the
  // learner view would be identical to the author view. A control that does
  // nothing, in a header that is already crowded.
  expect(screen.queryByRole('radio', { name: 'learner' })).not.toBeInTheDocument()
})

it('offers the audience toggle once the document has components', async () => {
  view(
    {},
    {
      lessons: {
        parse: vi.fn().mockResolvedValue({
          blocks: [
            {
              kind: 'component',
              id: 'q1',
              type: 'multiple-choice',
              data: { prompt: 'which?', options: ['a', 'b'] },
              raw: '',
              lang: 'mcq',
              unknown: false,
              errors: [],
            },
          ],
        }),
        progress: vi.fn().mockResolvedValue([]),
      },
    },
  )

  expect(await screen.findByRole('radio', { name: 'learner' })).toBeInTheDocument()
  // Author first: this console's reader is the person building the course, and
  // the learner view is a preview of somebody else's screen.
  expect(screen.getByRole('radio', { name: 'author' })).toHaveAttribute('aria-checked', 'true')
})

it('treats a missing file as an empty state, not as a failure', async () => {
  view(
    {},
    {
      workspace: {
        readFile: vi.fn().mockRejectedValue(new ApiError('nope', 404)),
        history: vi.fn().mockResolvedValue([]),
      },
    },
  )

  // The path had not been written yet, or was removed. Nothing broke, so
  // there is no error and no retry -- retrying would re-ask a question whose
  // answer cannot change.
  expect(await screen.findByText('No such file.')).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: /retry/i })).not.toBeInTheDocument()
})

it('says where the file was missing from when the reader is in the past', async () => {
  view(
    { scrub: ScrubPoint.at(EventIndex(12)) },
    {
      workspace: {
        readFile: vi.fn().mockRejectedValue(new ApiError('nope', 404)),
        history: vi.fn().mockResolvedValue([]),
      },
    },
  )

  // "Not in the workspace here" is a claim about a moment. At HEAD the same
  // 404 means the file does not exist at all, which is a different sentence
  // for a reader deciding whether they mistyped or scrubbed too far back.
  expect(await screen.findByText('Not in the workspace here.')).toBeInTheDocument()
  expect(screen.getByText(/did not exist at event 12/)).toBeInTheDocument()
})

it('offers a retry for a failure that could actually resolve', async () => {
  const readFile = vi.fn().mockRejectedValue(new ApiError('boom', 500))
  view({}, { workspace: { readFile, history: vi.fn().mockResolvedValue([]) } })

  // The long timeout is the behaviour, not a workaround. `Contents` sets its
  // own `retry` predicate -- up to two more attempts for anything that is not
  // a 404 -- and react-query backs off between them, so the error box does not
  // appear for well over the 1000ms default. Waiting for it here is also the
  // only thing that distinguishes "retried and gave up" from "surfaced the
  // first failure immediately", which is the difference the predicate exists
  // to make.
  expect(
    await screen.findByText('Could not read this file', {}, { timeout: 5000 }),
  ).toBeInTheDocument()
  expect(readFile).toHaveBeenCalledTimes(3)

  // The distinction this pair of tests exists for: a 500 might succeed on a
  // second ask and a 404 will not, so only one of them gets a button.
  expect(screen.getByRole('button', { name: /retry/i })).toBeInTheDocument()
})

/** **The `if (option.id !== active)` guard this file used to admit was untested
 *  has left the building, and the two halves of it landed differently.**
 *
 *  The original: a test for it was written and deleted, because clicking the
 *  already-active tab and asserting nothing changed passed with the guard
 *  removed. React bails out of a re-render when a `useState` setter is called
 *  with the value the state already holds, so `setAudience('author')` while the
 *  audience is already `author` produces no render, no new query key and no
 *  refetch. Unobservable through the interface rather than merely uncovered.
 *
 *  Where it went. For the tabs, into Radix: `Tabs` does not call
 *  `onValueChange` for the tab that is already open, so the guard is the
 *  library's and is the same guard for every future call site rather than one
 *  per component. Still unobservable from here, for the same React reason, and
 *  still not asserted here.
 *
 *  For the choices it became something with teeth. `ToggleGroup` in single mode
 *  reports `''` when the pressed item is pressed again, which is a *different*
 *  value rather than the same one -- so React does not bail out, the query key
 *  changes, and forwarding it would refetch the document for an audience that
 *  does not exist. `Choices` drops it, and `Choices.test.tsx` fails if that line
 *  is removed. The defence that could only be argued for is now the one that can
 *  be proved. */
