import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import type { InteractionLogHealth } from '@domain/interaction/log.ts'

import { HealthStrip } from './HealthStrip.tsx'

const NOW = new Date('2026-08-25T12:00:00Z')

const health = (over: Partial<InteractionLogHealth> = {}): InteractionLogHealth => ({
  collecting: true,
  total: 12_043,
  firstAt: new Date('2026-08-19T09:12:04Z'),
  lastAt: new Date('2026-08-25T11:55:00Z'),
  kinds: [{ kind: 'ViewEntered', count: 4102 }],
  failures: [],
  installCount: 1,
  sessionCount: 87,
  ...over,
})

describe('HealthStrip', () => {
  it('answers the first question with numbers rather than a status word', () => {
    render(<HealthStrip health={health()} now={NOW} />)
    expect(screen.getByText('12043')).toBeInTheDocument()
    expect(screen.getByText('5m ago')).toBeInTheDocument()
    expect(screen.getByText('87')).toBeInTheDocument()
  })

  it('distinguishes switched off from broken', () => {
    render(<HealthStrip health={health({ collecting: false, total: 0, lastAt: null })} now={NOW} />)
    expect(screen.getByText('off')).toBeInTheDocument()
    // "never", not "unknown": an empty log has no last event, and that is an
    // answer rather than a missing value.
    expect(screen.getByText('never')).toBeInTheDocument()
  })

  it('renders no failures block at all when there are none', () => {
    render(<HealthStrip health={health()} now={NOW} />)
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
    // And no green counterpart either. A tick that is always present is
    // furniture, and the eye stops seeing furniture.
    expect(screen.queryByText(/healthy/i)).not.toBeInTheDocument()
  })

  it('renders the failures block, with the errors, when the projection dropped something', () => {
    render(
      <HealthStrip
        now={NOW}
        health={health({
          failures: [
            {
              id: 'f-1',
              eventType: 'SearchPerformed',
              error: 'query_text too long',
              failedAt: new Date('2026-08-25T11:00:00Z'),
            },
          ],
        })}
      />,
    )
    expect(screen.getByRole('alert')).toBeInTheDocument()
    expect(screen.getByText('1 event the projection could not process')).toBeInTheDocument()
    expect(screen.getByText(/query_text too long/)).toBeInTheDocument()
  })
})
