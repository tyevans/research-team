import clsx from 'clsx'
import { useId, type CSSProperties, type ReactNode } from 'react'

import { useSplit } from './Split.tsx'

/** What a collapsed pane leaves on screen.
 *
 * Both forms exist in the console today and each is right where it is, which
 * is why this is an enum rather than a boolean: `rail` is the session view
 * above 1181px, a 34px column with the title turned on its side; `strip` is
 * the same panes below 820px and the research rail's `is-folded`, where the
 * title stays level because the pane is now a row. `research.css` says so in
 * its own comment -- "hence `is-folded` rather than reusing `collapsed`, whose
 * rules would rotate the title" -- which is two class names and two
 * stylesheets standing in for one parameter. */
export type CollapseTo = 'rail' | 'strip'

/** Who scrolls inside a pane.
 *
 * `body` is the common case and the default: the pane's body is the scroll
 * container and its content runs as long as it likes. `regions` is for a pane
 * holding two or more independently scrolling areas -- the session workspace
 * is a file list over a file viewer, each scrolling on its own -- where the
 * body must be a flex column that does *not* scroll, or the outer scroller
 * swallows the inner ones and neither behaves.
 *
 * `regions` also covers the case that was a separate `raw` prop in the session
 * view: a child that renders its own scroll container because it needs a ref
 * on it, as `Conversation` does to stick to the bottom. Two names for one
 * shape was the accident; the shape is "the body is a column, its children
 * scroll". */
export type PaneScroll = 'body' | 'regions'

export const Pane = ({
  id,
  label,
  meta,
  actions,
  footer,
  scroll = 'body',
  collapseTo = 'rail',
  minContent,
  unmountWhenCollapsed = false,
  collapsed: collapsedProp,
  onToggle: onToggleProp,
  children,
}: {
  id: string
  /** The visible heading, and the accessible name of the region. */
  label: string
  /** A count or a status, shown beside the heading. */
  meta?: ReactNode
  /** Controls belonging to this pane's header, beside the collapse toggle. */
  actions?: ReactNode
  /** Content pinned below the body rather than scrolling with it: a composer
   *  under a conversation, a live feed under a log.
   *
   *  A slot rather than something the caller puts at the end of `children`,
   *  because the whole point is that it is *outside* the scroll container.
   *  Inside, it scrolls away, which for a composer means a text box that
   *  leaves the screen as the conversation grows. */
  footer?: ReactNode
  scroll?: PaneScroll
  /** What this pane leaves behind when it collapses — **outside a `Split`**.
   *
   *  Inside one, the split's axis decides and this is not read. See the note
   *  on `form` below for why that is not the prop being ignored. */
  collapseTo?: CollapseTo
  /** The height, in pixels, below which this pane's content stops being worth
   *  showing.
   *
   *  The parameter that `research.css:70-88`'s fix should have been. An even
   *  split of a laptop viewport across three regions left each list showing
   *  three or four rows, "which is a scrollbar rather than a list"; 240px is
   *  roughly seven document rows. That fix is real and it is a literal in one
   *  stylesheet selected by two pane names, so nothing carries it to the
   *  session view's three panes or to the next pane anybody builds. Here it
   *  travels with the pane. */
  minContent?: number
  /** Drop the body from the tree entirely when collapsed, rather than hiding
   *  it.
   *
   *  Load-bearing rather than tidy, and the reason it is a declared property
   *  rather than the default: a virtualizer inside a hidden-but-mounted pane
   *  measures a zero-height scroll container and caches that, so the pane
   *  comes back empty. The cost of turning it on is that the body's own state
   *  -- scroll position, a half-typed filter -- does not survive a fold, which
   *  is why it is not the default. */
  unmountWhenCollapsed?: boolean
  /** Overrides the enclosing `Split`. Present so a `Pane` renders from props
   *  alone and can therefore have a story; a view inside a `Split` should not
   *  pass it. */
  collapsed?: boolean
  onToggle?: () => void
  children?: ReactNode
}) => {
  const split = useSplit()
  const bodyId = useId()

  const collapsed = collapsedProp ?? split?.collapsed.has(id) ?? false
  const onToggle = onToggleProp ?? (split ? () => split.toggle(id) : undefined)
  // Inside a `Split` the form follows the axis, both ways, and the caller's
  // `collapseTo` is not consulted at all. Once the panes stack a pane is a row,
  // so a rotated title would be lying about which way the layout runs;
  // `stacked` rather than `!wide` because between the two breakpoints these are
  // still columns and a collapsed one is still a rail.
  //
  // The other half of that used to be `: collapseTo`, and it drew the
  // Workbench's `conversation` as a 34px rail with a *level* title -- "▸ C" --
  // because `splitTemplate` gives every collapsed pane `RAIL_TRACK` while the
  // rotation lives only under `[data-collapse-to='rail']`. Two independent
  // decisions about one pane, which is the shape this whole primitive exists to
  // stop.
  //
  // Rejected: teaching `splitTemplate` a strip track, so `collapseTo` stayed
  // meaningful in a wide split. It would have to read a prop declared on the
  // *child* from the `tracks` array declared by the *view*, so the same fact
  // would be stated in two places that can disagree -- the disagreement this
  // module's header comment was written about. And a collapsed column wide
  // enough to read a level title gives back a fraction of the space that
  // collapsing is for.
  //
  // A standalone pane keeps what it was told: the research rail is three panes
  // in a flex column with no `Split` above them, and `strip` there is the only
  // thing that decides.
  const form: CollapseTo = split ? (split.stacked ? 'strip' : 'rail') : collapseTo

  return (
    <section
      className={clsx('lay-pane', collapsed && 'is-collapsed')}
      data-pane={id}
      data-collapse-to={form}
      aria-label={label}
      // `CSSProperties` has no room for a custom property, so the cast is
      // unavoidable rather than lazy — React writes the declaration through
      // `setProperty` and it works; only the type disagrees. Kept as narrow as
      // possible so it cannot hide a misspelled real property.
      style={
        minContent === undefined
          ? undefined
          : ({ '--pane-min-content': `${String(minContent)}px` } as CSSProperties)
      }
    >
      <header className="lay-pane-head">
        {onToggle ? (
          <button
            type="button"
            className="lay-pane-toggle"
            aria-expanded={!collapsed}
            aria-controls={bodyId}
            onClick={onToggle}
          >
            {/* A real sentence, not the glyph. `Pane.tsx` in the session view
                announces its toggles as "◂" and "▸" -- a bug `AgentWidget`
                names in a comment and routes around rather than through, so
                the correct behaviour exists in one component and the incorrect
                one in another. The glyph stays as decoration, hidden from the
                accessibility tree, and the name is text a screen reader can
                actually read out. */}
            <span aria-hidden="true">{collapsed ? '▸' : '◂'}</span>
            <span className="lay-visually-hidden">
              {collapsed ? `Expand ${label}` : `Collapse ${label}`}
            </span>
          </button>
        ) : null}
        <h2 className="lay-pane-title">{label}</h2>
        {meta === undefined ? null : <span className="lay-pane-meta">{meta}</span>}
        {actions === undefined ? null : <div className="lay-pane-actions">{actions}</div>}
      </header>

      {/* Three states, not two. Collapsed-and-unmounting renders no body at
          all; collapsed-and-keeping renders one the stylesheet hides, so its
          scroll position and any half-typed input survive; open renders it
          normally. `hidden` rather than a class, so the distinction is visible
          to assistive technology and to `:has()` rather than only to CSS. */}
      {collapsed && unmountWhenCollapsed ? null : (
        <div className="lay-pane-body" data-scroll={scroll} id={bodyId} hidden={collapsed}>
          {children}
        </div>
      )}

      {/* Outside the body, and folded away with it.
          `display: contents` on the wrapper, so a footer holding two siblings
          -- the session conversation pins an approvals list above a composer
          -- stays two flex items of the pane rather than becoming one box with
          two blocks inside it. The wrapper exists only to carry `hidden`,
          which is what keeps a folded pane's composer out of the accessibility
          tree as well as off the screen; the session view's rule folded it
          with `display: none` alone, so a screen reader still found it. */}
      {footer === undefined ? null : (
        <div className="lay-pane-footer" hidden={collapsed}>
          {footer}
        </div>
      )}
    </section>
  )
}
