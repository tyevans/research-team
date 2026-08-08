import { describe, expect, it } from 'vitest'

import {
  applyNote,
  emptyExtraction,
  isExtractionFrame,
  type ExtractionFrame,
} from './extraction.ts'

const frame = (over: Partial<ExtractionFrame> = {}): ExtractionFrame => ({
  type: 'Extraction',
  projectId: '11111111-1111-1111-1111-111111111111',
  sourceId: 'notes',
  stage: 'extracting',
  detail: '',
  entities: null,
  relationships: null,
  domain: null,
  domainConfidence: null,
  index: null,
  total: null,
  modelCalls: null,
  ...over,
})

describe('applyNote', () => {
  it('records each stage once, in arrival order', () => {
    let extraction = emptyExtraction('notes')
    extraction = applyNote(extraction, frame({ stage: 'storing' }))
    extraction = applyNote(extraction, frame({ stage: 'extracting' }))
    extraction = applyNote(extraction, frame({ stage: 'extracting', modelCalls: 2 }))

    expect(extraction.stages.map((entry) => entry.stage)).toEqual(['storing', 'extracting'])
    expect(extraction.stage).toBe('extracting')
    expect(extraction.modelCalls).toBe(2)
  })

  it('keeps the counts and the schema from the extracted note', () => {
    const extraction = applyNote(
      emptyExtraction('notes'),
      frame({
        stage: 'extracted',
        entities: 12,
        relationships: 30,
        domain: 'psychology',
        domainConfidence: 0.87,
      }),
    )

    expect(extraction.entities).toBe(12)
    expect(extraction.relationships).toBe(30)
    expect(extraction.domain).toBe('psychology')
    expect(extraction.domainConfidence).toBe(0.87)
  })

  it('keeps a zero confidence distinct from an absent one', () => {
    // 0.0 means the classifier gave up and fell back. Rendering that as
    // "no classifier ran" would present a fallback as a decision.
    const gaveUp = applyNote(
      emptyExtraction('notes'),
      frame({ stage: 'extracted', domain: 'psychology', domainConfidence: 0 }),
    )
    const neverRan = applyNote(
      emptyExtraction('notes'),
      frame({ stage: 'extracted', domain: 'psychology' }),
    )

    expect(gaveUp.domainConfidence).toBe(0)
    expect(neverRan.domainConfidence).toBeNull()
  })

  it('collects consolidation progress and the merges it reports', () => {
    let extraction = emptyExtraction('notes')
    extraction = applyNote(
      extraction,
      frame({ stage: 'consolidating', index: 1, total: 2, detail: 'Ada Lovelace' }),
    )
    extraction = applyNote(
      extraction,
      frame({
        stage: 'consolidating',
        index: 1,
        total: 2,
        detail: 'Ada Lovelace absorbed Ada -- name and structure agree',
      }),
    )

    expect(extraction.index).toBe(1)
    expect(extraction.total).toBe(2)
    expect(extraction.merges).toHaveLength(2)
    expect(extraction.merges[1]).toContain('absorbed')
  })

  it('marks a failure and keeps why', () => {
    const extraction = applyNote(
      emptyExtraction('notes'),
      frame({ stage: 'failed', detail: 'the model refused' }),
    )

    expect(extraction.failed).toBe(true)
    expect(extraction.stages.at(-1)?.detail).toBe('the model refused')
  })
})

describe('isExtractionFrame', () => {
  it('accepts an extraction frame and rejects anything else', () => {
    expect(isExtractionFrame({ type: 'Extraction' })).toBe(true)
    expect(isExtractionFrame({ type: 'TurnActivity' })).toBe(false)
    expect(isExtractionFrame(null)).toBe(false)
  })
})
