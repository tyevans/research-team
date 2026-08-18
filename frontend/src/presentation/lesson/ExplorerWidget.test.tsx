/** What jsdom can judge about the explorer: the requests each control makes,
 *  the prose it falls back to, and the counts it is obliged to show on every
 *  result.
 *
 * The cost behaviour is deliberately not here -- it lives alone in
 * `ExplorerWidget.cost.test.tsx`, for the reason that file's docstring gives.
 * The height assertion is in `ExplorerWidget.browser.test.tsx`, for CLAUDE.md's
 * reason: jsdom lays nothing out.
 */
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { expect, it, vi } from 'vitest'

import type { AttemptsApi } from '@application/lesson/use-attempts.ts'
import { ApiError } from '@application/ports/errors.ts'
import type { ProjectId } from '@domain/shared/identifier.ts'
import { componentBlock } from '@presentation/ask/ask-fixtures.ts'

import { band, harness, PROJECT } from './timeline-widget-harness.tsx'
import { ExplorerWidget } from './ExplorerWidget.tsx'

vi.mock('../research/TimelineCanvas.tsx', () => ({
  TimelineCanvas: ({ bands }: { bands: readonly unknown[] }) => (
    <div data-testid="timeline-canvas" data-bands={bands.length} />
  ),
}))

const attempts = {} as unknown as AttemptsApi

const BASE = {
  over: 'timeline',
  prompt: 'Pull the window back.',
  vary: ['entity_type', 'window'],
}

const renderWidget = (
  data: Record<string, unknown> = BASE,
  {
    timeline = vi
      .fn()
      .mockResolvedValue({ bands: [band('b1')], undatedCount: 0, truncated: false }),
    // `null` and not `undefined` for "no project in scope": a destructuring
    // default fires on `undefined` and would restore `PROJECT`, so the
    // no-project test would silently exercise the ordinary path -- the shape
    // `EvidenceWidget.test.tsx` records having measured.
    projectId = PROJECT,
  }: { timeline?: ReturnType<typeof vi.fn>; projectId?: ProjectId | null } = {},
) => ({
  timeline,
  ...render(
    <ExplorerWidget
      block={componentBlock({ type: 'explorer', id: 'e1', data })}
      attempts={attempts}
      {...(projectId ? { projectId } : {})}
    />,
    { wrapper: harness(timeline) },
  ),
})

it('reads the author’s window first, before the reader has touched anything', async () => {
  const { timeline } = renderWidget({ ...BASE, entity_type: 'Person', from: '0300-01-01' })

  await waitFor(() =>
    expect(timeline).toHaveBeenCalledWith(PROJECT, {
      entityType: 'Person',
      from: '0300-01-01',
    }),
  )
})

it('offers every entity type the unfiltered read came back with', async () => {
  // The design's section 1 in one assertion: no route enumerates entity types,
  // so the picker's vocabulary is whatever an unfiltered response contains.
  //
  // Red against a picker populated from the *filtered* response, which on a
  // widget the author started at `Person` would offer exactly one option --
  // the one already chosen -- and would look entirely reasonable on screen.
  const timeline = vi.fn().mockImplementation((_project, window: { entityType?: string }) =>
    Promise.resolve({
      bands: window.entityType
        ? [band('p1')]
        : [
            { ...band('p1'), entityType: 'Person' },
            { ...band('w1'), entityType: 'Work' },
            { ...band('p2'), entityType: 'Person' },
          ],
      undatedCount: 0,
      truncated: false,
    }),
  )
  renderWidget({ ...BASE, entity_type: 'Person' }, { timeline })

  await waitFor(() => expect(screen.getByRole('option', { name: 'Work' })).toBeInTheDocument())
  // Deduplicated and sorted: two `Person` bands are one option, and the order
  // does not depend on the order bands arrived in.
  expect(screen.getAllByRole('option').map((option) => option.textContent)).toEqual([
    'any type',
    'Person',
    'Work',
  ])
})

it('re-reads with the type the reader chose', async () => {
  const { timeline } = renderWidget({ ...BASE, from: '0300-01-01' })
  await waitFor(() => expect(timeline).toHaveBeenCalled())
  // `toHaveBeenCalled` above is satisfied the instant the query function is
  // invoked -- synchronously, inside `render`'s own `act` -- which is before
  // the mocked promise has actually resolved and repainted the picker with
  // its vocabulary. Firing the change before that leaves 'Person' absent from
  // the `<select>`, and jsdom (like a real browser) refuses to set a select's
  // value to an option that is not there, so the change is silently dropped.
  // Waiting for the option is the deterministic form of "the picker is ready
  // to be used" -- a bare timeout would work by accident and only sometimes.
  await waitFor(() => expect(screen.getByRole('option', { name: 'Person' })).toBeInTheDocument())

  fireEvent.change(screen.getByLabelText(/entity type/i), { target: { value: 'Person' } })

  await waitFor(() =>
    expect(timeline).toHaveBeenLastCalledWith(PROJECT, {
      entityType: 'Person',
      from: '0300-01-01',
    }),
  )
})

it('draws only the controls the author opened', () => {
  // `vary` is not a formality: an author who set a window deliberately and one
  // who did not are indistinguishable to a reader unless the author says which.
  // Red against a widget defaulting `vary` to every axis.
  renderWidget({ ...BASE, vary: ['entity_type'] })

  expect(screen.getByLabelText(/entity type/i)).toBeInTheDocument()
  expect(screen.queryByLabelText(/^from$/i)).not.toBeInTheDocument()
  expect(screen.queryByLabelText(/^to$/i)).not.toBeInTheDocument()
})

it('renders an unsupported backing read as prose naming what is supported', () => {
  // The `over:` seam. The server warns rather than rejects, so this block is
  // valid and arrives renderable -- and the sentence has to name `timeline`,
  // because "not supported" alone tells an author nothing they can act on.
  const { timeline } = renderWidget({ ...BASE, over: 'graph' })

  expect(screen.getByText(/only/i)).toHaveTextContent('timeline')
  expect(screen.queryByRole('combobox')).not.toBeInTheDocument()
  expect(timeline).not.toHaveBeenCalled()
  expect(screen.queryByRole('alert')).not.toBeInTheDocument()
})

it('shows the author’s invitation, which is the point of the type', () => {
  // Without the prompt a reader is handed controls with no reason to touch
  // them, which is the design's section 3. Red against a widget that reads
  // `prompt` and never renders it.
  renderWidget({ ...BASE, prompt: 'Pull the window back to the third century.' })

  expect(screen.getByText(/third century/)).toBeInTheDocument()
})

it('says how many entities carry no dates at all, on every result', async () => {
  renderWidget(BASE, {
    timeline: vi
      .fn()
      .mockResolvedValue({ bands: [band('b1')], undatedCount: 412, truncated: false }),
  })

  await waitFor(() => expect(screen.getByText(/412/)).toBeInTheDocument())
})

it('still reports the counts when the reader has narrowed to nothing', async () => {
  // The state an explorer reaches and a timeline mostly does not: a reader
  // narrows, the bands vanish, and without the counts they cannot tell
  // exclusion from truncation. Red against a widget that returns early on an
  // empty `bands` and never reaches the counts.
  renderWidget(BASE, {
    timeline: vi.fn().mockResolvedValue({ bands: [], undatedCount: 412, truncated: true }),
  })

  await waitFor(() => expect(screen.getByText(/412/)).toBeInTheDocument())
  expect(screen.getByText(/more than could be shown/i)).toBeInTheDocument()
  expect(screen.getByText(/nothing dated/i)).toBeInTheDocument()
})

it('blames the bound rather than the project when a date will not parse', async () => {
  renderWidget(BASE, {
    timeline: vi.fn().mockRejectedValue(new ApiError("'from' is not an ISO instant", 422)),
  })

  await waitFor(() => expect(screen.getByText(/could not be read as a date/i)).toBeInTheDocument())
  expect(screen.queryByRole('alert')).not.toBeInTheDocument()
})

it('tells the reader a view cannot be linked to', () => {
  // The design's section 5: no query state is serialisable anywhere in this
  // app, so saying so is better than a share affordance that does not work.
  // Matched without an apostrophe: this build emits typographic ones and a
  // straight-quote regex would never match.
  renderWidget(BASE)

  expect(screen.getByText(/cannot be linked to/i)).toBeInTheDocument()
})

it('renders nothing but a note with no project in scope, and fetches nothing', () => {
  const { timeline } = renderWidget(BASE, { projectId: null })

  expect(timeline).not.toHaveBeenCalled()
  expect(screen.getByText(/needs a project in scope/i)).toBeInTheDocument()
})
