import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import type { SessionStore } from '@application/session/session-store.ts'
import { emptyActivity, putActivity, type ActivityEntry } from '@domain/activity/activity.ts'
import { MessageId, SessionId } from '@domain/shared/identifier.ts'

import { ActivityFeed } from './ActivityFeed.tsx'
import { hitList } from './shapes/fixtures.ts'

const entry = (over: Partial<ActivityEntry> = {}): ActivityEntry => ({
  messageId: MessageId('m1'),
  sessionId: SessionId('s1'),
  kind: 'tool',
  text: null,
  payload: null,
  ...over,
})

/** The component only ever reads through the selector, so a function that
 *  applies one to a fixed state is the whole of the store it needs. Building a
 *  real zustand store would test zustand. */
const storeOf = (entries: readonly ActivityEntry[], status = 'sending') => {
  const state = {
    turn: { status },
    activity: entries.reduce((buffer, one) => putActivity(buffer, one), emptyActivity()),
  }
  return ((selector: (s: typeof state) => unknown) => selector(state)) as unknown as SessionStore
}

describe('ActivityFeed', () => {
  it('no longer stamps every card with a provisional banner', () => {
    // Repeated once per card it stopped being read at all, which is the
    // opposite of what a provisional marker is for. Phase is position now:
    // everything above the live edge is settled by virtue of being above it.
    render(<ActivityFeed store={storeOf([entry({ text: 'thinking' })])} />)
    expect(screen.queryByText(/not yet recorded/i)).not.toBeInTheDocument()
  })

  it('draws a live shape from an artifact', () => {
    render(
      <ActivityFeed
        store={storeOf([
          entry({ payload: { data: { name: 'search_sources', artifact: hitList } } }),
        ])}
      />,
    )
    expect(screen.getByText('manuscriptreport.com')).toBeInTheDocument()
    expect(screen.getByTestId('stream-glyph')).toHaveAttribute('data-phase', 'live')
  })

  it('keeps the existing provisional body for an entry with no artifact', () => {
    // Every entry took this path before this work and most still do, so the
    // fallback is the common case rather than an error branch. Red if
    // `ToolResult` were allowed to substitute its own default markup here.
    const { container } = render(<ActivityFeed store={storeOf([entry({ text: 'thinking' })])} />)
    expect(container.querySelector('.provisional-body')).toHaveTextContent('thinking')
  })

  it('shimmers only where prose is still arriving', () => {
    // `text` is the delta accumulator and is null on a whole-message entry --
    // which is exactly the entry that has nothing more coming, so a shimmer
    // there would promise an update that never lands.
    const streaming = render(<ActivityFeed store={storeOf([entry({ text: 'part of a sen' })])} />)
    expect(streaming.container.querySelector('.stream-shim')).not.toBeNull()
    streaming.unmount()

    const done = render(
      <ActivityFeed store={storeOf([entry({ payload: { data: { content: 'done' } } })])} />,
    )
    expect(done.container.querySelector('.stream-shim')).toBeNull()
  })

  it('renders nothing once the turn is idle', () => {
    // A bubble outliving the turn is one nothing would ever clear.
    const { container } = render(
      <ActivityFeed store={storeOf([entry({ text: 'thinking' })], 'idle')} />,
    )
    expect(container).toBeEmptyDOMElement()
  })
})
