import type { Meta, StoryObj } from '@storybook/react-vite'

import type { TextSummary } from '@domain/research/document.ts'
import { emptyExtractionQueue } from '@domain/research/extraction-queue.ts'
import { SourceId } from '@domain/shared/identifier.ts'

import { DocumentBrowser } from './DocumentBrowser.tsx'

/** The corpus, at the width the rail gives it.
 *
 * The width is the point of these stories rather than incidental. A document
 * title is long, the rail is 340px, and the row's height is measured rather
 * than assumed precisely because most titles wrap to two lines there — the bug
 * that produced rows drawing over each other. At 1200px none of that happens
 * and the story proves nothing.
 */
const meta = {
  title: 'research/DocumentBrowser',
  component: DocumentBrowser,
  parameters: { layout: 'fullscreen' },
  decorators: [
    (Story) => (
      <div
        style={{
          width: '340px',
          height: '420px',
          display: 'flex',
          flexDirection: 'column',
          border: '1px solid var(--line)',
          borderRadius: 'var(--radius)',
          background: 'var(--bg-panel)',
          padding: '10px 12px 12px',
        }}
      >
        <Story />
      </div>
    ),
  ],
} satisfies Meta<typeof DocumentBrowser>

export default meta

type Story = StoryObj<typeof meta>

const document = (index: number, over: Partial<TextSummary> = {}): TextSummary => ({
  sourceId: SourceId(`0000000${String(index)}-1111-2222-3333-444444444444`),
  title: `Spacing effects in long-term retention, part ${String(index)}`,
  kind: 'text',
  charCount: 18_400 + index * 137,
  derivedFrom: null,
  degradations: [],
  sha256: 'a'.repeat(64),
  uri: `https://example.org/papers/${String(index)}`,
  publishedAt: '2019-04-02',
  note: null,
  fetchedAt: null,
  droppedReason: null,
  extracted: false,
  ...over,
})

const DOCUMENTS: readonly TextSummary[] = [
  document(1),
  document(2, {
    title:
      'A very long title of the kind that wraps to two lines in a 340px rail and is exactly why rows are measured rather than assumed',
  }),
  document(3, {
    droppedReason: 'paywalled: only the abstract was reachable',
  }),
  ...Array.from({ length: 30 }, (_, index) => document(index + 4)),
]

const base = {
  documents: DOCUMENTS,
  total: DOCUMENTS.length,
  filter: '',
  onFilterChange: () => {},
  onOpen: () => {},
  queue: emptyExtractionQueue,
  extractableCount: DOCUMENTS.length - 1,
  queueSize: 0,
  busy: false,
  cancelling: false,
  onExtract: () => {},
  onExtractAll: () => {},
  onCancelExtraction: () => {},
  onAdd: () => {},
}

/** Thirty-three sources, of which the virtualizer draws the handful on
 *  screen. The third is dropped and stays in the list with its reason: the
 *  corpus keeps it as an audit trail, and hiding it would misreport what the
 *  project holds. */
export const Corpus: Story = { args: base }

/** A filter that matches nothing, against a corpus that is not empty. The
 *  component this replaced could not render this state at all — it returned
 *  early on an empty *fetch* and had no idea the filter existed. */
export const FilteredToNothing: Story = {
  args: { ...base, documents: [], filter: 'thermodynamics' },
}

/** Nothing stored yet. The filter box is gone with the list, deliberately:
 *  a search field over an empty corpus is a control with nothing to do. */
export const Empty: Story = {
  args: { ...base, documents: [], total: 0 },
}

/** Every extraction state a row can be in, at once and in one place.
 *
 * The first is running, the second queued, the fourth failed and the fifth
 * already extracted -- the third is the dropped one and deliberately offers no
 * control at all, because the server excludes dropped documents from
 * extract-all and a control here would promise an action it cannot honour.
 *
 * The failure's `detail` is on the row rather than behind anything, because
 * nothing durable records that an extraction was even requested: this string
 * lives only in the queue's memory and is the failure's one account of itself.
 */
export const Extracting: Story = {
  args: {
    ...base,
    queue: {
      running: DOCUMENTS[0]!.sourceId,
      queued: [DOCUMENTS[1]!.sourceId],
      finished: [
        {
          sourceId: DOCUMENTS[3]!.sourceId,
          status: 'failed',
          detail: 'the model refused: context length exceeded',
          entities: null,
          relationships: null,
        },
      ],
    },
    documents: DOCUMENTS.map((row, index) => (index === 4 ? { ...row, extracted: true } : row)),
    extractableCount: DOCUMENTS.length - 4,
    queueSize: 2,
  },
}
