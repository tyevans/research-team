import type { Meta, StoryObj } from '@storybook/react-vite'

import { EntityStatus } from './EntityStatus.tsx'

/** Every status the console shows, on one page.
 *
 * This is the story that does the work §5 of the component-system spec assigns
 * to a gallery: making the existing set answerable at a glance. The two rules
 * these encode are both ones the console currently gets wrong somewhere, and
 * both are the kind of rule that is easy to state in prose and impossible to
 * check without seeing them together —
 *
 * - **only `queue_empty` earns the good tone** among the six run endings, and
 * - **`human_gate` is a pause, not a failure.**
 *
 * `RunEndings` is where to look: five of the six should read as "something
 * needs you", and exactly one as "finished".
 */
const meta: Meta = {
  title: 'entity/EntityStatus',
}

export default meta

type Story = StoryObj

const Set = ({ title, statuses }: { title: string; statuses: readonly string[] }) => (
  <section style={{ padding: 'var(--space-3)' }}>
    <h3 style={{ font: 'inherit', color: 'var(--fg-dim)', margin: '0 0 var(--space-2)' }}>
      {title}
    </h3>
    <div style={{ display: 'flex', gap: 'var(--space-2)', flexWrap: 'wrap' }}>
      {statuses.map((status) => (
        <EntityStatus key={status} status={status} />
      ))}
    </div>
  </section>
)

/** The five topic statuses. `not_pursuing` and `superseded` are both "done
 *  with" rather than "done", so neither is green — a closed topic that reads
 *  as answered is a queue that lies about what it achieved. */
export const TopicStatuses: Story = {
  render: () => (
    <Set
      title="topic"
      statuses={['open', 'investigating', 'answered', 'not_pursuing', 'superseded']}
    />
  ),
}

/** A dispatch's five. `failed` is the only red one, and it is the only one a
 *  reader has to do something about. */
export const DispatchStatuses: Story = {
  render: () => (
    <Set title="dispatch" statuses={['queued', 'running', 'done', 'cancelled', 'failed']} />
  ),
}

/** The six run endings, which is the set the rule is about. One green.
 *  `human_gate` reads "needs a person" rather than showing its identifier, and
 *  is toned as a pause rather than as a fault. */
export const RunEndings: Story = {
  render: () => (
    <Set
      title="run ending"
      statuses={['queue_empty', 'budget_exhausted', 'human_gate', 'stalled', 'error', 'cancelled']}
    />
  ),
}

/** A failure with its reason beside it, as text.
 *
 *  `DispatchChip` puts this in a `title` today, which is not keyboard
 *  reachable, not available on touch and inconsistently announced — nine
 *  instances of that pattern are counted in the session report alone. The
 *  reason truncates rather than pushing the status off the row. */
export const WithAReason: Story = {
  render: () => (
    <div style={{ padding: 'var(--space-3)', display: 'flex', gap: 'var(--space-2)' }}>
      <EntityStatus status="failed" detail="model returned no content" />
      <EntityStatus
        status="failed"
        detail="a reason long enough that it has to be cut off somewhere sensible"
      />
    </div>
  ),
}

/** A status this build has never heard of. Neutral, not red: a backend that
 *  grew a status should not make a queue look broken. */
export const UnknownStatus: Story = {
  render: () => <Set title="unknown" statuses={['from_a_newer_backend']} />,
}
