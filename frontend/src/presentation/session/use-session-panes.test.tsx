import { act, render, renderHook, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, describe, it } from 'vitest'

import { useToasts } from '@application/notifications/toast-store.ts'
import { ContainerProvider } from '@app/container-context.tsx'
import type { Container } from '@app/container.ts'
import { InMemoryPreferenceStore } from '@infrastructure/storage/preference-store.ts'
import { Pane } from '@presentation/layout/Pane.tsx'
import { Split } from '@presentation/layout/Split.tsx'
import { splitTemplate } from '@presentation/layout/split-tracks.ts'

import { buildContainer } from '../../test/container.ts'
import { SESSION_TRACKS, useSessionPanes } from './use-session-panes.ts'

/** The session view's pane layout, carried across the migration onto `Split`.
 *
 * This file is the surviving half of the characterization suite written before
 * the migration (#95). Each case that moved here pinned something about
 * `session/Pane.tsx` and `use-panes.ts`; the behaviour survived and the code
 * did not, so the assertion follows the behaviour. Two cases did not move and
 * both are recorded below rather than deleted quietly.
 *
 * **What these tests constrain.** The track values, the persistence, the
 * refusal, and the structure of the rendered panes. **What they do not.** Any
 * geometry: `vitest.setup.ts` stubs `matchMedia`, `ResizeObserver` and
 * `getBoundingClientRect` because "real layout is Playwright's job", and there
 * is no Playwright here. Nothing below observes a column width, a 34px rail, or
 * whether a folded pane is actually off the screen. The stub answers `false` to
 * every media query, so a rendered `Split` in these tests is always in its
 * below-the-breakpoint state and never writes a template at all; the template
 * is asserted through `splitTemplate` directly, which is why that function is
 * exported separately from the component that calls it.
 */

const containerWith = (preferences: InMemoryPreferenceStore): Container =>
  buildContainer({ preferences })

const wrapper =
  (preferences: InMemoryPreferenceStore) =>
  ({ children }: { children: React.ReactNode }) => (
    <ContainerProvider container={containerWith(preferences)}>{children}</ContainerProvider>
  )

describe('the session tracks', () => {
  it('are the values that were live before the migration, not the ones the stylesheet declared', () => {
    // The migration's single most important assertion, and it is here because
    // the two declarations it replaces disagreed: `panes.css:73` said
    // `minmax(300px, 1.05fr) minmax(320px, 1.5fr) minmax(300px, 1.15fr)` and
    // `use-panes.ts` wrote `280/1.05 320/1.5 280/1.05` inline. An inline style
    // outranks a stylesheet unconditionally, so the second set is what has
    // been on screen and the first has never applied on a wide window --
    // confirmed in a browser, not reasoned about.
    //
    // Taking the stylesheet's numbers while unifying the two would have been a
    // 20px change to two columns and a weight change to a third, arriving as a
    // side effect of a refactor nobody would think to look at for it. Whether
    // those are the better numbers is a separate argument; this pins the ones
    // that were live so making that change has to be deliberate.
    expect(splitTemplate({ tracks: SESSION_TRACKS, collapsed: new Set(), wide: true })).toBe(
      'minmax(280px, 1.05fr) minmax(320px, 1.5fr) minmax(280px, 1.05fr)',
    )
  })

  it('put the workspace in the middle and give a collapsed pane the rail', () => {
    // Order, pinned by collapsing an *adjacent* pair. The first draft of this
    // assertion in #95 collapsed the outer two, which is symmetric and passed
    // with the pane order reversed -- caught by mutation, not by reading.
    expect(
      splitTemplate({
        tracks: SESSION_TRACKS,
        collapsed: new Set(['timeline', 'workspace']),
        wide: true,
      }),
    ).toBe('var(--rail-w) var(--rail-w) minmax(280px, 1.05fr)')
  })
})

describe('useSessionPanes', () => {
  it('starts from what was stored, so a reload keeps the layout', () => {
    const preferences = new InMemoryPreferenceStore()
    preferences.setCollapsedPanes('session', ['workspace'])

    const { result } = renderHook(() => useSessionPanes(), { wrapper: wrapper(preferences) })
    expect([...result.current.collapsed]).toEqual(['workspace'])
  })

  it('leaves the research rail’s stored layout alone', () => {
    const preferences = new InMemoryPreferenceStore()
    preferences.setCollapsedPanes('research', ['topics'])

    const { result } = renderHook(() => useSessionPanes(), { wrapper: wrapper(preferences) })
    act(() => result.current.onCollapsedChange(new Set(['timeline'])))

    // The mirror of `RailPane.test.tsx`'s third case. Both views store a pane
    // layout, they are different sets of panes, and one shared key meant the
    // second writer erased the first's.
    expect(preferences.collapsedPanes('research')).toEqual(['topics'])
    expect(preferences.collapsedPanes('session')).toEqual(['timeline'])
  })

  it('says why a refusal happened', () => {
    const { result } = renderHook(() => useSessionPanes(), {
      wrapper: wrapper(new InMemoryPreferenceStore()),
    })
    act(() => result.current.onRefuse())

    // The wording is the view's, not the primitive's: `Split` refuses and
    // reports, and a layout component reaching for a toast store would be the
    // coupling the props-only rule exists to prevent.
    expect(useToasts.getState().toasts.at(-1)?.message).toBe('At least one pane has to stay open.')
  })
})

describe('the session panes, composed', () => {
  const Panes = () => {
    const panes = useSessionPanes()
    return (
      <Split
        id="session"
        label="Session panes"
        tracks={SESSION_TRACKS}
        collapsed={panes.collapsed}
        onCollapsedChange={panes.onCollapsedChange}
        onRefuse={panes.onRefuse}
      >
        <Pane id="timeline" label="Event log" footer={<p>the activity feed</p>}>
          <p>the log</p>
        </Pane>
        <Pane id="workspace" label="Workspace" scroll="regions">
          <p>the files</p>
        </Pane>
        <Pane id="conversation" label="Conversation" scroll="regions" footer={<p>the composer</p>}>
          <p>the messages</p>
        </Pane>
      </Split>
    )
  }

  const show = (preferences = new InMemoryPreferenceStore()) =>
    render(<Panes />, { wrapper: wrapper(preferences) })

  it('names each pane for the stylesheet and for a reader', () => {
    show()

    // `data-pane` is what `responsive.css`'s middle arrangement selects on --
    // `[data-pane='conversation']` wraps to its own row, and the `:has()` rules
    // that shrink a collapsed track name the other two. Emitting the wrong one
    // silently disables a stylesheet rule and shows up nowhere in the DOM.
    // These replace the `.pane-timeline` / `.pane-workspace` class names the
    // same rules used before the migration.
    for (const [id, label] of [
      ['timeline', 'Event log'],
      ['workspace', 'Workspace'],
      ['conversation', 'Conversation'],
    ] as const) {
      const pane = screen.getByRole('region', { name: label })
      expect(pane).toHaveAttribute('data-pane', id)
      expect(pane).toHaveClass('lay-pane')
    }
  })

  it('folds a pane away and remembers it, without unmounting what is inside', async () => {
    const preferences = new InMemoryPreferenceStore()
    show(preferences)

    await userEvent.click(screen.getByRole('button', { name: 'Collapse Event log' }))

    const pane = screen.getByRole('region', { name: 'Event log' })
    expect(pane).toHaveClass('is-collapsed')
    expect(preferences.collapsedPanes('session')).toEqual(['timeline'])

    // Hidden, not unmounted -- the session arm of a split the console answers
    // two ways. `RailPane` unmounts its body so a virtualizer does not measure
    // a zero-height scroller; these panes keep theirs so a scroll position
    // survives a fold, and `Timeline` and the live tail stay subscribed while
    // folded, which is the cost. `unmountWhenCollapsed` is the parameter that
    // now names the choice; this asserts the session's default is off.
    expect(screen.getByText('the log')).toBeInTheDocument()
  })

  it('folds the footer away with the body, and out of the accessibility tree', async () => {
    show()
    expect(screen.getByText('the composer')).toBeVisible()

    await userEvent.click(screen.getByRole('button', { name: 'Collapse Conversation' }))

    // The rule this replaces was `.pane.collapsed > *:not(.pane-head)`, which
    // set `display: none` and nothing else -- so a folded pane's composer was
    // off the screen and still reachable by a screen reader. `hidden` on the
    // wrapper removes it from both.
    expect(screen.getByText('the composer')).not.toBeVisible()
    expect(screen.getByText('the messages')).not.toBeVisible()
  })

  it('keeps the footer outside the body, where the scroll cannot take it', () => {
    const { container } = show()
    const footer = screen.getByText('the composer')

    // Structure, and the whole reason `footer` is a slot rather than the last
    // of `children`: inside the body it scrolls away with the conversation,
    // which for a composer means a text box that leaves the screen as the
    // conversation grows.
    expect(
      container.querySelector('[data-pane="conversation"] .lay-pane-body'),
    ).not.toContainElement(footer)
    expect(footer.closest('.lay-pane-footer')).toBeInTheDocument()
  })

  it('declares which panes hold their own scrollers', () => {
    show()

    // The workspace stacks a file list over a file viewer and the conversation
    // renders its own scroll container to stick to the bottom; both need a body
    // that is a column and does not scroll, or the outer scroller swallows the
    // inner ones. Two props in the old component -- `bodyClassName` for one and
    // `raw` for the other -- for one shape.
    const scrollOf = (id: string) =>
      screen
        .getByRole('region', { name: id })
        .querySelector('.lay-pane-body')
        ?.getAttribute('data-scroll')

    expect(scrollOf('Event log')).toBe('body')
    expect(scrollOf('Workspace')).toBe('regions')
    expect(scrollOf('Conversation')).toBe('regions')
  })

  it('refuses to fold the last open pane, and does not store the refusal', async () => {
    const preferences = new InMemoryPreferenceStore()
    show(preferences)

    await userEvent.click(screen.getByRole('button', { name: 'Collapse Event log' }))
    await userEvent.click(screen.getByRole('button', { name: 'Collapse Workspace' }))
    await userEvent.click(screen.getByRole('button', { name: 'Collapse Conversation' }))

    expect(screen.getByRole('region', { name: 'Conversation' })).not.toHaveClass('is-collapsed')
    expect(useToasts.getState().toasts.at(-1)?.message).toBe('At least one pane has to stay open.')

    // Structural now rather than a rule to remember: `Split` calls `onRefuse`
    // instead of `onCollapsedChange`, so the write is not on that path at all.
    // The hook this replaces had the refusal and the write inside one state
    // updater, one edit away from storing a layout with everything closed that
    // a reload would come back to.
    expect(preferences.collapsedPanes('session')).toEqual(['timeline', 'workspace'])
  })

  it('announces its toggles with a sentence', () => {
    show()

    // **This case inverts a pre-migration assertion, deliberately.** #95 pinned
    // the defect: `session/Pane.tsx`'s toggle rendered `◂`/`▸` as its only
    // child, so its accessible name was a glyph and the sentence lived in a
    // `title` that is not reliably announced. That test's own docstring said to
    // update it to assert the fix when the fix landed rather than delete it,
    // because a `VisuallyHidden` label dropped later would otherwise leave
    // nothing failing. This is that update.
    expect(screen.getByRole('button', { name: 'Collapse Event log' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '◂' })).toBeNull()
  })
})
