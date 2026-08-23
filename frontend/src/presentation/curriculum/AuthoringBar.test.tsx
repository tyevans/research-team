import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import type { AuthoringRun, AuthoringStatus } from '@domain/knowledge/authoring.ts'

import { AuthoringBar } from './AuthoringBar.tsx'

/** Two suites over one bar, and they met in a merge.
 *
 * The stop control and the `cancelled`/`interrupted` readings came from the
 * durable-runs branch; the download links came from the export branch. Both
 * describe the same component and both had written their own `show`, so this
 * file settles on one harness: **`show(status, props)`**, with the status
 * positional because it is the dominant input to every test here and burying
 * it in `props` cost a nesting level in nine of them.
 *
 * The fixture is the export branch's `alpha`/`beta`, kept rather than merged
 * with the other side's `rome`/`carthage` for the reason any coin-flip is
 * settled: one of them had to go, and two naming schemes in one file is worse
 * than either.
 */

const run = (over: Partial<AuthoringRun> = {}): AuthoringRun => ({
  runId: 'r1',
  status: 'done',
  kind: 'path',
  targets: ['alpha', 'beta'],
  completed: ['alpha', 'beta'],
  sessions: ['s-alpha', 's-beta'],
  current: null,
  failures: [],
  ...over,
})

/** A run in flight, with one target written and another in hand. */
const running = (over: Partial<AuthoringRun> = {}): AuthoringStatus => ({
  current: run({
    status: 'running',
    completed: ['alpha'],
    sessions: ['s-alpha'],
    current: 'beta',
    ...over,
  }),
  last: null,
})

/** A run somebody stopped after one target. */
const stopped = (): AuthoringStatus => ({
  current: null,
  last: run({ status: 'cancelled', completed: ['alpha'], sessions: ['s-alpha'] }),
})

const show = (
  status: AuthoringStatus | null,
  props: Partial<Parameters<typeof AuthoringBar>[0]> = {},
) =>
  render(
    <AuthoringBar
      status={status}
      areaSlug={null}
      areaTitle={null}
      pathLength={2}
      pending={false}
      stopping={false}
      error={null}
      onAuthor={() => {}}
      onCancel={() => {}}
      courseUrl={(area, format) =>
        `/export/course` +
        (area ? `?area=${area}` : '') +
        (format && format !== 'zip' ? `${area ? '&' : '?'}format=${format}` : '')
      }
      {...props}
    />,
  )

describe('the stop control', () => {
  it('is absent when nothing is running', () => {
    // A control that is always there and does nothing most of the time trains
    // the reader to ignore it.
    show({ current: null, last: run() })

    expect(screen.queryByRole('button', { name: /stop writing/i })).not.toBeInTheDocument()
  })

  it('appears while a run is in flight, and is the one live control', () => {
    // The write buttons are disabled for exactly the period the stop exists,
    // which is the whole argument for showing it only then.
    show(running())

    expect(screen.getByRole('button', { name: /stop writing/i })).toBeEnabled()
    expect(screen.getByRole('button', { name: /write every course/i })).toBeDisabled()
  })

  it('asks to stop when pressed', async () => {
    const onCancel = vi.fn()
    show(running(), { onCancel })

    await userEvent.click(screen.getByRole('button', { name: /stop writing/i }))

    expect(onCancel).toHaveBeenCalledOnce()
  })

  it('cannot be pressed twice while the first press is in flight', () => {
    show(running(), { stopping: true })

    expect(screen.getByRole('button', { name: /stopping/i })).toBeDisabled()
  })
})

describe('how a finished run is reported', () => {
  it('says nothing extra about an ordinary finish', () => {
    // The count already says how it went. A "done" label on every successful
    // run is noise on the ninety-nine that were fine.
    show({ current: null, last: run() })

    expect(screen.getByText(/wrote 2 of 2/i)).toBeInTheDocument()
    expect(screen.queryByText(/stopped|interrupted|failed/i)).not.toBeInTheDocument()
  })

  it('names a stop as a stop rather than a failure', () => {
    // A cancelled run and a failed one leave the same partial set of courses
    // behind, which is why reporting one as the other misreads both.
    show(stopped())

    expect(screen.getByText(/last run stopped/i)).toBeInTheDocument()
  })

  it('spells out a run a restart interrupted', () => {
    // The one status a reader cannot guess: it is neither something they did
    // nor something the model did.
    show({
      current: null,
      last: run({ status: 'interrupted', completed: ['alpha'], sessions: ['s-alpha'] }),
    })

    expect(screen.getByText(/interrupted by a restart/i)).toBeInTheDocument()
  })

  it('still links every course a stopped run wrote', () => {
    // The point of stopping rather than killing the server. These courses
    // exist, in that session's workspace, and this link is the only way in.
    show(stopped())

    expect(screen.getByRole('link', { name: 'alpha' })).toHaveAttribute(
      'href',
      expect.stringContaining('s-alpha'),
    )
  })

  it('counts the targets a stopped run never started', () => {
    // Otherwise invisible: "wrote 1 of 2" and an empty failure list account
    // for one of the two, and say nothing about the other.
    show(stopped())

    expect(screen.getByText(/1 never started/i)).toBeInTheDocument()
  })

  it('does not count anything as unstarted when a done run lost a target', () => {
    // A `done` run reached the end of its list. Its failures are named
    // separately, and adding "0 never started" beside them would be a second
    // sentence saying nothing.
    show({
      current: null,
      last: run({
        completed: ['alpha'],
        sessions: ['s-alpha'],
        failures: [{ target: 'beta', detail: 'the model refused' }],
      }),
    })

    expect(screen.queryByText(/never started/i)).not.toBeInTheDocument()
    expect(screen.getByText(/beta: the model refused/i)).toBeInTheDocument()
  })
})

describe('AuthoringBar downloads', () => {
  it('offers the archive once a run has finished', () => {
    // The `href` is asserted, not merely the presence of a link. A download
    // link is the one control whose whole behaviour is its URL — an anchor
    // rendered with the wrong one looks correct and fetches the wrong project.
    show({ current: null, last: run() })

    const zip = screen.getByRole('link', { name: /download all courses \(\.zip\)/i })
    expect(zip).toHaveAttribute('href', '/export/course')
    expect(zip).toHaveAttribute('download')

    // The one page, offered beside the archive rather than instead of it.
    // Asserted by `href` for the reason above: the whole of what this link
    // does is its URL, and one built without `format=html` downloads a zip
    // under a name promising a page.
    const page = screen.getByRole('link', { name: /download all courses \(\.html\)/i })
    expect(page).toHaveAttribute('href', '/export/course?format=html')
    expect(page).toHaveAttribute('download')
  })

  it('offers the selected area on its own when that area was written', () => {
    show({ current: null, last: run() }, { areaSlug: 'beta', areaTitle: 'Beta' })

    expect(screen.getByRole('link', { name: /download “Beta”/i })).toHaveAttribute(
      'href',
      '/export/course?area=beta',
    )
  })

  it('does not offer an area the run never wrote', () => {
    // A link to an area with no course is a 404 the person discovers by
    // leaving the page: a download route's error is a navigation, not
    // something this pane can catch and render.
    show(
      { current: null, last: run({ completed: ['alpha'], sessions: ['s-alpha'] }) },
      { areaSlug: 'beta', areaTitle: 'Beta' },
    )

    expect(screen.queryByRole('link', { name: /download “Beta”/i })).not.toBeInTheDocument()
    expect(
      screen.getByRole('link', { name: /download all courses \(\.zip\)/i }),
    ).toBeInTheDocument()
  })

  it('offers nothing while a run is in flight', () => {
    // The server answers 409 mid-run rather than handing back a snapshot, so
    // a link offered here would be a link into an error page.
    show({
      current: run({ status: 'running', completed: ['alpha'], sessions: ['s-alpha'] }),
      last: run(),
    })

    expect(screen.queryByRole('link', { name: /download/i })).not.toBeInTheDocument()
  })

  it('offers nothing when no run is remembered', () => {
    show(null)

    expect(screen.queryByRole('link', { name: /download/i })).not.toBeInTheDocument()
  })

  it('still offers the archive for a run a stop left partial', () => {
    // Where the two halves of this bar actually meet. A stopped run wrote
    // fewer courses than it was asked for, and those courses exist -- so the
    // download is offered, over exactly what was written. The export refusing
    // mid-run is about a run *in flight*, not about a run that ended early.
    show(stopped())

    expect(screen.getByRole('link', { name: /download all courses/i })).toHaveAttribute(
      'href',
      '/export/course',
    )
  })
})
