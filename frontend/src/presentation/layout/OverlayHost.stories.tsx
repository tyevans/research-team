import type { Meta, StoryObj } from '@storybook/react-vite'
import { useState } from 'react'

// `OverlayHost` is not imported: every story here mounts it through `Shell`,
// which is the only way a view should ever get one. A story that constructed
// a bare host would be demonstrating an arrangement the design does not want.
import { Drawer } from '../common/Drawer.tsx'
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
 * refuse a click, and — the part a browser caught and jsdom's first round of
 * assertions did not — **Tab from inside the drawer must reach nothing
 * outside it, including the chrome.** The first version of this host made
 * every other *layer* inert and left the whole shell tabbable, so the pointer
 * was blocked by the backdrop and the keyboard was not.
 *
 * Before the migration the painting half was wrong too: the dock popover was
 * `z-index: 40` and the drawer's `aria-modal` backdrop was `z-index: 20`, so a
 * live, clickable panel sat on top of a dialog claiming to be modal. Both
 * declarations are deleted; these stories are what shows that the replacement
 * behaves, because no test in this repository can.
 *
 * **The trap to know before reading a result here.** `inert` blocks
 * *user-initiated* activation and does not block a programmatic `.click()`. A
 * synthetic click landing on an inert element is the specification working, not
 * a defect — check these by actually pressing and actually tabbing.
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
        The page behind. A modal must make everything except itself unreachable — this text, the row
        below it, and the <code>agents</code> button in the chrome, not merely the other overlay
        layers.
      </p>
      <p style={{ padding: '0 var(--space-4)' }}>
        <button type="button">a row on the page</button>
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
    <Shell
      chrome={
        <>
          <strong>research-team</strong>
          <button type="button">agents</button>
        </>
      }
    >
      {/* A focusable element behind, and one in the layer beneath the top
          modal, so the confinement is checkable here rather than merely
          plausible: Tab must cycle within the confirm and reach neither. The
          first version of this story had nothing focusable behind it, which
          made it look like it demonstrated more than it did. */}
      <p style={{ padding: 'var(--space-4)' }}>
        The page behind. <button type="button">a row on the page</button>
      </p>
      <Overlay label="Session detail" modal>
        <div style={{ position: 'fixed', inset: '10% 10% auto 10%' }}>
          <Panel>
            <h3>Session detail</h3>
            <p>Beneath the confirm: dimmed, inert, unreachable by Tab.</p>
            <button type="button">a control in the drawer</button>
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

/** Focus in on open, focus back on close — with the real `Drawer`, not a
 *  hand-built panel.
 *
 * The other stories here compose bare `Overlay`s, which is right for showing
 * the host's own contract and wrong for this one: moving focus is `Drawer`'s
 * job, deliberately not the host's, and it changed shape in this migration. It
 * used to be a mount effect; `Overlay` renders `null` until its host's
 * container exists, so a mount effect read `null` off the ref and focused
 * nothing. It is a callback ref now.
 *
 * **What to check, in this order.** Tab to `open the worker feed` and press
 * Enter. Focus must land on `Close` — visibly, with a ring. Then press Escape.
 * Focus must return to `open the worker feed`, not to `<body>`: press Tab
 * immediately after and you should land on `after the row`, which is only true
 * if the return actually happened. Then do the whole thing again with the
 * mouse and check the *third* case: while the drawer is open, Tab repeatedly.
 * It must never reach `before the row`, `after the row`, or the chrome, no
 * matter how many times you press it.
 */
const DrawerFromARow = () => {
  const [open, setOpen] = useState(false)
  return (
    <Shell
      chrome={
        <>
          <strong>research-team</strong>
          <button type="button">a control in the chrome</button>
        </>
      }
    >
      <p style={{ padding: 'var(--space-4)', display: 'flex', gap: 'var(--space-3)' }}>
        <button type="button">before the row</button>
        <button type="button" onClick={() => setOpen(true)}>
          open the worker feed
        </button>
        <button type="button">after the row</button>
      </p>
      {open ? (
        <Drawer heading="Watching a worker" label="Worker detail" onClose={() => setOpen(false)}>
          <p style={{ padding: 'var(--space-4)' }}>
            The transcript. <button type="button">a control in the body</button>
          </p>
        </Drawer>
      ) : null}
    </Shell>
  )
}

export const FocusReturnsToTheRow: Story = { render: () => <DrawerFromARow /> }

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
