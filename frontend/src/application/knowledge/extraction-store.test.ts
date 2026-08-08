import { expect, it, vi } from 'vitest'

import { ProjectId } from '@domain/shared/identifier.ts'

import { createExtractionStore } from './extraction-store.ts'

const PROJECT = ProjectId('11111111-1111-1111-1111-111111111111')
const OTHER = ProjectId('99999999-9999-9999-9999-999999999999')

const frame = (over: Record<string, unknown> = {}) => ({
  type: 'Extraction',
  project_id: PROJECT,
  source_id: 'notes',
  stage: 'extracting',
  detail: '',
  entities: null,
  relationships: null,
  domain: null,
  domain_confidence: null,
  index: null,
  total: null,
  model_calls: null,
  ...over,
})

const store = (extractions = { on: vi.fn().mockResolvedValue({ current: [], last: [] }) }) =>
  createExtractionStore({ extractions, projectId: PROJECT })

it('folds a frame for this project', () => {
  const extraction = store()
  extraction.getState().handleFrame(frame({ stage: 'storing' }))

  expect(extraction.getState().current?.stage).toBe('storing')
})

it('ignores a frame for another project', () => {
  // The SSE connection is global — every project's frames arrive here.
  // Folding another project's extraction would show one course's work on
  // another's page.
  const extraction = store()
  extraction.getState().handleFrame(frame({ project_id: OTHER, stage: 'storing' }))

  expect(extraction.getState().current).toBeNull()
})

it('ignores frames that are not extraction frames', () => {
  const extraction = store()
  extraction.getState().handleFrame({ type: 'TurnActivity', session_id: 'x' })

  expect(extraction.getState().current).toBeNull()
})

it('ignores an extraction frame whose fields do not parse', () => {
  // `type: 'Extraction'` alone is not enough to fold: the frame arrives off an
  // unvalidated socket, and a half-shaped one would otherwise fold `undefined`
  // into the counts and render as progress that never happened.
  const extraction = store()
  extraction.getState().handleFrame({ type: 'Extraction', project_id: PROJECT })

  expect(extraction.getState().current).toBeNull()
})

it('moves a finished extraction to last and clears current', () => {
  const extraction = store()
  extraction.getState().handleFrame(frame({ stage: 'extracting' }))
  extraction.getState().handleFrame(frame({ stage: 'consolidated', entities: 2 }))

  expect(extraction.getState().current).toBeNull()
  expect(extraction.getState().last?.entities).toBe(2)
})

it('keeps a failed extraction as the last one', () => {
  const extraction = store()
  extraction.getState().handleFrame(frame({ stage: 'failed', detail: 'the model refused' }))

  expect(extraction.getState().last?.failed).toBe(true)
})

it('starts a new extraction when the source changes', () => {
  const extraction = store()
  extraction.getState().handleFrame(frame({ source_id: 'first', stage: 'extracting' }))
  extraction.getState().handleFrame(frame({ source_id: 'second', stage: 'storing' }))

  expect(extraction.getState().current?.sourceId).toBe('second')
  expect(extraction.getState().current?.stages.map((s) => s.stage)).toEqual(['storing'])
})

it('rebuilds from the catch-up route after a reconnect', async () => {
  // The frames carry no feed position, so this is the only recovery path.
  const extractions = {
    on: vi.fn().mockResolvedValue({
      current: [frame({ stage: 'consolidating', index: 3, total: 9 })],
      last: [],
    }),
  }
  const extraction = store(extractions)

  await extraction.getState().catchUp()

  expect(extractions.on).toHaveBeenCalledWith(PROJECT)
  expect(extraction.getState().current?.index).toBe(3)
})
