import type { Meta, StoryObj } from '@storybook/react-vite'
import { useState } from 'react'

import { Shell } from '../layout/Shell.tsx'
import { Choices } from './Choices.tsx'
import { TabList, TabPanel, Tabs } from './Tabs.tsx'

/** The two primitives that share one skin, shown together because telling them
 *  apart by eye is the thing to check.
 *
 * `Tabs.test.tsx` and `Choices.test.tsx` settle the semantics — which control
 * owns a panel, what the arrow keys do, what a screen reader is told. Neither
 * can see any of this:
 *
 * - **The selected look.** It moved off a `.active` class we wrote and onto the
 *   attributes the libraries write, `[data-state='active']` for a tab and
 *   `[data-state='checked']` for a choice. jsdom applies no stylesheet, so a
 *   selector that matches neither would pass every test and ship a header where
 *   nothing looks chosen.
 * - **That they still look identical to each other.** They are two components
 *   now and one control strip on screen, deliberately: the reader of this
 *   header should not be asked to care which is which. If the two rows ever
 *   drift apart visually, this story is where it shows.
 * - **Selection following focus in a real event loop.** Tab into the
 *   rendered/source row and press ArrowRight once: the panel changes with no
 *   second press. jsdom reports the focus move and not the selection, which is
 *   written up in `Choices.test.tsx`.
 * - **The tab list not doing that.** Tab into contents/history and press
 *   ArrowRight: focus moves, the panel does not change until Enter. The two
 *   rows answer the arrow keys differently, on purpose, because one of them
 *   costs a request.
 *
 * `Shell` is here for the `OverlayHost` that the author/learner explanations
 * need; without one those tooltips open onto nothing.
 */
const meta: Meta = {
  title: 'common/Tabs',
  parameters: { layout: 'fullscreen' },
}

export default meta

type Story = StoryObj

const Line = ({ children }: { children: string }) => (
  <p style={{ padding: 'var(--space-3)', margin: 0 }}>{children}</p>
)

/** `FileView`'s header, which is where both primitives ship and the only place
 *  all three rows appear at once. The path, two `Choices` and one `TabList`,
 *  in the order the view puts them. */
export const FileViewHeader: Story = {
  render: function Render() {
    const [tab, setTab] = useState('content')
    const [mode, setMode] = useState<'rendered' | 'source'>('rendered')
    const [audience, setAudience] = useState<'author' | 'learner'>('author')
    return (
      <Shell>
        <Tabs value={tab} onValueChange={setTab}>
          <div className="file-view-head">
            <span className="fv-path">course/module-1/lesson.md</span>
            {tab === 'content' ? (
              <Choices
                label="How to show this file"
                options={[
                  { id: 'rendered', label: 'rendered' },
                  { id: 'source', label: 'source' },
                ]}
                value={mode}
                onValueChange={setMode}
              />
            ) : null}
            {tab === 'content' && mode === 'rendered' ? (
              <Choices
                label="Whose view of this document"
                options={[
                  {
                    id: 'author',
                    label: 'author',
                    explanation:
                      'Everything the file contains, including answers and authoring warnings.',
                  },
                  {
                    id: 'learner',
                    label: 'learner',
                    explanation:
                      'Preview what a learner is sent: answers and rationales withheld, and graded on the server.',
                  },
                ]}
                value={audience}
                onValueChange={setAudience}
              />
            ) : null}
            <TabList
              label="File view"
              options={[
                { id: 'content', label: 'contents' },
                { id: 'history', label: 'history' },
              ]}
            />
          </div>
          <TabPanel value="content">
            <Line>{`the file, as ${mode}, for the ${audience}`}</Line>
          </TabPanel>
          <TabPanel value="history">
            <Line>every revision of it</Line>
          </TabPanel>
        </Tabs>
      </Shell>
    )
  },
}
