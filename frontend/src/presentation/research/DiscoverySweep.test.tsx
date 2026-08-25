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

    expect(onRun).toHaveBeenCalledWith({ again: false, lenient: false })
  })

  it('says a fully-read corpus is finished, and still offers a re-read', async () => {
    // The half of this that changed on 2026-08-24: it used to offer *no*
    // button, which made a corpus whose classes were all refused a dead end --
    // the pane said everything had been read and there was nothing to press.
    const onRun = vi.fn()
    render(<DiscoverySweep {...props} pending={[]} onRun={onRun} />)

    expect(screen.getByText(/every extracted document has been read/i)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /^read \d+ documents?$/i })).not.toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: /read every document again/i }))

    expect(onRun).toHaveBeenCalledWith({ again: true, lenient: false })
  })

  it('sends the lenient setting with whichever button was pressed', async () => {
    // Both halves: the checkbox is read at press time, and it does not turn an
    // ordinary press into a re-read. A single boolean covering both would make
    // "read the pending documents leniently" unreachable.
    const onRun = vi.fn()
    render(<DiscoverySweep {...props} pending={['a']} onRun={onRun} />)

    await userEvent.click(screen.getByRole('checkbox'))
    await userEvent.click(screen.getByRole('button', { name: /read 1 document/i }))

    expect(onRun).toHaveBeenCalledWith({ again: false, lenient: true })
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
    // Every control, not `getByRole('button')`: a running sweep that left the
    // re-read pressable would start a second one over the same corpus.
    for (const control of screen.getAllByRole('button')) expect(control).toBeDisabled()
    expect(screen.getByRole('checkbox')).toBeDisabled()
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
