import type { Meta, StoryObj } from '@storybook/react-vite'
import { useState } from 'react'

// `OverlayHost` is not imported: every story here mounts it through `Shell`,
// which is the only way a view should ever get one. A story that constructed
// a bare host would be demonstrating an arrangement the design does not want.
import { Overlay } from './OverlayHost.tsx'
import { Shell } from './Shell.tsx'

/** The stacking contract, shown where stacking actually happens.
 *
 * These stories carry more weight than most, because `OverlayHost.test.tsx`
 * can assert the `inert` attribute and cannot assert what `inert` *does* —
 * jsdom implements the attribute's presence and none of its behaviour — and
 * can assert DOM order but not paint order, because jsdom resolves no
 * stacking contexts. **Everything this host promises is only observable in a
 * browser, which is here.**
 *
 * What to check in `DockThenDrawer`, which is the reason the host exists: the
 * drawer must paint *over* the dock, the dock must be visibly dimmed and
 * refuse a click, and Tab must not reach the dock's button. On `main` all
 * three are wrong — the dock popover is `z-index: 40` and the drawer's
 * `aria-modal` backdrop is `z-index: 20`, so a live, clickable panel sits on
 * top of a dialog claiming to be modal.
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
  title: 'layout/OverlayHost',
  parameters: { layout: 'fullscreen' },
}

export default meta

type Story = StoryObj

const Panel = ({ children }: { children: React.ReactNode }) => (
  <div
    style={{
      background: 'var(--bg-panel)',
      border: '1px solid var(--line)',
      borderRadius: 'var(--radius)',
      boxShadow: 'var(--shadow-1)',
      padding: 'var(--space-4)',
      minWidth: '280px',
    }}
  >
    {children}
  </div>
)

/** The arrangement that is broken today, built out of the host.
 *
 * Open the feed and the drawer arrives *after* the dock, so it is later in the
 * DOM and above it — with one shared z-index there is no second number to get
 * wrong. The dock goes inert, which is the part the dock currently has to
 * reason about in a comment and get backwards. */
const DockAndDrawer = () => {
  const [dockOpen, setDockOpen] = useState(true)
  const [watching, setWatching] = useState(false)

  return (
    <Shell
      chrome={
        <>
          <strong>research-team</strong>
          <button type="button" onClick={() => setDockOpen((open) => !open)}>
            agents
          </button>
        </>
      }
    >
      <p style={{ padding: 'var(--space-4)' }}>
        The page behind. A modal must make everything except itself unreachable.
      </p>

      {dockOpen ? (
        <Overlay label="Agents" onDismiss={() => setDockOpen(false)}>
          <div style={{ position: 'fixed', top: 'var(--topbar-h)', right: 'var(--space-4)' }}>
            <Panel>
              <p>2 agents running</p>
              <button type="button" onClick={() => setWatching(true)}>
                watch this session
              </button>
            </Panel>
          </div>
        </Overlay>
      ) : null}

      {watching ? (
        <Overlay label="Watching a session" modal onDismiss={() => setWatching(false)}>
          <div
            style={{
              position: 'fixed',
              inset: '0 0 0 auto',
              width: 'min(42vw, 640px)',
              background: 'var(--bg-panel)',
              borderLeft: '1px solid var(--line)',
              padding: 'var(--space-4)',
            }}
          >
            <h3>Watching a session</h3>
            <button type="button" onClick={() => setWatching(false)}>
              Close
            </button>
            <p>The transcript.</p>
          </div>
        </Overlay>
      ) : null}
    </Shell>
  )
}

/** A popover and, opened from it, a modal drawer — the exact pair that inverts
 *  on `main`. Escape closes the drawer and not the popover, because the host
 *  gives Escape to the topmost layer and the dock no longer has an opinion. */
export const DockThenDrawer: Story = { render: () => <DockAndDrawer /> }

/** Two modals, stacked. The confirm is above the drawer and stays usable; the
 *  drawer beneath it goes inert. This is why a modal marks the layers *below*
 *  it rather than every layer but itself — `Confirm` is built on `Drawer`, so
 *  a modal-over-modal is an ordinary case rather than a contrived one. */
export const TwoDeep: Story = {
  render: () => (
    <Shell chrome={<strong>research-team</strong>}>
      <p style={{ padding: 'var(--space-4)' }}>The page behind.</p>
      <Overlay label="Session detail" modal>
        <div style={{ position: 'fixed', inset: '10% 10% auto 10%' }}>
          <Panel>
            <h3>Session detail</h3>
            <p>Beneath the confirm: dimmed, inert, unreachable by Tab.</p>
          </Panel>
        </div>
      </Overlay>
      <Overlay label="Delete this session?" modal>
        <div style={{ position: 'fixed', inset: '30% 25% auto 25%' }}>
          <Panel>
            <h3>Delete this session?</h3>
            <p>The session and its event log are removed.</p>
            <button type="button">Cancel</button>
          </Panel>
        </div>
      </Overlay>
    </Shell>
  ),
}

/** A single non-modal layer, which takes nothing away from the page: no
 *  backdrop, nothing inert, the page still clickable behind it. A popover is
 *  not a dialog, and a host that treated every layer as modal would be a
 *  worse answer than the four z-index values it replaces. */
export const OneNonModalLayer: Story = {
  render: () => (
    <Shell chrome={<strong>research-team</strong>}>
      <p style={{ padding: 'var(--space-4)' }}>
        Still clickable — a popover takes nothing away from the page.
      </p>
      <Overlay label="Row actions">
        <div style={{ position: 'fixed', top: '30%', left: '30%' }}>
          <Panel>
            <p>Fork from here</p>
            <p>Copy link</p>
          </Panel>
        </div>
      </Overlay>
    </Shell>
  ),
}
