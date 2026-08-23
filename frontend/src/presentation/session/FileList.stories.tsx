import { useState } from 'react'
import type { Meta, StoryObj } from '@storybook/react-vite'

import { FilePath } from '@domain/shared/file-path.ts'
import type { WorkspaceFile } from '@domain/workspace/workspace-file.ts'

import { FileList } from './FileList.tsx'

/** The workspace at the selected point, and the deliberate counterpart to
 *  `Timeline`'s grid.
 *
 * The two are the console's worked example of choosing an ARIA role on the
 * merits rather than by habit. `FileList.tsx`: **"A listbox rather than a
 * grid: a file row has exactly one action, and the simplest role that fits is
 * the one assistive technology handles best."** `Timeline` is a grid because
 * its rows carry two actions — scrub, and fork — and only a grid legitimately
 * allows a focusable control inside a row.
 *
 * Reading the two pages together is the point. A reviewer who sees only one
 * has no way to tell a considered role from a copied one.
 *
 * **The selection pattern is the other half, and it is the one an
 * accessibility linter gets wrong.** This is an `aria-activedescendant`
 * listbox: the tab stop is the container, each `option` is deliberately *not*
 * focusable, and selection is announced by the container pointing at a row's
 * id. That is one of the two patterns the ARIA practices allow; the rule only
 * models the other (roving tabindex), which is why the file carries a disable
 * comment arguing it. Giving each row its own tab stop would put every file in
 * the tab order — a regression, not a fix.
 *
 * `Historical` is the state worth a second look. An empty workspace means two
 * different things depending on where the reader is standing, and the pane
 * says which: *"the agent has not written anything yet"* live, against *"the
 * workspace was empty at event N"* when scrubbed. Same absence, different
 * fact.
 */
const meta: Meta = {
  title: 'session/FileList',
}

export default meta

type Story = StoryObj

const file = (path: string, size: number, revisions = 0): WorkspaceFile => ({
  path: FilePath.of(path),
  size,
  revisions,
})

const FILES: readonly WorkspaceFile[] = [
  file('course/framing/outline.md', 4_210, 3),
  file('course/framing/objectives.md', 2_890, 1),
  file('notes/tetrarchy.md', 11_400, 7),
  file('sources/diocletian-provinces.json', 96_512),
  file('a/deeply/nested/path/that/keeps/going/for/a/while/final.md', 512, 2),
]

const Frame = ({ heading, children }: { heading: string; children: React.ReactNode }) => (
  <section style={{ padding: 'var(--space-3)', maxWidth: 420 }}>
    <h3 style={{ font: 'inherit', color: 'var(--fg-faint)', margin: '0 0 var(--space-2)' }}>
      {heading}
    </h3>
    {children}
  </section>
)

const Live = ({
  files,
  at = null,
  openPath = null,
}: {
  files: readonly WorkspaceFile[]
  at?: number | null
  openPath?: string | null
}) => {
  const [open, setOpen] = useState(openPath === null ? null : FilePath.of(openPath))
  return (
    <FileList
      files={files}
      open={open}
      historicalAt={at}
      onOpen={setOpen}
      onReopen={() => undefined}
    />
  )
}

/** The workspace, nothing selected.
 *
 *  Live: click the list and use the arrow keys. The list is one tab stop, not
 *  five — arrowing moves the selection and `aria-activedescendant` follows it,
 *  which is what a screen reader reads. */
export const AWorkspace: Story = {
  render: () => (
    <Frame heading="files">
      <Live files={FILES} />
    </Frame>
  ),
}

/** One file open. The selection has to be unmistakable down a long column,
 *  because it is also what Enter re-reads. */
export const OneOpen: Story = {
  render: () => (
    <Frame heading="one file open">
      <Live files={FILES} openPath="notes/tetrarchy.md" />
    </Frame>
  ),
}

/** A path longer than the column.
 *
 *  Paths are the one thing here with no bound — an agent writes wherever it
 *  likes. What to check: the size and revision count stay legible rather than
 *  being pushed out by the path, since they are the two things a reader scans
 *  the column for. */
export const ALongPath: Story = {
  render: () => (
    <Frame heading="a path that does not fit">
      <Live files={[FILES[4]!, FILES[0]!]} />
    </Frame>
  ),
}

/** **The pair.** An empty workspace, live.
 *
 *  "The agent has not written anything yet" is a statement about *now*. */
export const EmptyLive: Story = {
  render: () => (
    <Frame heading="empty — following the head">
      <Live files={[]} />
    </Frame>
  ),
}

/** The same absence, scrubbed back.
 *
 *  "The workspace was empty at event 40" is a statement about *then*, and it
 *  is a different fact. A pane that gave both states one sentence would tell a
 *  reader scrubbed into the past that the agent has written nothing — which is
 *  false as soon as they scrub forward again. */
export const EmptyHistorical: Story = {
  render: () => (
    <Frame heading="empty — pinned to event 40">
      <Live files={[]} at={40} />
    </Frame>
  ),
}

/** Files with no revisions recorded, which is what a fresh write looks like
 *  before any edit. The `rN` prefix is absent rather than `r0`. */
export const NoRevisions: Story = {
  render: () => (
    <Frame heading="never edited">
      <Live files={[file('sources/raw.json', 240_128), file('sources/index.json', 1_024)]} />
    </Frame>
  ),
}
