import type { Meta, StoryObj } from '@storybook/react-vite'

import type { Approval } from '@domain/approval/approval.ts'
import { ApprovalId, SessionId } from '@domain/shared/identifier.ts'

import { Approvals } from './Approvals.tsx'

/** Gated calls waiting on a person, and the rule that a decision is never
 *  hidden.
 *
 * **Every decision is named on every card, including the ones this gate will
 * not take.** A tool gate allows approve/edit/reject; a stage gate also allows
 * respond. Hiding the excluded one would make the console's vocabulary depend
 * on server state that nothing on screen reports — a reader sees three
 * controls here and four there, and has no way to tell whether the fourth is
 * missing, broken, or was never a thing. `Approvals.tsx` files that under
 * "empty is not the same as unavailable".
 *
 * So an unavailable decision renders **disabled, by name, with its reason
 * beside it** — and `disabled` rather than `aria-disabled`, because there is
 * genuinely nothing to do with it, so it should not take focus. The reason is
 * a real element joined by `aria-describedby`, so a screen-reader user gets
 * the explanation the sighted reader gets rather than a silently dead button.
 *
 * `AToolGate` and `AStageGate` are that rule. Both must show four controls.
 * Only one of them has four *live* ones.
 *
 * The other thing worth seeing: **`edit` and `respond` are modes, not
 * buttons that post.** Neither means anything without a payload — an `edit`
 * with no arguments re-runs the call the reviewer was objecting to, and a
 * `respond` with no message invents a tool result. A bare button for either
 * would look like it did something and do the wrong thing.
 */
const meta: Meta = {
  title: 'session/Approvals',
}

export default meta

type Story = StoryObj

const SESSION = SessionId('7d41e0aa-1111-4111-8111-444444444444')

/** `Omit` before the intersection, for the reason `SessionForest.stories.tsx`
 *  records: `Partial<Approval>` already declares `id?: ApprovalId`, so
 *  intersecting it with `{ id: string }` yields `ApprovalId & string` and
 *  every literal id below is a type error. Second time in this series, so it
 *  is an idiom rather than an accident -- a fixture helper that takes a raw
 *  string for a branded id has to drop the branded one first. */
const approval = (over: Omit<Partial<Approval>, 'id'> & { id: string }): Approval => ({
  sessionId: SESSION,
  toolName: 'fetch',
  description: 'Fetch a page from the open web',
  args: { url: 'https://en.wikipedia.org/wiki/Tetrarchy', timeout: 30 },
  allowedDecisions: ['approve', 'edit', 'reject'],
  context: null,
  ...over,
  id: ApprovalId(over.id),
})

const map = (...items: readonly Approval[]) =>
  new Map(items.map((item) => [item.id, item] as const))

const Frame = ({ heading, children }: { heading: string; children: React.ReactNode }) => (
  <section style={{ padding: 'var(--space-3)', maxWidth: 720 }}>
    <h3 style={{ font: 'inherit', color: 'var(--fg-faint)', margin: '0 0 var(--space-2)' }}>
      {heading}
    </h3>
    {children}
  </section>
)

/** **A tool gate: `respond` is named and disabled, not absent.**
 *
 *  Read against `AStageGate`. Four controls on both, and the fourth here
 *  carries the server's own reason — answering on the tool's behalf invents a
 *  result, and the log is supposed to record what actually happened. */
export const AToolGate: Story = {
  render: () => (
    <Frame heading="a tool gate — three decisions allowed, four shown">
      <Approvals
        approvals={map(approval({ id: 'ap-1' }))}
        deciding={null}
        onDecide={() => undefined}
      />
    </Frame>
  ),
}

/** A stage gate, which takes all four.
 *
 *  The comparison is the whole point: a reader who has seen only one of these
 *  cannot tell a disabled control from a missing one, and that is the
 *  confusion the fixed list exists to prevent. */
export const AStageGate: Story = {
  render: () => (
    <Frame heading="a stage gate — all four allowed">
      <Approvals
        approvals={map(
          approval({
            id: 'ap-2',
            toolName: 'advance_stage',
            description: 'Leave the Framing stage and begin Drafting',
            args: { from: 'step1.framing', to: 'step2.drafting' },
            allowedDecisions: ['approve', 'edit', 'reject', 'respond'],
            context: {
              stage: 'step1.framing',
              findingsArtifact: 'course/framing/findings.json',
              artifactPaths: ['course/framing/outline.md', 'course/framing/objectives.md'],
              blocked: true,
              artifactsReviewed: 2,
              linksReviewed: 4,
              unimplementedChecks: ['outline.reading_level'],
              unreadableArtifacts: [],
              findings: [
                {
                  check: 'outline.section_count',
                  severity: 'blocking',
                  message: 'The outline has two sections; the preset asks for at least four.',
                  cites: ['course/framing/outline.md'],
                  suggestedEdit: null,
                },
              ],
            },
          }),
        )}
        deciding={null}
        onDecide={() => undefined}
      />
    </Frame>
  ),
}

/** Both, one above the other, which is the only arrangement the rule can be
 *  judged in — a card alone always looks complete. */
export const BothGates: Story = {
  render: () => (
    <Frame heading="both — four controls each, different numbers live">
      <Approvals
        approvals={map(
          approval({ id: 'ap-1' }),
          approval({
            id: 'ap-2',
            toolName: 'advance_stage',
            description: 'Leave the Framing stage and begin Drafting',
            args: { from: 'step1.framing', to: 'step2.drafting' },
            allowedDecisions: ['approve', 'edit', 'reject', 'respond'],
          }),
        )}
        deciding={null}
        onDecide={() => undefined}
      />
    </Frame>
  ),
}

/** A decision in flight. Everything is busy, and the accent stays on
 *  `Approve` — it is still the action, it is simply momentarily unavailable,
 *  and there is no other live control to move it to. */
export const Deciding: Story = {
  render: () => (
    <Frame heading="a decision in flight">
      <Approvals
        approvals={map(approval({ id: 'ap-1' }))}
        deciding={ApprovalId('ap-1')}
        onDecide={() => undefined}
      />
    </Frame>
  ),
}

/** Several at once, which is what an unattended run produces. */
export const Several: Story = {
  render: () => (
    <Frame heading="three waiting">
      <Approvals
        approvals={map(
          approval({ id: 'ap-1' }),
          approval({
            id: 'ap-3',
            toolName: 'write_file',
            description: 'Write into the session workspace',
            args: { path: 'course/framing/outline.md', bytes: 4210 },
          }),
          approval({
            id: 'ap-4',
            toolName: 'shell',
            description: null,
            args: { command: 'uv run pytest -q' },
          }),
        )}
        deciding={null}
        onDecide={() => undefined}
      />
    </Frame>
  ),
}

/** Nothing waiting. The container draws, empty — this component is rendered
 *  by a bar that decides for itself whether to appear, so an empty map here is
 *  a normal frame rather than a state to dress. */
export const NothingWaiting: Story = {
  render: () => (
    <Frame heading="nothing waiting">
      <Approvals approvals={map()} deciding={null} onDecide={() => undefined} />
    </Frame>
  ),
}
