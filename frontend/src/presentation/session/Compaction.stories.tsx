import { useState } from 'react'
import type { Meta, StoryObj } from '@storybook/react-vite'

import type { Message } from '@domain/conversation/message.ts'

import { Compaction } from './Compaction.tsx'

/** What the model is shown, against what the log still holds.
 *
 * `Compaction.tsx` puts the whole feature in one sentence: **"Nothing was
 * deleted — the log still holds every message, and so does this pane. What
 * changed is what the *model* is shown."**
 *
 * That distinction lives entirely in the wording, which is why it is worth a
 * page. Three sentences carry it, and each would be a lie in the obvious
 * wrong build:
 *
 * - "context compacted — the model sees a summary of the first N messages"
 * - "N superseded messages — **still in the log, not sent to the model**"
 * - "context boundary · everything below is sent **verbatim**"
 *
 * A build that said "N messages removed" would describe a data model this
 * project does not have, and would do it convincingly. The superseded messages
 * being *expandable, right there* is the proof the pane offers, which is why
 * `Superseded` opens that fold.
 *
 * **The two folds default differently, on purpose.** The summary is open and
 * the superseded messages are closed: show what the model sees, and keep what
 * it does not out of the way until asked. The summary's key is inverted —
 * `compaction:summary:closed`, so an empty set means open — which is the same
 * trick `AgentWidget` uses and for the same reason: the store's default is an
 * empty set, and the desired default is open.
 */
const meta: Meta = {
  title: 'session/Compaction',
}

export default meta

type Story = StoryObj

const message = (role: Message['role'], content: string): Message => ({
  role,
  content,
  toolCalls: [],
  name: null,
  artifact: null,
  isError: false,
})

const HIDDEN: readonly Message[] = [
  message('user', 'Start from the tetrarchy and work outward.'),
  message('assistant', 'Diocletian divided rule between two Augusti and two Caesars in 293.'),
  message('user', 'Which provinces did that create?'),
  message('assistant', 'None directly — the provincial subdivision was a separate reform.'),
  message('user', 'Show me the sources.'),
  message('assistant', 'Three of the eight documents in the corpus mention it.'),
]

const SUMMARY =
  'The reader is tracing the tetrarchy’s administrative consequences. Established so far: rule was divided in 293 between two Augusti and two Caesars; the provincial subdivision was a separate reform; three corpus documents bear on it.'

/** Holds the fold state, so the disclosures actually open in the gallery.
 *
 *  A `Set` rather than a boolean pair, because that is what the pane takes —
 *  the session view owns one set of open keys for every fold on the page, so a
 *  story that invented two booleans would be showing a component the
 *  application does not render. */
const useFolds = (initial: readonly string[] = []) => {
  const [open, setOpen] = useState<ReadonlySet<string>>(new Set(initial))
  return {
    open,
    onToggle: (key: string) =>
      setOpen((current) => {
        const next = new Set(current)
        if (next.has(key)) next.delete(key)
        else next.add(key)
        return next
      }),
  }
}

const Frame = ({ heading, children }: { heading: string; children: React.ReactNode }) => (
  <section style={{ padding: 'var(--space-3)', maxWidth: 720 }}>
    <h3 style={{ font: 'inherit', color: 'var(--fg-faint)', margin: '0 0 var(--space-2)' }}>
      {heading}
    </h3>
    {children}
  </section>
)

/** As a reader first meets it: summary open, superseded messages folded away.
 *
 *  Read the three sentences. None of them says anything was removed, and that
 *  is the feature. */
export const AsItArrives: Story = {
  render: function Render() {
    const folds = useFolds()
    return (
      <Frame heading="context compacted">
        <Compaction summary={SUMMARY} hidden={HIDDEN} through={HIDDEN.length} {...folds} />
      </Frame>
    )
  },
}

/** **The proof.** The superseded messages, opened — still here, still
 *  readable, simply not sent.
 *
 *  This is the story that makes the wording checkable rather than merely
 *  reassuring: a pane that claimed the messages were still in the log and then
 *  had nothing to show would be worse than one that admitted they were gone. */
export const Superseded: Story = {
  render: function Render() {
    const folds = useFolds(['compaction:messages'])
    return (
      <Frame heading="the superseded messages, expanded">
        <Compaction summary={SUMMARY} hidden={HIDDEN} through={HIDDEN.length} {...folds} />
      </Frame>
    )
  },
}

/** The summary folded away, which is the one thing a reader can hide.
 *
 *  Its key is inverted (`…:closed`), so this story adds the key rather than
 *  removing one — the shape that catches an author reading the default the
 *  wrong way round. */
export const SummaryClosed: Story = {
  render: function Render() {
    const folds = useFolds(['compaction:summary:closed'])
    return (
      <Frame heading="summary folded">
        <Compaction summary={SUMMARY} hidden={HIDDEN} through={HIDDEN.length} {...folds} />
      </Frame>
    )
  },
}

/** No summary text came back with the session.
 *
 *  The pane says *that*, rather than showing an empty box. "No summary text
 *  was returned" is a fact about this session's record; an empty fold would
 *  read as a summary that failed to render, and a reader would not know which
 *  of the two they were looking at. */
export const NoSummaryText: Story = {
  render: function Render() {
    const folds = useFolds()
    return (
      <Frame heading="no summary returned">
        <Compaction summary="" hidden={HIDDEN} through={HIDDEN.length} {...folds} />
      </Frame>
    )
  },
}

/** One message compacted, which is where the plural would show.
 *
 *  "the first 1 messages" is the kind of thing that ships and stays — the same
 *  hazard `ProjectCard`'s `OneOfEverything` story exists for, in a different
 *  pane. */
export const OneMessage: Story = {
  render: function Render() {
    const folds = useFolds()
    return (
      <Frame heading="a single superseded message">
        <Compaction summary={SUMMARY} hidden={[HIDDEN[0]!]} through={1} {...folds} />
      </Frame>
    )
  },
}
