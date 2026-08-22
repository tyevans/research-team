import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import type { AuthoringRun, AuthoringStatus } from '@domain/knowledge/authoring.ts'

import { AuthoringBar } from './AuthoringBar.tsx'

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
      error={null}
      onAuthor={() => {}}
      courseUrl={(area) => (area ? `/export/course?area=${area}` : '/export/course')}
      {...props}
    />,
  )

describe('AuthoringBar downloads', () => {
  it('offers the archive once a run has finished', () => {
    // The `href` is asserted, not merely the presence of a link. A download
    // link is the one control whose whole behaviour is its URL — an anchor
    // rendered with the wrong one looks correct and fetches the wrong project.
    show({ current: null, last: run() })

    const link = screen.getByRole('link', { name: /download all courses/i })
    expect(link).toHaveAttribute('href', '/export/course')
    expect(link).toHaveAttribute('download')
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
      {
        areaSlug: 'beta',
        areaTitle: 'Beta',
      },
    )

    expect(screen.queryByRole('link', { name: /download “Beta”/i })).not.toBeInTheDocument()
    expect(screen.getByRole('link', { name: /download all courses/i })).toBeInTheDocument()
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
})
