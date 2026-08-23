import { useState } from 'react'
import type { Meta, StoryObj } from '@storybook/react-vite'

import { Choices } from './Choices.tsx'
import { TabList, TabPanel, Tabs } from './Tabs.tsx'

/** A row of buttons that answer one question, and the defect this component
 *  is the historical site of.
 *
 * **`ChosenAndExplained` is a companion to a test, not a guard.** `CLAUDE.md`
 * records a defect that shipped past a fully green suite and was caught by
 * eye: "a chosen control drawing in the unchosen colour, because a `Tooltip`
 * and a `RadioGroup` both wrote `data-state` to one element". That element is
 * this component's `Choice` — `Tooltip asChild` wraps `RadioGroup.Item`, and
 * both libraries claim the same attribute.
 *
 * **The guard already exists and is stronger than this file.**
 * `Tabs.browser.test.tsx` measures the computed colour of an explained,
 * chosen option against `--accent`, and was proved red by restoring the
 * `[data-state=…]` selector in `workspace.css`. Nothing here adds to that,
 * and a story claiming to be the defence would be worse than no story: it
 * would look like cover.
 *
 * What the story adds is the *shape* of the defect for a person. The test
 * knows two rgb literals; it cannot show that the failure looked entirely
 * reasonable, which is why it survived review. Seeing the explained and
 * unexplained groups side by side is what makes "these must match" a thing
 * anyone would think to check on the next component that stacks two
 * primitives on one element.
 *
 * **`ChoicesAgainstTabs`** is the other one worth reading. `Choices.tsx`
 * argues at length that these are not tabs — a tab claims to control a panel
 * and says so with `aria-controls`, where these change how one panel draws
 * itself. The two look nearly identical and mean different things, which is
 * how `FileView` came to hold three identical-looking rows meaning two
 * different things. Seeing them together is the only way that distinction
 * stays learnable.
 */
const meta: Meta = {
  title: 'common/Choices',
}

export default meta

type Story = StoryObj

const Frame = ({ heading, children }: { heading: string; children: React.ReactNode }) => (
  <section style={{ padding: 'var(--space-3)' }}>
    <h3 style={{ font: 'inherit', color: 'var(--fg-dim)', margin: '0 0 var(--space-2)' }}>
      {heading}
    </h3>
    {children}
  </section>
)

/** The plain case, live. Arrow keys move *and* select — the APG contract for
 *  radios, and the reason `RadioGroup` was chosen over `ToggleGroup`, whose
 *  arrows move focus without changing the answer.
 *
 *  Check by keyboard: the row is one tab stop, not three. Every option being
 *  its own tab stop is what the two hand-rolled predecessors got wrong while
 *  announcing themselves as radiogroups. */
export const Live: Story = {
  render: function Render() {
    const [value, setValue] = useState<'rendered' | 'source'>('rendered')
    return (
      <Frame heading="How to show this file">
        <Choices
          label="How to show this file"
          options={[
            { id: 'rendered', label: 'rendered' },
            { id: 'source', label: 'source' },
          ]}
          value={value}
          onValueChange={setValue}
        />
      </Frame>
    )
  },
}

/** The defect, shown rather than asserted. `Tabs.browser.test.tsx` is what
 *  actually fails if it returns.
 *
 *  The rule: **`two` and `three` must be indistinguishable except that one has
 *  a tooltip.** `two` is chosen and carries an explanation, so it is the
 *  element both `Tooltip` and `RadioGroup` write `data-state` to. `three` is
 *  chosen in a second group and carries none.
 *
 *  Worth knowing while looking at it: this page would have looked *fine* to a
 *  reviewer who did not already know the rule. The chosen option in the
 *  broken build was dim, not missing, and a dim control among controls reads
 *  as "not applicable here" rather than as a bug. That is the transferable
 *  part. */
export const ChosenAndExplained: Story = {
  render: function Render() {
    const [a, setA] = useState<'one' | 'two'>('two')
    const [b, setB] = useState<'three' | 'four'>('three')
    return (
      <>
        <Frame heading="chosen option has an explanation">
          <Choices
            label="chosen option has an explanation"
            options={[
              { id: 'one', label: 'one' },
              { id: 'two', label: 'two', explanation: 'This option carries a tooltip.' },
            ]}
            value={a}
            onValueChange={setA}
          />
        </Frame>
        <Frame heading="chosen option has none — must look the same">
          <Choices
            label="chosen option has none"
            options={[
              { id: 'three', label: 'three' },
              { id: 'four', label: 'four', explanation: 'This option carries a tooltip.' },
            ]}
            value={b}
            onValueChange={setB}
          />
        </Frame>
      </>
    )
  },
}

/** Every option explained, which is the busiest this gets.
 *
 *  A row where each control owes the reader a sentence is the case that made
 *  `Tooltip asChild` necessary: `Tooltip`'s own wrapper button would put a
 *  second focusable element around the item and take the roving tabindex away
 *  from the thing that has to carry it. Check by keyboard that the row is
 *  still one tab stop with four explanations on it. */
export const AllExplained: Story = {
  render: function Render() {
    const [value, setValue] = useState('recent')
    return (
      <Frame heading="Sort these documents by">
        <Choices
          label="Sort these documents by"
          options={[
            { id: 'recent', label: 'recent', explanation: 'Newest first, by fetch time.' },
            { id: 'relevance', label: 'relevance', explanation: 'By retrieval score.' },
            { id: 'title', label: 'title', explanation: 'Alphabetical.' },
            { id: 'source', label: 'source', explanation: 'Grouped by domain.' },
          ]}
          value={value}
          onValueChange={setValue}
        />
      </Frame>
    )
  },
}

/** **The distinction, side by side.**
 *
 *  Top: `Tabs`, which controls a panel and carries `aria-controls`. Bottom:
 *  `Choices`, which changes how one panel draws itself and carries none.
 *
 *  They are nearly the same picture. That is the problem `Choices.tsx` was
 *  written about, not an accident of this story — `FileView`'s header once
 *  held three rows built from one `TabGroup` meaning two different things.
 *  The test for which to reach for is in `Tabs.tsx`; this is the page that
 *  makes the question occur to you at all. */
export const ChoicesAgainstTabs: Story = {
  render: function Render() {
    const [mode, setMode] = useState<'rendered' | 'source'>('rendered')
    const [tab, setTab] = useState('summary')
    return (
      <>
        <Frame heading="Tabs — controls a panel, announces aria-controls">
          <Tabs value={tab} onValueChange={setTab}>
            <TabList
              label="Sections"
              options={[
                { id: 'summary', label: 'summary' },
                { id: 'citations', label: 'citations' },
              ]}
            />
            <TabPanel value="summary">
              <p style={{ color: 'var(--fg-dim)' }}>The summary panel — a different element.</p>
            </TabPanel>
            <TabPanel value="citations">
              <p style={{ color: 'var(--fg-dim)' }}>The citations panel — swapped in for it.</p>
            </TabPanel>
          </Tabs>
        </Frame>
        <Frame heading="Choices — changes how one panel draws itself">
          <Choices
            label="How to show this file"
            options={[
              { id: 'rendered', label: 'rendered' },
              { id: 'source', label: 'source' },
            ]}
            value={mode}
            onValueChange={setMode}
          />
          <p style={{ color: 'var(--fg-dim)' }}>
            One panel, drawn as {mode}. No second panel was swapped in.
          </p>
        </Frame>
      </>
    )
  },
}
