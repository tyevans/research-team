import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { Delegation } from './Delegation.tsx'
import { delegation } from './fixtures.ts'

describe('Delegation', () => {
  it('shows workers on one wall-clock axis so a serialised fan-out looks wrong', () => {
    // Four rows that each report a plausible duration say nothing. Placed on
    // one axis, a fan-out that silently serialised draws as a staircase --
    // which is the entire reason this shape draws bars rather than printing
    // durations.
    render(<Delegation artifact={delegation} phase="settled" />)
    const bars = screen.getAllByTestId('worker-bar')
    expect(bars[0]).toHaveStyle({ left: '0%' })
    expect(bars[1]).toHaveStyle({ left: '0%' })
    // The axis is the turn so far: worker-c ends latest at 8000ms, so it
    // starts three quarters of the way along.
    expect(bars[2]).toHaveStyle({ left: '75%' })
    expect(bars[3]).toHaveAttribute('data-running', 'true')
  })

  it('pins an unfinished worker to the live edge rather than giving it a width', () => {
    // `duration_ms` is null precisely because nothing has measured it, so a
    // width would be invented. Zero-width would read as "returned
    // immediately", which is the opposite of true.
    render(<Delegation artifact={delegation} phase="settled" />)
    const running = screen.getAllByTestId('worker-bar')[3]
    expect(running).toHaveStyle({ right: '0%' })
    expect(running?.style.width).toBe('')
    expect(screen.getByText('…')).toBeInTheDocument()
  })

  it('marks a worker that failed', () => {
    render(<Delegation artifact={delegation} phase="settled" />)
    expect(screen.getAllByTestId('worker-bar')[2]).toHaveAttribute('data-ok', 'false')
  })

  it('prints each finished worker’s duration', () => {
    render(<Delegation artifact={delegation} phase="settled" />)
    expect(screen.getByText('6.0s')).toBeInTheDocument()
  })

  it('survives a delegation with no workers yet', () => {
    // The span is zero before anything has started, and every percentage would
    // be `NaN%` -- which is not a width, so each bar would keep whatever the
    // previous render gave it.
    render(<Delegation artifact={{ ...delegation, workers: [] }} phase="settled" />)
    expect(screen.queryAllByTestId('worker-bar')).toHaveLength(0)
    expect(screen.getByText('0 workers')).toBeInTheDocument()
  })
})
