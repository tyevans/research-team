import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import type { ActivityEntry } from '@domain/activity/activity.ts'
import { MessageId, SessionId } from '@domain/shared/identifier.ts'

import { ProvisionalBubble } from './Provisional.tsx'
import { hitList } from './shapes/fixtures.ts'

/** What `ActivityFeed.test.tsx` asserted, re-sited.
 *
 * That component is gone: the turn in flight is the last items in `.conv`
 * now, so there is no feed to render and the two assertions that were about
 * the feed rather than about a bubble went with it — whether it draws at all
 * while the turn is idle, which is `useLiveActivity`'s question and is asked
 * in its own tests, and whether it stamps a per-card provisional banner, which
 * it does again deliberately. That banner is what carries the pulsing dot, and
 * the dot is the live marker `Conversation` and the timeline both rely on.
 *
 * What survives is the half that was always about this bubble: an entry
 * carrying an artifact reaches `ToolResult`, an entry carrying none renders
 * the markup it rendered before, and the two are told apart by the artifact
 * rather than by which surface is drawing.
 */
const entry = (over: Partial<ActivityEntry> = {}): ActivityEntry => ({
  messageId: MessageId('m1'),
  sessionId: SessionId('s1'),
  kind: 'tool',
  text: null,
  payload: null,
  ...over,
})

describe('ProvisionalBubble', () => {
  it('draws a live shape from an artifact', () => {
    render(
      <ProvisionalBubble
        entry={entry({ payload: { data: { name: 'search_sources', artifact: hitList } } })}
      />,
    )

    // The structure, not the string. Red if `activityMessage` stops lifting
    // `artifact` off the payload, which is the seam that lets a provisional
    // entry reach the same component the committed transcript uses.
    expect(screen.getByText('manuscriptreport.com')).toBeInTheDocument()
    expect(screen.getByTestId('stream-glyph')).toHaveAttribute('data-phase', 'live')
  })

  it('names the tool the entry carries', () => {
    // `name` travels on the provisional payload as well as on the committed
    // message, and the header is the same header either way. Red if
    // `activityMessage` drops it and the shape falls back to its literal.
    render(
      <ProvisionalBubble
        entry={entry({ payload: { data: { name: 'web_search', artifact: hitList } } })}
      />,
    )
    expect(screen.getByText('web_search')).toBeInTheDocument()
  })

  it('settles the shape inside a discarded fold', () => {
    // The timeline's fold is over a turn that failed. A pulsing glyph there
    // claims content is still arriving into a turn that ended before the
    // reader opened the fold — the same reason that fold passes `tag={null}`
    // and loses the dot. Red if `phase` is hard-coded to `live`.
    render(
      <ProvisionalBubble
        entry={entry({ payload: { data: { artifact: hitList } } })}
        tag={null}
        phase="settled"
      />,
    )
    expect(screen.getByTestId('stream-glyph')).toHaveAttribute('data-phase', 'settled')
  })

  it('keeps the existing provisional body for an entry with no artifact', () => {
    // Every entry took this path before artifacts existed and most still do,
    // so the fallback is the common case rather than an error branch. Red if
    // `ToolResult` were allowed to substitute its own default markup here.
    const { container } = render(<ProvisionalBubble entry={entry({ text: 'thinking' })} />)
    expect(container.querySelector('.provisional-body')).toHaveTextContent('thinking')
    expect(container.querySelector('[data-testid="stream-fallback"]')).toBeNull()
  })

  it('leaves an assembled call summary literal rather than parsing it', () => {
    // `form: 'calls'` is main's distinction and it survives the artifact work
    // untouched: the summary is a label this code assembled, and through a
    // markdown parser the underscores in `search_sources` turn its middle
    // italic and vanish. Red if the fallback routed every form through
    // `Markdown`.
    const { container } = render(
      <ProvisionalBubble
        entry={entry({ payload: { data: { tool_calls: [{ name: 'read_source', args: {} }] } } })}
      />,
    )
    const body = container.querySelector('.provisional-body')
    expect(body).toHaveClass('mono')
    expect(body?.querySelector('em')).toBeNull()
  })
})
