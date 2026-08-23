import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import { DiscoverySweep } from './DiscoverySweep.tsx'

const props = {
  pending: null as readonly string[] | null,
  running: false,
  progress: null,
  error: null,
  onRun: () => {},
}

describe('DiscoverySweep', () => {
  it('offers the sweep with the count of what it would read', async () => {
    const onRun = vi.fn()
    render(<DiscoverySweep {...props} pending={['a', 'b', 'c']} onRun={onRun} />)

    await userEvent.click(screen.getByRole('button', { name: /read 3 documents/i }))

    expect(onRun).toHaveBeenCalledOnce()
  })

  it('says a fully-read corpus is finished, and offers no button', () => {
    render(<DiscoverySweep {...props} pending={[]} />)

    expect(screen.getByText(/every extracted document has been read/i)).toBeInTheDocument()
    expect(screen.queryByRole('button')).not.toBeInTheDocument()
  })

  it('counts progress against the total while the sweep runs', () => {
    render(
      <DiscoverySweep
        {...props}
        pending={['a', 'b', 'c']}
        running
        progress={{ done: 1, total: 3, found: 2, barren: 0, declined: 0 }}
      />,
    )

    expect(screen.getByText(/1 of 3/)).toBeInTheDocument()
    expect(screen.getByRole('button')).toBeDisabled()
  })

  it('reports documents that were declined apart from documents that state nothing', () => {
    // The distinction the whole payload is arranged around: `found: null` is a
    // document that was *not read* -- too long, or an unreadable reply -- and
    // it stays pending, where `found: 0` is read and barren and is done. A
    // summary that collapsed them would tell a reader the corpus is finished
    // when a third of it was refused.
    render(
      <DiscoverySweep
        {...props}
        pending={['a', 'b', 'c']}
        progress={{ done: 3, total: 3, found: 1, barren: 1, declined: 1 }}
      />,
    )

    expect(screen.getByText(/1 was not read/i)).toBeInTheDocument()
    expect(screen.getByText(/states no classes/i)).toBeInTheDocument()
  })

  it('shows a failure without claiming the sweep finished', () => {
    render(<DiscoverySweep {...props} pending={['a']} error="the model timed out" />)

    expect(screen.getByText(/the model timed out/)).toBeInTheDocument()
  })
})
