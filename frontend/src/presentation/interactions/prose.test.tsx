import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import type { LoggedInteraction } from '@domain/interaction/log.ts'
import { BrowserSessionId, InstallId } from '@domain/shared/identifier.ts'

import { INTERACTION_KINDS } from '../routing/routes.ts'
import { interactionProse } from './prose.tsx'

const anEvent = (
  kind: string,
  payload: Record<string, unknown> = {},
  over: Partial<LoggedInteraction> = {},
): LoggedInteraction => ({
  browserSessionId: BrowserSessionId('bs-1'),
  installId: InstallId('in-1'),
  seq: 1,
  kind,
  view: 'project/catalog',
  occurredAt: new Date('2026-08-25T10:00:00Z'),
  receivedAt: null,
  projectId: null,
  sessionId: null,
  payload,
  ...over,
})

/** The rendered sentence as one string, so an assertion reads like the row. */
const prose = (event: LoggedInteraction): string => {
  const { container } = render(<>{interactionProse(event)}</>)
  return container.textContent ?? ''
}

describe('interactionProse', () => {
  it('says where a view was entered', () => {
    expect(prose(anEvent('ViewEntered'))).toBe('entered project/catalog')
  })

  it('reads an exit as the spec writes it, dwell and hidden both', () => {
    expect(prose(anEvent('ViewExited', { dwell_ms: 2310, hidden_ms: 400 }))).toBe(
      'left project/catalog after 2.3s (0.4s hidden)',
    )
  })

  it('leaves the hidden slice off when there was none, rather than printing a zero', () => {
    expect(prose(anEvent('ViewExited', { dwell_ms: 2310, hidden_ms: 0 }))).toBe(
      'left project/catalog after 2.3s',
    )
  })

  it('reads a search as its query and its result count', () => {
    expect(prose(anEvent('SearchPerformed', { query_text: 'aqueducts', result_count: 0 }))).toBe(
      'searched “aqueducts” — 0 results',
    )
  })

  it('reads an approval as decision, latency and whether details were opened', () => {
    expect(
      prose(
        anEvent('ApprovalDecided', {
          decision: 'approved',
          latency_ms: 14_200,
          expanded_details: true,
        }),
      ),
    ).toBe('approved after 14.2s, details opened')
  })

  it('says so when the details were not opened, because that is the signal', () => {
    expect(
      prose(
        anEvent('ApprovalDecided', {
          decision: 'approved',
          latency_ms: 900,
          expanded_details: false,
        }),
      ),
    ).toBe('approved after 0.9s, details not opened')
  })

  it('names the attention pair against the view they happened on', () => {
    expect(prose(anEvent('AttentionLost'))).toBe('the tab was backgrounded on project/catalog')
    expect(prose(anEvent('AttentionRegained'))).toBe('the tab came back on project/catalog')
  })

  it('reads the rest of the vocabulary', () => {
    expect(prose(anEvent('EntityOpened', { entity_id: 'e-9', source: 'search' }))).toBe(
      'opened entity e-9 from search',
    )
    expect(
      prose(anEvent('ProjectSwitched', { to_project_id: 'p-2', from_project_id: 'p-1' })),
    ).toBe('switched to project p-2 from p-1')
    expect(prose(anEvent('ExtractionQueued', { source_id: 'q3-memo' }))).toBe(
      'queued q3-memo for extraction',
    )
    expect(prose(anEvent('ExtractionCancelled', { source_id: 'q3-memo' }))).toBe(
      'cancelled extraction of q3-memo',
    )
    expect(prose(anEvent('DispatchRequested', { topic_id: 't-1', action: 'widen' }))).toBe(
      'widen on topic t-1',
    )
    expect(prose(anEvent('AskSubmitted', { query_text: 'why did it fall' }))).toBe(
      'asked “why did it fall”',
    )
    expect(prose(anEvent('ActionUndone', { action_kind: 'feature', target_id: 'c-1' }))).toBe(
      'undid feature on c-1',
    )
    expect(prose(anEvent('ActionRetried', { action_kind: 'extract', attempt_number: 3 }))).toBe(
      'retried extract, attempt 3',
    )
    expect(prose(anEvent('EmptyResultEncountered', { where: 'search', query_length: 12 }))).toBe(
      'nothing to show in search for a 12-character query',
    )
  })

  /** The exhaustiveness the `never` arm gives is a *compile-time* property and
   *  this cannot assert it -- a missing case is a build failure, proved by
   *  deleting one. What this asserts is the half a type cannot: that every arm
   *  actually produces a sentence, rather than falling through to an empty
   *  string a reader would read as an empty payload. */
  it('produces prose for every kind in the vocabulary', () => {
    for (const kind of INTERACTION_KINDS) {
      expect(prose(anEvent(kind)).trim(), kind).not.toBe('')
    }
  })

  it('is loud about a kind this build does not know, rather than blank', () => {
    render(<>{interactionProse(anEvent('SomethingNewer'))}</>)
    expect(screen.getByText(/unrecognised kind/)).toBeInTheDocument()
  })

  it('renders the part of a sentence it has when a field is missing', () => {
    expect(prose(anEvent('ViewExited', {}))).toBe('left project/catalog after —')
    expect(prose(anEvent('ActionUndone', { action_kind: 'feature' }))).toBe('undid feature')
  })
})
