import type { Meta, StoryObj } from '@storybook/react-vite'

import type { Dispatch } from '@domain/research/dispatch.ts'
import { focusCounts, type TopicView } from '@domain/research/topic.ts'
import { TopicId } from '@domain/shared/identifier.ts'

import { TopicQueue } from './TopicQueue.tsx'

/** The topic queue in the states it actually reaches.
 *
 * Every one of these was unreachable in a workbench until the fetching moved
 * out: the component that drew a failed dispatch also asked the server for
 * one. That is the argument for the split in one sentence — "a failed
 * dispatch, clamped, beside a queued one" is now a thing you can look at
 * rather than a thing you arrange by breaking a server.
 *
 * Rendered in a 340px box, which is the width the rail actually gives it.
 * A queue story at 1200px is a queue nobody sees.
 */
const meta = {
  title: 'research/TopicQueue',
  component: TopicQueue,
  parameters: { layout: 'fullscreen' },
  decorators: [
    (Story) => (
      <div
        style={{
          width: '340px',
          height: '520px',
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
} satisfies Meta<typeof TopicQueue>

export default meta

type Story = StoryObj<typeof meta>

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

const TOPICS: readonly TopicView[] = [
  topic({ topicId: TopicId('11111111-1111-1111-1111-111111111111'), isBlocked: true }),
  topic({
    topicId: TopicId('22222222-2222-2222-2222-222222222222'),
    question: 'Does spacing interact with sleep, or only with elapsed time?',
    needsAttention: true,
    triggers: ['two findings disagree'],
  }),
  topic({
    topicId: TopicId('33333333-3333-3333-3333-333333333333'),
    question: 'What is the smallest interval that still shows an effect?',
    status: 'open',
    sources: 0,
    findings: 0,
    openSubQuestions: 0,
  }),
  topic({
    topicId: TopicId('44444444-4444-4444-4444-444444444444'),
    question: 'Was the 2019 replication pre-registered?',
    status: 'answered',
    openSubQuestions: 0,
  }),
  topic({
    topicId: TopicId('55555555-5555-5555-5555-555555555555'),
    question: 'Should the lesson cover massed practice at all?',
    status: 'not_pursuing',
    openSubQuestions: 0,
  }),
]

const dispatch = (over: Partial<Dispatch> = {}): Dispatch => ({
  dispatchId: 'd1',
  topicId: '11111111-1111-1111-1111-111111111111',
  action: 'understanding',
  status: 'running',
  question: null,
  position: null,
  path: null,
  sessionId: null,
  detail: null,
  ...over,
})

const base = {
  topics: TOPICS,
  counts: focusCounts(TOPICS),
  focus: 'all' as const,
  search: '',
  dispatches: new Map<string, Dispatch>(),
  running: false,
  queuedCount: 0,
  dispatching: false,
  stopping: false,
  onFocusChange: () => {},
  onSearchChange: () => {},
  onDispatch: () => {},
  onManage: () => {},
  onStop: () => {},
}

/** The ordinary case: a queue with work in it, nothing dispatched. */
export const Queue: Story = { args: base }

/** The third row has no sources and no findings, so its one verb is disabled
 *  with a reason. The only disabled control in this feature, and the argument
 *  for it is in `TopicQueue`'s own comment: synthesising from nothing produces
 *  the model's prior knowledge presented as project findings. */
export const NothingToSynthesise: Story = {
  args: { ...base, focus: 'live', topics: [TOPICS[2]!], counts: focusCounts([TOPICS[2]!]) },
}

/** Four dispatches at once, which is what the chip set is for. The failure is
 *  the row that matters: it is clamped to the meta line rather than given a
 *  line of its own, so a model error that runs to a paragraph cannot push the
 *  rest of the queue off the screen. Its full text is in the `title`. */
export const Dispatched: Story = {
  args: {
    ...base,
    running: true,
    queuedCount: 2,
    dispatches: new Map<string, Dispatch>([
      ['11111111-1111-1111-1111-111111111111', dispatch()],
      [
        '22222222-2222-2222-2222-222222222222',
        dispatch({ dispatchId: 'd2', status: 'queued', position: 1 }),
      ],
      [
        '44444444-4444-4444-4444-444444444444',
        dispatch({
          dispatchId: 'd3',
          status: 'failed',
          detail:
            'the model returned a citation for a source this project does not hold, twice in a row',
        }),
      ],
      [
        '55555555-5555-5555-5555-555555555555',
        dispatch({ dispatchId: 'd4', status: 'done', path: 'understanding/spacing.md' }),
      ],
    ]),
  },
}

/** The queue has work in it and the filter is hiding all of it. Distinct from
 *  the story below, and the distinction is the whole reason `counts` is passed
 *  separately from `topics`. */
export const FilteredToNothing: Story = {
  args: { ...base, topics: [], search: 'sleep deprivation in pilots', focus: 'closed' },
}

/** Nothing has been seeded. The counts are all zero, which is how the queue
 *  knows to say this rather than "no topics match". */
export const Empty: Story = {
  args: { ...base, topics: [], counts: focusCounts([]) },
}
