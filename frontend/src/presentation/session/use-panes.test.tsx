import { act, renderHook } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { useToasts } from '@application/notifications/toast-store.ts'
import { ContainerProvider } from '@app/container-context.tsx'
import type { Container } from '@app/container.ts'
import { InMemoryPreferenceStore } from '@infrastructure/storage/preference-store.ts'

import { usePanes } from './use-panes.ts'

/** Only the ports this hook actually reaches for. The rest stay absent on
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

  describe('who owns the column tracks', () => {
    afterEach(() => vi.unstubAllGlobals())

    const atWidth = (wide: boolean) =>
      vi.stubGlobal('matchMedia', (query: string) => ({
        matches: wide,
        media: query,
        addEventListener: () => {},
        removeEventListener: () => {},
      }))

    it('gives a collapsed pane a fixed rail, so the space goes to the open ones', () => {
      atWidth(true)
      const { result } = render()
      act(() => result.current.toggle('timeline'))
      expect(result.current.gridTemplateColumns?.split(' ')[0]).toBe('34px')
    })

    it('hands the columns back to the stylesheet below the three-column breakpoint', () => {
      // An inline grid-template would silently outrank the media queries that
      // reflow the panes at narrower widths.
      atWidth(false)
      const { result } = render()
      act(() => result.current.toggle('timeline'))
      expect(result.current.gridTemplateColumns).toBeUndefined()
    })
  })
})
