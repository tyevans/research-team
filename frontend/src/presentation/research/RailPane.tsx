import clsx from 'clsx'
import { useCallback, useState } from 'react'

import { useContainer } from '@app/container-context.tsx'

import { Button } from '../common/primitives.tsx'

/** The research rail's layout, remembered separately from the session view's. */
const GROUP = 'research'

export type RailPaneName = 'seeding' | 'topics' | 'documents'

/** Whether one rail pane is folded, sticky across reloads.
 *
 * Each pane owns its own copy rather than the view holding one hook for all
 * three, so `ResearchView` stays a markup-only component. That makes two
 * writers to one stored list, which is why a write re-reads the list instead
 * of using the state it rendered from -- otherwise folding two panes in a row
 * would store only the second.
 *
 * Unlike the session view there is no "at least one must stay open" rule: the
 * three heads stay on screen when folded, so every toggle remains reachable.
 */
const useFolded = (name: RailPaneName) => {
  const { preferences } = useContainer()
  const [folded, setFolded] = useState(() => preferences.collapsedPanes(GROUP).includes(name))

  const toggle = useCallback(() => {
    const next = !folded
    const others = preferences.collapsedPanes(GROUP).filter((each) => each !== name)
    preferences.setCollapsedPanes(GROUP, next ? [...others, name] : others)
    setFolded(next)
  }, [folded, name, preferences])

  return { folded, toggle }
}

/** A pane in the research rail, with a head that folds it away.
 *
 * Folding unmounts the body rather than hiding it. Hiding would leave the
 * document list's virtualizer measuring a zero-height scroller and restore it
 * scrolled to nothing; the cost is that expanding re-renders from the query
 * cache, and refetches if that entry has gone stale.
 */
export const RailPane = ({
  name,
  title,
  label,
  children,
}: {
  name: RailPaneName
  title: string
  label: string
  children: React.ReactNode
}) => {
  const { folded, toggle } = useFolded(name)
  return (
    <section className={clsx('pane', `pane-${name}`, folded && 'is-folded')} aria-label={label}>
      <header className="pane-head">
        <Button
          tone="ghost"
          className="pane-toggle"
          aria-expanded={!folded}
          /* Labelled as well as titled: the glyph is the whole of the button's
             content, so without this the control announces itself as "▾". */
          aria-label={folded ? `Expand ${title}` : `Fold ${title} away`}
          title={folded ? `Expand ${title}` : `Fold ${title} away`}
          onClick={toggle}
        >
          {folded ? '▸' : '▾'}
        </Button>
        <h2>{title}</h2>
      </header>
      {folded ? null : <div className="pane-body">{children}</div>}
    </section>
  )
}
