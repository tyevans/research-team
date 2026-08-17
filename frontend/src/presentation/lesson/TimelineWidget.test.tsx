/** What jsdom can judge about the timeline widget: the request it makes and
 *  the counts it is obliged to show.
 *
 * The height assertion is in `TimelineWidget.browser.test.tsx` for
 * `GraphWidget`'s reason, and the same one CLAUDE.md gives: jsdom lays
 * nothing out.
 */
import { render, screen, waitFor } from '@testing-library/react'
import { expect, it, vi } from 'vitest'

import { ApiError } from '@application/ports/errors.ts'
import type { AttemptsApi } from '@application/lesson/use-attempts.ts'
import type { ProjectId } from '@domain/shared/identifier.ts'
import { componentBlock } from '@presentation/ask/ask-fixtures.ts'

import { band, harness, PROJECT } from './timeline-widget-harness.tsx'
import { TimelineWidget } from './TimelineWidget.tsx'

vi.mock('../research/TimelineCanvas.tsx', () => ({
  TimelineCanvas: ({ bands }: { bands: readonly unknown[] }) => (
    <div data-testid="timeline-canvas" data-bands={bands.length} />
  ),
}))

const attempts = {} as unknown as AttemptsApi

const renderWidget = (
  data: Record<string, unknown>,
  {
    timeline = vi
      .fn()
      .mockResolvedValue({ bands: [band('b1')], undatedCount: 0, truncated: false }),
    // `null` and not `undefined` for "no project in scope". A destructuring
    // default fires on `undefined`, so `{ projectId: undefined }` would
    // restore `PROJECT` and the no-project test would silently exercise the
    // ordinary path instead -- the shape `EvidenceWidget.test.tsx` records
    // having measured.
    projectId = PROJECT,
  }: { timeline?: ReturnType<typeof vi.fn>; projectId?: ProjectId | null } = {},
) => ({
  timeline,
  ...render(
    <TimelineWidget
      block={componentBlock({ type: 'timeline', id: 'fourth-century', data })}
      attempts={attempts}
      {...(projectId ? { projectId } : {})}
    />,
    { wrapper: harness(timeline) },
  ),
})

it('asks for exactly the window the author wrote', async () => {
  const { timeline } = renderWidget({
    entity_type: 'Person',
    from: '0300-01-01',
    to: '0400-01-01',
  })

  await waitFor(() =>
    expect(timeline).toHaveBeenCalledWith(PROJECT, {
      entityType: 'Person',
      from: '0300-01-01',
      to: '0400-01-01',
    }),
  )
})

it('asks for the whole timeline when the author bounded nothing', async () => {
  // An omitted bound is an open end. Red against a reader that defaults
  // `from` to anything -- the request would silently narrow.
  const { timeline } = renderWidget({})

  await waitFor(() => expect(timeline).toHaveBeenCalledWith(PROJECT, {}))
})

it('says how many entities carry no dates at all', async () => {
  // The denominator. Most entities in a real graph carry no dates, so a
  // timeline is a view of a minority of the corpus -- and a widget that shows
  // eight bands without saying four hundred were undated has misrepresented
  // the project. Red against a widget that renders only `bands`.
  renderWidget(
    { entity_type: 'Person' },
    {
      timeline: vi
        .fn()
        .mockResolvedValue({ bands: [band('b1')], undatedCount: 412, truncated: false }),
    },
  )

  await waitFor(() => expect(screen.getByText(/412/)).toBeInTheDocument())
})

it('says when the server capped the answer', async () => {
  // A timeline that quietly drops two thirds of its bands is the read-model
  // failure this project has already had once, and `truncated` is the only
  // thing that shows it.
  renderWidget(
    {},
    {
      timeline: vi
        .fn()
        .mockResolvedValue({ bands: [band('b1')], undatedCount: 0, truncated: true }),
    },
  )

  await waitFor(() => expect(screen.getByText(/more than could be shown/i)).toBeInTheDocument())
})

it('says so plainly when nothing in the window is dated', async () => {
  renderWidget(
    { entity_type: 'Person' },
    { timeline: vi.fn().mockResolvedValue({ bands: [], undatedCount: 9, truncated: false }) },
  )

  await waitFor(() => expect(screen.getByText(/nothing dated/i)).toBeInTheDocument())
  expect(screen.queryByRole('alert')).not.toBeInTheDocument()
})

it('still reports the undated count when no band matched the window', async () => {
  // "Nothing dated matches, and 412 entities carry no dates" is a more useful
  // answer than either half. Red against a widget that returns early on an
  // empty `bands` and never reaches the counts.
  renderWidget(
    { entity_type: 'Person' },
    { timeline: vi.fn().mockResolvedValue({ bands: [], undatedCount: 412, truncated: false }) },
  )

  await waitFor(() => expect(screen.getByText(/412/)).toBeInTheDocument())
})

it('names the unparseable bound rather than blaming the project', async () => {
  // `/timeline` 422s on a date it cannot parse rather than clamping, unlike
  // nearly everything else these widgets call (`app.py`'s `read_timeline`
  // says why). An author who wrote `from: fourth century` needs to be told
  // that, and "this project's timeline could not be read" would send them
  // looking at the corpus. Red against a widget with one error branch.
  renderWidget(
    { from: 'the fourth century' },
    {
      timeline: vi.fn().mockRejectedValue(new ApiError("'from' is not an ISO instant", 422)),
    },
  )

  await waitFor(() => expect(screen.getByText(/could not be read as a date/i)).toBeInTheDocument())
  expect(screen.queryByRole('alert')).not.toBeInTheDocument()
})

it('does not fetch a permanent failure twice, whatever the app-wide default is', async () => {
  // The app's global is `retry: 1` (`main.tsx:27`), which is right for a
  // console pane on a flaky link and wrong for these blocks: the failures a
  // resolved widget meets are permanent by construction -- a 422 on a
  // mistyped date is a 422 forever -- and retrying only doubles the wait
  // before the reader gets the sentence saying so. `resolvedWidgetQuery` sets
  // that once, at the shape level.
  //
  // Red against a widget that omits `...resolvedWidgetQuery`: the client here
  // is built the way the real one is, so the call count comes back 2.
  const timeline = vi.fn().mockRejectedValue(new ApiError("'from' is not an ISO instant", 422))
  render(
    <TimelineWidget
      block={componentBlock({ type: 'timeline', id: 't', data: { from: 'nonsense' } })}
      attempts={attempts}
      projectId={PROJECT}
    />,
    { wrapper: harness(timeline, 1) },
  )

  await waitFor(() => expect(screen.getByText(/could not be read as a date/i)).toBeInTheDocument())
  expect(timeline).toHaveBeenCalledTimes(1)
})

it('renders nothing but a note with no project in scope, and fetches nothing', () => {
  const { timeline } = renderWidget({ entity_type: 'Person' }, { projectId: null })

  expect(timeline).not.toHaveBeenCalled()
  expect(screen.getByText(/needs a project in scope/i)).toBeInTheDocument()
})
