import type { Meta, StoryObj } from '@storybook/react-vite'

import { Pane } from './Pane.tsx'
import { Shell } from './Shell.tsx'
import { Split } from './Split.tsx'
import type { Track } from './split-tracks.ts'

/** The three regions, and the scroll contract that is the whole reason the
 *  surface is a named thing rather than a div.
 *
 *  `research.css` records what the contract buys, and it is worth having on
 *  the gallery page beside the thing it describes: "inside a scrolling page
 *  every pane needs a fixed pixel height, and fixed heights are what made this
 *  page a stack of small boxes with the largest artifact in the smallest one."
 */
/** Typed as a bare `Meta` rather than `satisfies Meta<typeof Component>`.
 *
 * The bound form makes `args` mandatory on every story, and every story in
 * this file supplies its whole tree through `render` because the interesting
 * states are stateful — a collapsed pane you cannot expand, or an overlay
 * nothing opens, demonstrates nothing. Declaring `args` as well would mean
 * writing the props twice and letting the two copies disagree. The cost is
 * that Storybook cannot infer an args table for the controls panel; there is
 * no docs addon installed to show one, and these compositions have no single
 * component whose props a table would describe. */
const meta: Meta = {
  title: 'layout/Shell',
  parameters: { layout: 'fullscreen' },
}

export default meta

type Story = StoryObj

const TRACKS: readonly Track[] = [
  { id: 'rail', min: 280, weight: 1 },
  { id: 'stage', min: 320, weight: 2 },
]

const Chrome = () => (
  <>
    <strong>research-team</strong>
    <span style={{ color: 'var(--fg-dim)' }}>/ a project / a session</span>
    <span style={{ marginLeft: 'auto', color: 'var(--k-file)' }}>live</span>
  </>
)

const Long = ({ what }: { what: string }) => (
  <div style={{ padding: 'var(--space-3)' }}>
    {Array.from({ length: 40 }, (_, index) => (
      <p key={index}>
        {what} {index + 1}
      </p>
    ))}
  </div>
)

/** The default. The surface fills the screen and never scrolls; each pane
 *  scrolls on its own. Scroll one and the other stays where it was — that
 *  independence is the property, and it is what a single scrolling page cannot
 *  give you. */
export const ViewportScrolling: Story = {
  render: () => (
    <div style={{ height: '90vh' }}>
      <Shell chrome={<Chrome />} scroll="viewport">
        <Split
          id="research"
          label="Research"
          tracks={TRACKS}
          collapsed={new Set()}
          onCollapsedChange={() => {}}
        >
          <Pane id="rail" label="Topics" meta="18 open" minContent={240}>
            <Long what="topic" />
          </Pane>
          <Pane id="stage" label="Graph">
            <Long what="entity" />
          </Pane>
        </Split>
      </Shell>
    </div>
  ),
}

/** The narrow mode, declared rather than inherited.
 *
 *  This is `responsive.css` setting `body { overflow: auto }` below 820px,
 *  turned into a property of the shell. The behaviour is the same; what
 *  changes is that a reader of `Shell` can see that it happens. A global
 *  overridden by a media query in a different file is a mode nobody knows
 *  about until they are debugging it.
 *
 *  **The one to open beside `ViewportScrolling`**, at any width. Both stories
 *  rendered the same page until this was fixed — the same element scrolled in
 *  each, `.lay-pane-body`, because the surface's `overflow: auto` had nothing
 *  to scroll while everything under it was still sized to fit. What tells them
 *  apart is which box the scrollbar is on and whether the chrome leaves with
 *  the content. */
export const PageScrolling: Story = {
  render: () => (
    <div style={{ height: '90vh' }}>
      <Shell chrome={<Chrome />} scroll="page">
        <Pane id="stack" label="Everything">
          <Long what="row" />
        </Pane>
      </Shell>
    </div>
  ),
}

/** Page scrolling with two panes still side by side, which is the case the
 *  single-pane story above cannot show: the panes stretch to the taller of
 *  them and the whole row scrolls as one, rather than each column scrolling
 *  where it stands. Scroll it and both move together — that is the property,
 *  and it is the one `ViewportScrolling` deliberately does not have. */
export const PageScrollingWithColumns: Story = {
  render: () => (
    <div style={{ height: '90vh' }}>
      <Shell chrome={<Chrome />} scroll="page">
        <Split
          id="research"
          label="Research"
          tracks={TRACKS}
          collapsed={new Set()}
          onCollapsedChange={() => {}}
        >
          <Pane id="rail" label="Topics" meta="18 open" minContent={240}>
            <Long what="topic" />
          </Pane>
          <Pane id="stage" label="Graph">
            <Long what="entity" />
          </Pane>
        </Split>
      </Shell>
    </div>
  ),
}

/** No chrome. A shell without it is a call site you can see rather than a page
 *  that silently renders without a breadcrumb, which is why `chrome` is a
 *  named slot and not a convention about `children`. */
export const SurfaceOnly: Story = {
  render: () => (
    <div style={{ height: '90vh' }}>
      <Shell>
        <Pane id="only" label="Surface">
          <Long what="line" />
        </Pane>
      </Shell>
    </div>
  ),
}
