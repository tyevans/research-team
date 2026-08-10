import { act, renderHook } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { useToasts } from '@application/notifications/toast-store.ts'
import { ContainerProvider } from '@app/container-context.tsx'
import type { Container } from '@app/container.ts'
import { InMemoryPreferenceStore } from '@infrastructure/storage/preference-store.ts'

import { usePanes } from './use-panes.ts'

/** **What these tests can and cannot see.** `vitest.setup.ts` stubs
 *  `matchMedia` because "real layout is Playwright's job, not jsdom's", and
 *  there is no Playwright here. So the assertions below are about the *string*
 *  this hook hands to `grid-template-columns` and about which media query it
 *  asks. Nothing observes a rendered track, a column width, or a reflow. A
 *  replacement that emits the same strings passes these tests whether or not
 *  the browser lays out the same way.
 *
 *  Only the ports this hook actually reaches for. The rest stay absent on
 *  purpose: a fake that implemented everything would hide which dependency the
 *  hook really has. */
const containerWith = (preferences: InMemoryPreferenceStore): Container =>
  ({ preferences }) as unknown as Container

const render = (preferences = new InMemoryPreferenceStore()) =>
  renderHook(() => usePanes(), {
    wrapper: ({ children }) => (
      <ContainerProvider container={containerWith(preferences)}>{children}</ContainerProvider>
    ),
  })

describe('usePanes', () => {
  it('starts with every pane open', () => {
    const { result } = render()
    expect(result.current.isCollapsed('timeline')).toBe(false)
    expect(result.current.isCollapsed('workspace')).toBe(false)
    expect(result.current.isCollapsed('conversation')).toBe(false)
  })

  it('collapses and expands one pane', () => {
    const { result } = render()
    act(() => result.current.toggle('timeline'))
    expect(result.current.isCollapsed('timeline')).toBe(true)

    act(() => result.current.toggle('timeline'))
    expect(result.current.isCollapsed('timeline')).toBe(false)
  })

  it('refuses to hide the last open pane, and says why', () => {
    const { result } = render()
    act(() => result.current.toggle('timeline'))
    act(() => result.current.toggle('workspace'))
    act(() => result.current.toggle('conversation'))

    // A view with nothing in it has no way back except a toggle you can no
    // longer see.
    expect(result.current.isCollapsed('conversation')).toBe(false)
    expect(useToasts.getState().toasts.at(-1)?.message).toBe('At least one pane has to stay open.')
  })

  it('persists the choice so a reload keeps the layout', () => {
    const preferences = new InMemoryPreferenceStore()
    const first = render(preferences)
    act(() => first.result.current.toggle('workspace'))

    const second = render(preferences)
    expect(second.result.current.isCollapsed('workspace')).toBe(true)
  })

  it('does not remember a refusal', () => {
    const preferences = new InMemoryPreferenceStore()
    const { result } = render(preferences)
    act(() => result.current.toggle('timeline'))
    act(() => result.current.toggle('workspace'))
    act(() => result.current.toggle('conversation'))

    // The refused toggle returns the previous state from the updater and never
    // reaches `setCollapsedPanes`. Writing it would be worse than the refusal it
    // already shows: a reload would come back to the all-closed layout the rule
    // exists to prevent, with nothing on screen having gone wrong.
    expect(preferences.collapsedPanes('session')).toEqual(['timeline', 'workspace'])
  })

  it('leaves the research rail’s stored layout alone', () => {
    const preferences = new InMemoryPreferenceStore()
    preferences.setCollapsedPanes('research', ['topics'])

    const { result } = render(preferences)
    act(() => result.current.toggle('timeline'))

    // The mirror of `RailPane.test.tsx`'s third case. Both views store a pane
    // layout and they are different sets of panes; one shared key meant the
    // second writer erased the first's. Collapsing the two groups back into one
    // fails here.
    expect(preferences.collapsedPanes('research')).toEqual(['topics'])
    expect(preferences.collapsedPanes('session')).toEqual(['timeline'])
  })

  describe('who owns the column tracks', () => {
    afterEach(() => vi.unstubAllGlobals())

    /** A `matchMedia` that can change its mind, so the breakpoint can be
     *  crossed rather than only started on either side of. Returns a fresh
     *  object per call, as the browser does, but shares one `matches` and one
     *  listener set -- the hook calls `matchMedia` twice, once in a lazy
     *  `useState` and once in the effect that subscribes. */
    const media = (initiallyWide: boolean) => {
      const listeners = new Set<() => void>()
      const asked: string[] = []
      let matches = initiallyWide
      vi.stubGlobal('matchMedia', (query: string) => {
        asked.push(query)
        return {
          get matches() {
            return matches
          },
          media: query,
          addEventListener: (_: string, fn: () => void) => void listeners.add(fn),
          removeEventListener: (_: string, fn: () => void) => void listeners.delete(fn),
        }
      })
      return {
        resizeTo: (wide: boolean) => {
          matches = wide
          for (const fn of listeners) fn()
        },
        get listening() {
          return listeners.size
        },
        get asked() {
          return asked
        },
      }
    }

    it('asks for the same boundary the stylesheet reflows at', () => {
      const viewport = media(true)
      render()

      // The one number in this file that is also written somewhere the tests
      // cannot see: `responsive.css:6` reflows at `max-width: 1180px`, so the
      // hook has to stop writing tracks at 1181px and not a pixel elsewhere.
      // Nothing else here would notice the query changing -- every other test
      // stubs the answer rather than the question, so a hook asking for
      // `(min-width: 900px)` would pass all of them while the inline style
      // outranked the two-column media query for 280px of width.
      //
      // This still only pins one half of the pair. The stylesheet's `1180` is
      // a literal in CSS and no test in this repository reads it.
      expect(viewport.asked).toContain('(min-width: 1181px)')
    })

    it('gives a collapsed pane a fixed rail, so the space goes to the open ones', () => {
      media(true)
      const { result } = render()
      act(() => result.current.toggle('timeline'))
      expect(result.current.gridTemplateColumns?.split(' ')[0]).toBe('34px')
    })

    it('sizes three open panes with the workspace widest', () => {
      media(true)
      const { result } = render()

      // Pinned whole rather than sampled. It does *not* pin the pane order:
      // the outer two tracks are identical, so reversing `PANES` produces the
      // same string. `gives each collapsed pane its own rail` is what holds the
      // order, and it holds it only because it collapses an asymmetric pair.
      //
      // Worth knowing before trusting this as the layout: `panes.css:73`
      // declares the same three tracks as `minmax(300px, 1.05fr) minmax(320px,
      // 1.5fr) minmax(300px, 1.15fr)` -- different minima on two tracks and a
      // different weight on the third. Above the breakpoint this inline value
      // wins; at or below it the stylesheet's does. So the two are not the same
      // layout, and this test pins only the half the hook owns.
      expect(result.current.gridTemplateColumns).toBe(
        'minmax(280px, 1.05fr) minmax(320px, 1.5fr) minmax(280px, 1.05fr)',
      )
    })

    it('gives each collapsed pane its own rail, in pane order', () => {
      media(true)
      const { result } = render()
      act(() => result.current.toggle('timeline'))
      act(() => result.current.toggle('workspace'))

      // A fixed track rather than a min-width is the whole point: the space two
      // collapsed panes give up goes to the one still open, instead of being
      // reserved for content nobody can see.
      //
      // The pair collapsed here is deliberately *adjacent* rather than the
      // outer two. Collapsing timeline and conversation reads better and pins
      // nothing about order, because the result is symmetric; this arrangement
      // is the only one in the file that fails when `PANES` is reordered.
      expect(result.current.gridTemplateColumns).toBe('34px 34px minmax(280px, 1.05fr)')
    })

    it('hands the columns back to the stylesheet below the three-column breakpoint', () => {
      // An inline grid-template would silently outrank the media queries that
      // reflow the panes at narrower widths.
      media(false)
      const { result } = render()
      act(() => result.current.toggle('timeline'))
      expect(result.current.gridTemplateColumns).toBeUndefined()
    })

    it('follows the window across the breakpoint without a remount', () => {
      const viewport = media(true)
      const { result } = render()
      act(() => result.current.toggle('timeline'))
      expect(result.current.gridTemplateColumns).toBe(
        '34px minmax(320px, 1.5fr) minmax(280px, 1.05fr)',
      )

      // Dragging a window narrow has to hand the tracks back, not just start
      // narrow. Without the `change` subscription the inline style written at
      // the wide size stays on the element and outranks every media query in
      // `responsive.css` -- the two-column and single-column layouts would
      // simply never apply to a window that was ever wide.
      act(() => viewport.resizeTo(false))
      expect(result.current.gridTemplateColumns).toBeUndefined()

      // And back, because the collapsed set has to survive the round trip.
      act(() => viewport.resizeTo(true))
      expect(result.current.gridTemplateColumns).toBe(
        '34px minmax(320px, 1.5fr) minmax(280px, 1.05fr)',
      )
    })

    it('stops listening to the window when it goes away', () => {
      const viewport = media(true)
      const { unmount } = render()
      expect(viewport.listening).toBe(1)

      unmount()
      expect(viewport.listening).toBe(0)
    })

    it('assumes three columns when the browser cannot answer', () => {
      vi.stubGlobal('matchMedia', undefined)
      const { result } = render()

      // `?? true`. The alternative default would hand the tracks to the
      // stylesheet, which reflows to two columns -- so a browser without
      // `matchMedia` would render the narrow layout on a wide screen and give
      // no sign of why. Assuming wide is wrong on a small screen in the same
      // way the media queries are already there to correct.
      expect(result.current.gridTemplateColumns).toBe(
        'minmax(280px, 1.05fr) minmax(320px, 1.5fr) minmax(280px, 1.05fr)',
      )
    })
  })
})
