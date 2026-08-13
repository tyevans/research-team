import type { Meta, StoryObj } from '@storybook/react-vite'

import { CitationList } from './CitationList.tsx'
import { PROJECT } from './ask-fixtures.ts'

/** What an answer stood on.
 *
 * `None` renders nothing, and that is the story: most answers cite nothing,
 * and a "Sources" heading over emptiness on every one of them reads as a page
 * that lost its data. A blank canvas here is the component working.
 */
const meta = {
  component: CitationList,
  title: 'ask/CitationList',
  args: { projectId: PROJECT },
} satisfies Meta<typeof CitationList>

export default meta

type Story = StoryObj<typeof meta>

export const None: Story = { args: { citations: [] } }

export const One: Story = { args: { citations: [{ kind: 'source', id: 's1' }] } }

/** Enough to wrap, which is the case the row shape is for -- the ids are
 *  server-side identifiers and there is no length this component can assume. */
export const Many: Story = {
  args: {
    citations: [
      's1',
      's2',
      's14',
      'doc-2019-spacing',
      'doc-2019-massed-review',
      's7',
      's8',
      'doc-untimed-final-test',
    ].map((id) => ({ kind: 'source' as const, id })),
  },
}
