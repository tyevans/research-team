import type { Meta, StoryObj } from '@storybook/react-vite'

import type { TopicDetail as TopicDetailView, TopicView } from '@domain/research/topic.ts'
import { TopicId } from '@domain/shared/identifier.ts'

import { TopicDetail } from './TopicDetail.tsx'
import { TopicRow } from './TopicRow.tsx'

/** One entity, two densities, on one page — which is the comparison the
 *  console cannot currently make.
 *
 * A topic's question was rendered as `<div className="topic-question">` in the
 * queue and as `<h3 className="drawer-title">` in the manage panel: the
 * `Drawer` component's own heading class, in a file that did not use `Drawer`.
 * The two markups shared **no class name at all**. Both have since moved —
 * the row's class is `.ent-topic-question` and `TopicManagePane`'s heading is
 * utilities — so the specific mismatch is gone and the reason it argued for is
 * not: putting `Row` and `Detail` beside each other is what makes "these are
 * the same entity at two densities" a thing you can see rather than a thing
 * you assert.
 *
 * `Detail` is also where the gap R-F3.10 found is closed: `rationale`,
 * `scope`, `sourceIds`, `findingNotes` and `contested` are all fetched by
 * `TopicManagePane` today and rendered nowhere in the console — this workbench
 * is the only place they are drawn at all, because nothing mounts `Detail`
 * yet.
 */
const meta: Meta = {
  title: 'entity/Topic',
  parameters: { layout: 'fullscreen' },
}

export default meta

type Story = StoryObj

const topic = (over: Partial<TopicView> = {}): TopicView => ({
  topicId: TopicId('22222222-1111-2222-3333-444444444444'),
  question: 'Who funded the study, and did they see it before publication?',
  status: 'investigating',
  sources: 4,
  findings: 2,
  openSubQuestions: 1,
  triggers: [],
  needsAttention: false,
  isBlocked: false,
  ...over,
})

const detail = (over: Partial<TopicDetailView> = {}): TopicDetailView => ({
  ...topic(),
  rationale: 'A funder who reviewed the draft is a conflict the conclusion has to be read against.',
  scope: 'A named funder, with a citation, and whether they saw a pre-publication draft.',
  subQuestions: [
    { key: 'a', question: 'Which grant number?', answer: 'NIH R01-99213', resolved: true },
    {
      key: 'b',
      question: 'Was there a pre-publication review clause?',
      answer: null,
      resolved: false,
    },
  ],
  sourceIds: ['doc-7', 'doc-9', 'doc-31'],
  findingNotes: [
    'Two of the three authors declare the same grant.',
    'The acknowledgements name a reviewer employed by the funder.',
  ],
  contested: false,
  ...over,
})

const Queue = ({ children }: { children: React.ReactNode }) => (
  <ul style={{ margin: 0, padding: 0, width: '360px', borderRight: '1px solid var(--line)' }}>
    {children}
  </ul>
)

/** The queue, in a rail the width it actually gets. Every row is the same
 *  height regardless of how long its question is — the contract a virtualizer
 *  estimates against, and the one L-F8 records a 122px hole for breaking.
 *
 *  **Worth opening in a browser**: the clamp is CSS, so jsdom can only assert
 *  that a long question produces no extra elements. */
export const Rows: Story = {
  render: () => (
    <Queue>
      <TopicRow
        topic={topic()}
        href="#a"
        slots={{ primary: <button type="button">Synthesise</button> }}
      />
      {/* The row as `TopicQueue` actually hands it over: a chip reporting a
          dispatch, one verb, and the rest behind a `⋯`. Worth opening at the
          340px this is drawn at rather than reading here -- the whole of #40
          was that this chip began 1.5px before the clip edge and was painted
          nowhere, which is invisible in the markup and obvious on screen. */}
      <TopicRow
        topic={topic({ question: 'What does the 2019 replication actually replicate?' })}
        href="#d"
        slots={{
          // The utility strings `TopicQueue`'s `DispatchChip` writes, copied
          // rather than imported — `CHIP` is that component's private dressing,
          // and a story that imported it would stop being a *sample* of the
          // markup and start being a second renderer of it. The same call
          // `Tooltip.stories.tsx` made in slice 3a, and the reason it is made
          // again here: this line held `.topic-dispatch`, and `research.css`
          // is deleted later in this slice, so leaving it would put an
          // undressed chip in the workbench with nothing failing.
          note: (
            <span className="inline-block max-w-[18ch] flex-none overflow-hidden align-middle font-mono text-xs text-ellipsis whitespace-nowrap text-accent">
              ⟳ understanding · running
            </span>
          ),
          primary: <button type="button">Synthesise</button>,
          overflow: [{ key: 'manage', label: 'Manage', onSelect: () => {} }],
        }}
      />
      <TopicRow
        topic={topic({ question: 'Short one?', status: 'open', sources: 0, findings: 0 })}
        href="#b"
      />
      <TopicRow topic={topic({ status: 'answered', openSubQuestions: 0 })} href="#c" />
    </Queue>
  ),
}

/** The three conditions a queue is scanned for, in the order they outrank each
 *  other. A topic that is blocked *and* closed is blocked: dimming it as
 *  closed is how it stops being noticed. */
export const RowStates: Story = {
  render: () => (
    <Queue>
      <TopicRow topic={topic({ isBlocked: true, question: 'Blocked: waiting on a person.' })} />
      <TopicRow topic={topic({ needsAttention: true, question: 'Flagged: something changed.' })} />
      <TopicRow topic={topic({ status: 'superseded', question: 'Closed: superseded.' })} />
      <TopicRow topic={topic({ question: 'Selected.' })} selected />
    </Queue>
  ),
}

/** A row with nothing to offer, which is the common case: no verb, no link.
 *  The row renders no empty chrome for the affordances it was not given. */
export const RowWithNoAffordances: Story = {
  render: () => (
    <Queue>
      <TopicRow topic={topic()} />
    </Queue>
  ),
}

/** The detail, with everything `TopicManagePane` fetches and does not show. */
export const Detail: Story = {
  render: () => (
    <div style={{ maxWidth: '640px' }}>
      <TopicDetail topic={detail()} />
    </div>
  ),
}

/** A topic nobody has written a rationale or a scope for. The headings are
 *  absent rather than empty: "Why this is being asked" over nothing reads as a
 *  field that failed to load. */
export const DetailWithNothingRecorded: Story = {
  render: () => (
    <div style={{ maxWidth: '640px' }}>
      <TopicDetail
        topic={detail({
          rationale: '',
          scope: '',
          findings: 0,
          findingNotes: [],
          sourceIds: [],
          subQuestions: [],
          openSubQuestions: 0,
          status: 'open',
        })}
      />
    </div>
  ),
}

/** Contested, blocked, and with the triggers that say why. This is the state
 *  a reader most needs the detail for and the one the queue can only hint
 *  at. */
export const DetailNeedingAttention: Story = {
  render: () => (
    <div style={{ maxWidth: '640px' }}>
      <TopicDetail
        topic={detail({
          contested: true,
          isBlocked: true,
          needsAttention: true,
          triggers: ['two findings disagree about the grant number'],
        })}
      />
    </div>
  ),
}

/** Both densities side by side — the comparison this gallery exists for. */
export const RowAndDetail: Story = {
  render: () => (
    <div style={{ display: 'flex', gap: 'var(--space-4)' }}>
      <Queue>
        <TopicRow topic={topic()} href="#a" selected />
      </Queue>
      <div style={{ maxWidth: '560px' }}>
        <TopicDetail topic={detail()} />
      </div>
    </div>
  ),
}
