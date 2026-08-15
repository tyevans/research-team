import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import { expect, it, vi } from 'vitest'

import { Pane } from './Pane.tsx'
import { Split } from './Split.tsx'
import type { Track } from './split-tracks.ts'

/** What a pane promises about its own content and its own name.
 *
 * **What these tests constrain.** Whether the body is in the tree, whether it
 * is marked `hidden`, what the toggle is called, and whether a pane inside a
 * `Split` follows it. All structural.
 *
 * **What they do not.** Anything about size. `minContent` is asserted as a
 * custom property on the element, not as a height, because jsdom lays nothing
 * out — a pane could set `--pane-min-content: 240px` and be rendered 12px tall
 * and nothing here would notice. `collapseTo="rail"` is asserted as a data
 * attribute, not as a 34px column with a rotated title. Those are the two
 * things the pane exists to do, and they are exactly the two a browser has to
 * check.
 *
 * Proved red by: rendering the body when `unmountWhenCollapsed` is set,
 * dropping `hidden`, replacing the visually-hidden label with the glyph alone,
 * and ignoring the enclosing split's collapsed set.
 */

const TRACKS: readonly Track[] = [
  { id: 'timeline', min: 280, weight: 1.05 },
  { id: 'workspace', min: 320, weight: 1.5 },
]

it('names its toggle with a sentence rather than a glyph', () => {
  render(
    <Pane id="timeline" label="Timeline" collapsed={false} onToggle={() => {}}>
      rows
    </Pane>,
  )

  // The defect this closes is live in `session/Pane.tsx`, whose toggle renders
  // `{collapsed ? '▸' : '◂'}` as its only child so its accessible name is a
  // glyph. `AgentWidget` names that bug in a comment and routes around it
  // rather than through it, which is how the correct behaviour came to exist
  // in one component and the incorrect one in another.
  expect(screen.getByRole('button', { name: 'Collapse Timeline' })).toHaveAttribute(
    'aria-expanded',
    'true',
  )
})

it('offers no toggle inside a split when it is declared uncollapsible', () => {
  // The content half of a sidebar layout. `Pane` renders a toggle for every
  // pane in a split, which is right for peers trading width against each other
  // and wrong for the one region everything else folds *away from* -- a reader
  // who folds the content area is left with two rails and no content, which is
  // the state `toggleCollapsed`'s last-open guard exists to prevent and cannot,
  // because the sidebar is still open.
  //
  // Red without `collapsible`: renders "Collapse Material".
  render(
    <Split
      id="project"
      label="Project panes"
      tracks={TRACKS}
      collapsed={new Set()}
      onCollapsedChange={() => {}}
    >
      <Pane id="timeline" label="Queue">
        rows
      </Pane>
      <Pane id="workspace" label="Material" collapsible={false}>
        tabs
      </Pane>
    </Split>,
  )

  expect(screen.queryByRole('button', { name: /Material/ })).toBeNull()
  // The sidebar keeps its own, or the layout has no controls at all.
  expect(screen.getByRole('button', { name: 'Collapse Queue' })).toBeInTheDocument()
})

it('still names the region when its title is not drawn', () => {
  // A pane whose header is a tab strip has no room for a second heading saying
  // the same word, but the region still has to be findable by name -- dropping
  // `label` rather than hiding it would take the accessible name with it.
  //
  // Red without `showLabel`: the heading is in the tree.
  render(
    <Pane id="workspace" label="Material" showLabel={false} collapsed={false}>
      tabs
    </Pane>,
  )

  expect(screen.getByRole('region', { name: 'Material' })).toBeInTheDocument()
  expect(screen.queryByRole('heading', { name: 'Material' })).toBeNull()
})

it('keeps a collapsed body in the tree by default, marked hidden', () => {
  render(
    <Pane id="timeline" label="Timeline" collapsed onToggle={() => {}}>
      <input aria-label="filter" defaultValue="half-typed" />
    </Pane>,
  )

  // Kept, so a scroll position and a half-typed filter survive a fold. The
  // cost is that a virtualizer in here would measure a zero-height container,
  // which is what `unmountWhenCollapsed` is for and why it is a declared
  // choice rather than the default in either direction.
  const body = screen.getByLabelText('filter', { selector: 'input' }).closest('.lay-pane-body')
  expect(body).toHaveAttribute('hidden')
  expect(screen.getByRole('button', { name: 'Expand Timeline' })).toBeInTheDocument()
})

it('drops a collapsed body entirely when asked to', () => {
  render(
    <Pane id="documents" label="Documents" collapsed unmountWhenCollapsed onToggle={() => {}}>
      <p>a virtualized list</p>
    </Pane>,
  )

  // Not merely hidden: gone. A virtualizer inside a hidden-but-mounted pane
  // measures a zero-height scroll container and caches that, so the pane comes
  // back empty.
  expect(screen.queryByText('a virtualized list')).toBeNull()
})

it('renders standalone, from props alone', () => {
  // The enforcement mechanism for the whole design: a component that cannot be
  // rendered from props alone cannot have a story, and a component that cannot
  // have a story is telling you it is not a component yet. `Pane` reads its
  // enclosing `Split` through context when there is one, so this asserts the
  // fallback rather than assuming it.
  render(
    <Pane id="alone" label="Alone">
      content
    </Pane>,
  )

  expect(screen.getByRole('region', { name: 'Alone' })).toBeInTheDocument()
  expect(screen.getByText('content')).toBeVisible()
  // No toggle at all without a way to act on one, rather than a dead button.
  expect(screen.queryByRole('button')).toBeNull()
})

it('follows the split it is inside, and reports a refusal to the view', async () => {
  const user = userEvent.setup()
  const onRefuse = vi.fn()

  const onCollapsedChange = vi.fn()

  const Workbench = () => {
    const [collapsed, setCollapsed] = useState<ReadonlySet<string>>(new Set(['timeline']))
    return (
      <Split
        id="session"
        label="Session panes"
        tracks={TRACKS}
        collapsed={collapsed}
        onCollapsedChange={(next) => {
          onCollapsedChange(next)
          setCollapsed(next)
        }}
        onRefuse={onRefuse}
      >
        <Pane id="timeline" label="Timeline">
          rows
        </Pane>
        <Pane id="workspace" label="Workspace">
          files
        </Pane>
      </Split>
    )
  }

  render(<Workbench />)
  expect(screen.getByRole('button', { name: 'Expand Timeline' })).toBeInTheDocument()

  // Collapsing the only open pane is refused, and the refusal is handed to the
  // view rather than announced by the primitive — the view owns the toast, and
  // a layout component reaching for a notification store is exactly the
  // coupling the props-only rule exists to prevent.
  await user.click(screen.getByRole('button', { name: 'Collapse Workspace' }))
  expect(onRefuse).toHaveBeenCalledTimes(1)
  expect(screen.getByRole('button', { name: 'Collapse Workspace' })).toBeInTheDocument()

  // *Instead of*, not *as well as*, which is what the prop's docstring claims
  // and what nothing checked until a mutation pass went looking. Calling both
  // is harmless today only because `toggleCollapsed` returns the set it was
  // given when it refuses, so the write is a no-op -- two facts in two files
  // holding one property up between them. Assert the one that is stated:
  // whoever changes the other has to come past this.
  expect(onCollapsedChange).not.toHaveBeenCalled()

  await user.click(screen.getByRole('button', { name: 'Expand Timeline' }))
  expect(screen.getByRole('button', { name: 'Collapse Timeline' })).toBeInTheDocument()
})

it('carries its content floor as a custom property', () => {
  render(
    <Pane id="topics" label="Topics" minContent={240}>
      rows
    </Pane>,
  )

  // Asserting the declaration, not the height, and the docstring above says
  // why. 240px is `research.css`'s existing fix — roughly seven document rows
  // — expressed as a parameter that travels with the pane instead of a literal
  // in one stylesheet selected by two pane names.
  expect(screen.getByRole('region', { name: 'Topics' })).toHaveStyle({
    '--pane-min-content': '240px',
  })
})
