import type { Meta, StoryObj } from '@storybook/react-vite'

import type { ForkNode, SessionSummary } from '@domain/session/session.ts'
import { ProjectId, SessionId } from '@domain/shared/identifier.ts'

import { ActivityChip } from './ProjectActivity.tsx'
import { SessionForest, SessionRow } from './SessionRow.tsx'
import { SkeletonRows } from './Skeletons.tsx'

/** A project's sessions, and the lineage that is the point of keeping them.
 *
 * **The ids differ in their first eight characters, and that is deliberate.**
 * `SessionRow` shows `shortId`, which is exactly those eight, and the first
 * draft of this file gave every fixture the same prefix -- so the gallery drew
 * five rows and one repeated id, teaching that the id column carries nothing.
 * Real ids are random and do not collide there. A fixture that makes a working
 * column look useless is worse than no fixture, and it was only visible by
 * screenshotting the page.
 *
 * `SessionForest` is the one place nesting survives on the landing page.
 * `SessionRow.tsx` argues why: inside one project the nesting is a
 * relationship between a handful of rows a reader can take in, where at the
 * top of the document it was the structure of everything and put this
 * morning's fork under a parent from March.
 *
 * Three rules these stories exist to keep checkable, all of them about a row
 * saying enough on its own:
 *
 * - **A session with no messages says so** rather than drawing an empty title.
 *   `row-title-empty` is a different class for that reason.
 * - **A fork says where it diverged**, as a chip, in the trail — not in a
 *   panel somebody has to open. A forked session's most useful fact is what
 *   it came from and at which event.
 * - **Failed turns and the held marker are chips, not colour on the row.** A
 *   row that turned red would be a row a reader has to interpret; a chip is a
 *   row a reader can read.
 *
 * `Skeletons` is here beside them deliberately, and it is the story to look at
 * after a layout change. Its whole claim is that a placeholder is the size of
 * what replaces it, and that claim was false until 2026-08-23 — 84px against a
 * 108px row. It is checked by `skeleton-height.browser.test.tsx` now, and this
 * is where it can be checked by eye.
 */
const meta: Meta = {
  title: 'tree/SessionForest',
}

export default meta

type Story = StoryObj

const PROJECT = ProjectId('11111111-1111-4111-8111-111111111111')

/** `Omit` before the intersection, which is not decoration. `Partial<SessionSummary>`
 *  already declares `id?: SessionId`, so intersecting it with `{ id: string }`
 *  yields `SessionId & string` and every literal id below is a type error. The
 *  branded-id types are doing their job; the helper has to stop fighting them. */
const session = (over: Omit<Partial<SessionSummary>, 'id'> & { id: string }): SessionSummary => ({
  projectId: PROJECT,
  startedAt: '2026-08-21T09:14:00Z',
  turns: 12,
  files: 4,
  firstMessage: 'map the tetrarchy onto the provinces it created',
  forkedFrom: null,
  forkedAt: null,
  failedTurns: null,
  ...over,
  id: SessionId(over.id),
})

const node = (s: SessionSummary, children: readonly ForkNode[] = []): ForkNode => ({
  ...s,
  children,
})

const Frame = ({ heading, children }: { heading: string; children: React.ReactNode }) => (
  <section style={{ padding: 'var(--space-3)', maxWidth: 720 }}>
    <h3 style={{ font: 'inherit', color: 'var(--fg-faint)', margin: '0 0 var(--space-2)' }}>
      {heading}
    </h3>
    {children}
  </section>
)

/** One row per state a session can be in, side by side.
 *
 *  The comparison is the story. Each of these looks fine alone; what has to be
 *  true is that a reader scanning the column can tell them apart without
 *  reading every word. */
export const EveryRowState: Story = {
  render: () => (
    <Frame heading="rows">
      <ul className="tree">
        {[
          session({ id: '7d41e0aa-1111-4111-8111-444444444444' }),
          session({
            id: 'b2c93f17-1111-4111-8111-555555555555',
            firstMessage: null,
            turns: 0,
            files: 0,
          }),
          session({
            id: '4e08ad5c-1111-4111-8111-666666666666',
            forkedFrom: SessionId('7d41e0aa-1111-4111-8111-444444444444'),
            forkedAt: 42,
          }),
          session({ id: 'c71b2d90-1111-4111-8111-777777777777', failedTurns: 3 }),
          session({
            id: '19f6e4b3-1111-4111-8111-888888888888',
            firstMessage:
              'a first message long enough that the row has to cut it off somewhere sensible rather than letting it push the id off the end of the line, which is what it did before the truncation existed',
          }),
        ].map((each) => (
          <li key={each.id}>
            <SessionRow session={each} />
          </li>
        ))}
      </ul>
    </Frame>
  ),
}

/** Two ordinary rows, and the story that used to be `Held`.
 *
 *  It drew one row with a `held` chip beside one without, on the argument that
 *  which session holds the project is a process fact the row is told rather
 *  than deduces. The argument stands and the chip is gone anyway: on the
 *  landing page the previewed row *is* the holder in the ordinary case, so the
 *  chip labelled the one session a reader was being shown with a word about
 *  lock ownership. Kept as a story, and kept under its old name, because it is
 *  what the gallery has that shows two sibling rows agreeing — a row that
 *  starts drawing state it should not is visible here and nowhere else. */
export const Held: Story = {
  render: () => (
    <Frame heading="two sibling rows, neither marked">
      <ul className="tree">
        <li>
          <SessionRow session={session({ id: '7d41e0aa-1111-4111-8111-444444444444' })} />
        </li>
        <li>
          <SessionRow session={session({ id: 'b2c93f17-1111-4111-8111-555555555555' })} />
        </li>
      </ul>
    </Frame>
  ),
}

/** Lineage three deep — a session, a fork of it, and a fork of that.
 *
 *  What to check: the indentation is legible at depth 3 and the fork chips
 *  read as a chain rather than as three unrelated rows that happen to be
 *  nested. This is the arrangement the whole component exists for. */
export const Lineage: Story = {
  render: () => (
    <Frame heading="a session and two generations of fork">
      <SessionForest
        nodes={[
          node(
            session({
              id: '7d41e0aa-1111-4111-8111-444444444444',
              firstMessage: 'map the tetrarchy onto the provinces it created',
            }),
            [
              node(
                session({
                  id: 'b2c93f17-1111-4111-8111-555555555555',
                  firstMessage: 'retry that, but keep Nicomedia separate',
                  forkedFrom: SessionId('7d41e0aa-1111-4111-8111-444444444444'),
                  forkedAt: 42,
                }),
                [
                  node(
                    session({
                      id: '4e08ad5c-1111-4111-8111-666666666666',
                      firstMessage: 'and now trace the Diocese boundaries',
                      forkedFrom: SessionId('b2c93f17-1111-4111-8111-555555555555'),
                      forkedAt: 61,
                      failedTurns: 1,
                    }),
                  ),
                ],
              ),
              node(
                session({
                  id: 'c71b2d90-1111-4111-8111-777777777777',
                  firstMessage: 'a second branch from the same point',
                  forkedFrom: SessionId('7d41e0aa-1111-4111-8111-444444444444'),
                  forkedAt: 42,
                }),
              ),
            ],
          ),
        ]}
      />
    </Frame>
  ),
}

/** The liveness marker, which is a chip and not a colour on the row.
 *
 *  Amber because that is what the event log already spends on tool activity,
 *  and a run *is* tool activity — the colour is borrowed rather than invented.
 *  `null` draws nothing at all, which is the common case and is why it is
 *  shown. */
export const Activity: Story = {
  render: () => (
    <Frame heading="activity">
      <div style={{ display: 'flex', gap: 'var(--space-2)', alignItems: 'center' }}>
        <ActivityChip label="extracting · 2m ago" />
        <ActivityChip label="authoring" />
        <ActivityChip label={null} />
        <span style={{ color: 'var(--fg-faint)' }}>← nothing is drawn for null</span>
      </div>
    </Frame>
  ),
}

/** The placeholder against the thing it replaces.
 *
 *  Four skeletons is what `ProjectList` draws while pending. The rule is that
 *  the page does not move when they are replaced, and it was broken until
 *  2026-08-23: the skeleton was 84px against a row estimated at 108.
 *  `skeleton-height.browser.test.tsx` holds the two together now; this is
 *  where the claim is visible. */
export const Skeletons: Story = {
  render: () => (
    <Frame heading="pending">
      <SkeletonRows count={4} />
    </Frame>
  ),
}
