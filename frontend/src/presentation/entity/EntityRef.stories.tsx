import type { Meta, StoryObj } from '@storybook/react-vite'

import type { EntityHead } from '@domain/entity/entity-head.ts'

import { EntityRef } from './EntityRef.tsx'

/** One component for a job this console currently does seven ways.
 *
 * The stories are deliberately a *comparison* rather than a demonstration:
 * side by side, `held by 3f2a1b9c` and `apollo` should read as the same kind
 * of thing said with different amounts of knowledge — which is the property
 * the seven existing spellings do not have. `Named` against `Unnamed` is the
 * one to look at, because the fallback being visible is the only behaviour
 * change in this component.
 */
const meta: Meta = {
  title: 'entity/EntityRef',
}

export default meta

type Story = StoryObj

const project: EntityHead = {
  kind: 'project',
  id: '3f2a1b9c-1111-2222-3333-444444444444',
  label: 'apollo',
}
const session: EntityHead = {
  kind: 'session',
  id: '7d41e0aa-1111-2222-3333-444444444444',
  label: null,
}
const topic: EntityHead = {
  kind: 'topic',
  id: '22222222-1111-2222-3333-444444444444',
  label: 'Who funded the study, and did they see it before publication?',
}

const Row = ({ label, children }: { label: string; children: React.ReactNode }) => (
  <div style={{ display: 'flex', gap: 'var(--space-4)', padding: 'var(--space-2)' }}>
    <code style={{ color: 'var(--fg-faint)', width: '18ch', flex: '0 0 auto' }}>{label}</code>
    {children}
  </div>
)

/** The name, when the caller already knows it. */
export const Named: Story = {
  render: () => <Row label="label set">{<EntityRef head={project} />}</Row>,
}

/** No name, so the short id — in monospace, so it does not pass for one.
 *  A session has no name on the wire and never will; this is the honest
 *  rendering rather than a placeholder. */
export const Unnamed: Story = {
  render: () => <Row label="label null">{<EntityRef head={session} />}</Row>,
}

/** The two together, which is the comparison worth having on a gallery page:
 *  a reader should be able to tell at a glance which of these the console
 *  knows the name of. */
export const NamedAndUnnamed: Story = {
  render: () => (
    <>
      <Row label="project">{<EntityRef head={project} />}</Row>
      <Row label="session">{<EntityRef head={session} />}</Row>
    </>
  ),
}

/** With the word that makes it a sentence. Prefix and name are one element so
 *  they cannot wrap into two fragments that read as unrelated. */
export const WithPrefix: Story = {
  render: () => (
    <>
      <Row label="held by">{<EntityRef head={session} prefix="held by" />}</Row>
      <Row label="forked from">{<EntityRef head={session} prefix="forked from" />}</Row>
    </>
  ),
}

/** A link, which is what gives back ⌘-click, middle-click, copy-link and the
 *  status-bar preview — none of which this console has today, because every
 *  navigation is a button calling `navigate()`. */
export const AsALink: Story = {
  render: () => <Row label="href set">{<EntityRef head={project} href="/project/3f2a1b9c" />}</Row>,
}

/** A topic's label is a sentence, and it truncates by CSS rather than by
 *  slicing the string — a sliced string cannot be recovered for a `title`, and
 *  a question is exactly the thing a reader hovers to read in full.
 *
 *  Worth opening in a browser: the truncation is the only part of this
 *  component jsdom cannot see. */
export const LongLabelInANarrowRail: Story = {
  render: () => (
    <div style={{ width: '220px', border: '1px dashed var(--line)' }}>
      <Row label="topic">{<EntityRef head={topic} />}</Row>
    </div>
  ),
}
