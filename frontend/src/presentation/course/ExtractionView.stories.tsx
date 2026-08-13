import type { Meta, StoryObj } from '@storybook/react-vite'

import type { Extraction } from '@domain/knowledge/extraction.ts'

import { ExtractionView } from './ExtractionPane.tsx'

/** What an ingest looks like while it is happening, and after.
 *
 * The pane exists because a run can spend minutes inside one `remember` call,
 * and until it did the only honest thing the console could say about those
 * minutes was "extraction". So the state worth looking at is the middle one:
 * stages listed, the current one marked, counts that carry forward.
 *
 * `RunningOverLast` is here because it is the layout most likely to be wrong
 * and was the hardest to reach — a second ingest starting before anyone read
 * the result of the first needed two frame sequences over a live feed.
 */
const meta: Meta = {
  title: 'course/ExtractionView',
  parameters: { layout: 'padded' },
}

export default meta

type Story = StoryObj

const extraction = (over: Partial<Extraction> = {}): Extraction => ({
  sourceId: 'syllabus.pdf',
  stage: 'extracting',
  stages: [
    { stage: 'storing', detail: 'stored syllabus.pdf' },
    { stage: 'extracting', detail: 'chunk 9 of 24' },
  ],
  entities: 31,
  relationships: 12,
  domain: 'education',
  domainConfidence: 0.82,
  index: 9,
  total: 24,
  modelCalls: 9,
  merges: [],
  failed: false,
  ...over,
})

export const NothingYet: Story = {
  render: () => <ExtractionView current={null} last={null} />,
}

export const Running: Story = {
  render: () => <ExtractionView current={extraction()} last={null} />,
}

/** A fallback classification, not a confident one. `0` and `null` mean
 *  different things here and the pane has to keep them apart — a fallback
 *  presented as a decision is the misreading the field exists to prevent.
 *
 *  Consolidating rather than extracting like `Running`, and that is what makes
 *  it a story: the counts line is gated on `extracted` having *arrived*
 *  (`ExtractionPane.tsx`), and the shared fixture stops at `extracting`. So
 *  this story rendered byte-identical to `Running` — same six lines, no
 *  confidence anywhere on it — and the distinction it exists for was never on
 *  screen. Measured with `innerText` of `.extraction` on both.
 *
 *  The stage list is extended rather than the current stage moved back,
 *  because a list showing a step past the marked-current one is its own
 *  defect. */
export const RunningWithoutADomain: Story = {
  render: () => (
    <ExtractionView
      current={extraction({
        domain: null,
        domainConfidence: 0,
        stage: 'consolidating',
        stages: [
          { stage: 'storing', detail: 'stored syllabus.pdf' },
          { stage: 'extracting', detail: '24 of 24' },
          { stage: 'extracted', detail: '31 entities' },
          { stage: 'consolidating', detail: '9 of 24 considered' },
        ],
      })}
      last={null}
    />
  ),
}

export const Finished: Story = {
  render: () => (
    <ExtractionView
      current={null}
      last={extraction({
        stage: 'consolidated',
        stages: [
          { stage: 'storing', detail: 'stored syllabus.pdf' },
          { stage: 'extracting', detail: '24 of 24' },
          { stage: 'consolidating', detail: '31 entities considered' },
          { stage: 'consolidated', detail: 'stored' },
        ],
        index: 24,
        merges: [
          'spacing effect — merged into “spaced repetition” (same concept, different wording)',
          'Ebbinghaus — kept (distinct entity)',
        ],
      })}
    />
  ),
}

export const Failed: Story = {
  render: () => (
    <ExtractionView
      current={null}
      last={extraction({ stage: 'failed', failed: true, merges: [] })}
    />
  ),
}

/** One finished, one already going. Both sections render, and the reader has
 *  to be able to tell at a glance which is which. */
export const RunningOverLast: Story = {
  render: () => (
    <ExtractionView
      current={extraction({ sourceId: 'lecture-02.md', index: 2, total: 11 })}
      last={extraction({ stage: 'consolidated', index: 24 })}
    />
  ),
}
