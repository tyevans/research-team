import clsx from 'clsx'

import { Button } from '../common/primitives.tsx'
import type { usePanes, PaneName } from './use-panes.ts'

export const Pane = ({
  name,
  title,
  label,
  meta,
  panes,
  children,
  footer,
  bodyClassName,
  raw = false,
}: {
  name: PaneName
  title: string
  label: string
  meta: string
  panes: ReturnType<typeof usePanes>
  children: React.ReactNode
  footer?: React.ReactNode
  bodyClassName?: string
  /** The child already renders its own `.pane-body` (it needs the scroll
   *  container to stick to the bottom), so this pane must not add a second. */
  raw?: boolean
}) => {
  const collapsed = panes.isCollapsed(name)
  return (
    <section
      className={clsx('pane', `pane-${name}`, collapsed && 'collapsed')}
      data-pane={name}
      aria-label={label}
    >
      <header className="pane-head">
        <Button
          tone="ghost"
          className="pane-toggle"
          aria-expanded={!collapsed}
          title={collapsed ? 'Expand this pane' : 'Collapse this pane'}
          onClick={() => panes.toggle(name)}
        >
          {collapsed ? '▸' : '◂'}
        </Button>
        <h2>{title}</h2>
        <span className="pane-meta">{meta}</span>
      </header>
      {raw ? children : <div className={clsx('pane-body', bodyClassName)}>{children}</div>}
      {footer}
    </section>
  )
}
