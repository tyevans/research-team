import { useCallback, useEffect, useState } from 'react'

import { notify } from '@application/notifications/toast-store.ts'
import { useContainer } from '@app/container-context.tsx'

export type PaneName = 'timeline' | 'workspace' | 'conversation'

export const PANES: readonly PaneName[] = ['timeline', 'workspace', 'conversation']

/** The collapsed rail's width. A fixed track rather than a min-width, so the
 *  space a collapsed pane gives up goes to the open ones — which is the entire
 *  point of collapsing. */
const RAIL = '34px'

/** Below this the stylesheet reflows the panes itself (two columns, then a
 *  single stack). An inline `grid-template-columns` would silently outrank
 *  those media queries, so above the breakpoint this hook owns the tracks and
 *  below it hands them back. */
const THREE_COLUMN = '(min-width: 1181px)'

/** Three panes on one screen means each is narrower than it wants to be, and
 *  which one you need is a function of what you are doing — reading a diff,
 *  following the log, or talking.
 *
 * Collapsing is per-pane, sticky across reloads, and refuses to hide the last
 * open pane: a view with nothing in it has no way back except a toggle you can
 * no longer see. */
export const usePanes = () => {
  const { preferences } = useContainer()
  const [collapsed, setCollapsed] = useState<readonly string[]>(() => preferences.collapsedPanes())
  const [wide, setWide] = useState(() => window.matchMedia?.(THREE_COLUMN).matches ?? true)

  // Crossing the breakpoint changes who owns the columns, so recompute there.
  useEffect(() => {
    const query = window.matchMedia?.(THREE_COLUMN)
    if (!query) return
    const onChange = () => setWide(query.matches)
    query.addEventListener('change', onChange)
    return () => query.removeEventListener('change', onChange)
  }, [])

  const toggle = useCallback(
    (name: PaneName) => {
      setCollapsed((current) => {
        const next = current.includes(name)
          ? current.filter((each) => each !== name)
          : [...current, name]
        if (next.length >= PANES.length) {
          notify('At least one pane has to stay open.', 'bad')
          return current
        }
        preferences.setCollapsedPanes(next)
        return next
      })
    },
    [preferences],
  )

  const isCollapsed = useCallback((name: PaneName) => collapsed.includes(name), [collapsed])

  const gridTemplateColumns = wide
    ? PANES.map((pane) =>
        collapsed.includes(pane)
          ? RAIL
          : pane === 'workspace'
            ? 'minmax(320px, 1.5fr)'
            : 'minmax(280px, 1.05fr)',
      ).join(' ')
    : undefined

  return { isCollapsed, toggle, gridTemplateColumns }
}
