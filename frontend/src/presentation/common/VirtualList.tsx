import { useVirtualizer } from '@tanstack/react-virtual'
import {
  Fragment,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  type ReactNode,
  type RefObject,
} from 'react'

/** Where a virtualized row has to put itself. */
export interface RowPosition {
  /** The row's index in `items`. The virtualizer reads this back off the DOM
   *  node to know which row it just measured, so it has to reach the element
   *  `measure` is given -- as `data-index`. */
  readonly index: number
  /** Offset from the top of the list, already corrected for where the list
   *  sits inside its scroll container. Apply it as `translateY`, not `top`:
   *  the virtualizer's own measurement expects a transform, and a `top` offset
   *  is counted twice as soon as a row reports a height that is not the
   *  estimate. */
  readonly top: number
  readonly measure: (element: HTMLElement | null) => void
}

/** One virtualized list, with the two lessons the previous two copies each
 *  learned separately.
 *
 * `docs/component-system-spec.md` §9 asks for this: "one wrapper preserving
 * `getItemKey`, re-measured `scrollMargin`, per-row measurement". Those three
 * are not a wish list, they are the three things that were got wrong once each
 * and fixed in one place while the other copy kept the bug or the risk of it.
 *
 * **Re-measured `scrollMargin`.** The virtualizer works in the *scroll
 * element's* coordinates, and a list is rarely at the top of its scroller --
 * `ProjectList` has a purpose line, an action bar and a heading above it.
 * Without the offset, the window of drawn rows is displaced by exactly that
 * much: invisible at three rows and drawing the wrong ones at fifty.
 * `DocumentBrowser` set no `scrollMargin` at all and was correct only because
 * its list happens to start at its scroller's top -- a latent bug that would
 * arrive with the first header anybody puts above it. Measuring on every
 * render, rather than accepting it as a prop, means neither caller can forget.
 *
 * **Per-row measurement with a fallback.** `ROW_HEIGHT` was once treated as
 * exact, and a title that wrapped to two lines -- most of them, in a 340px
 * rail -- drew over the row beneath. Every row reports its real height, and
 * the estimate only decides how far the scrollbar thinks it has to go before
 * a row has been drawn. The `|| estimate` is not defensive padding: jsdom
 * reports every height as 0, a measured 0 collapses the list to nothing and
 * takes the rows with it, and without this fallback no virtualized list in
 * this repository would be testable at all.
 *
 * **`getItemKey`.** Without it the virtualizer keys by index, so a list that
 * gains a row at the top re-keys every row below and React rebuilds the lot --
 * losing focus, scroll position and any open fold in them.
 *
 * The caller still renders and positions its own row element, through the
 * render prop. That is deliberate: both existing lists put the positioning on
 * the row itself rather than on a wrapper, and a wrapper element here would
 * have changed both their DOM shapes and any `>` selector aimed at them, for
 * no gain.
 */
export const VirtualList = <T,>({
  items,
  scrollRef,
  getKey,
  estimate,
  overscan = 6,
  className,
  children,
}: {
  items: readonly T[]
  /** The element that actually scrolls. Owned by the caller, because it is
   *  usually a pane body with other content in it rather than this list's own
   *  box. */
  scrollRef: RefObject<HTMLElement | null>
  getKey: (item: T, index: number) => string | number
  /** What a row is assumed to be until it has been drawn and measured. */
  estimate: (index: number) => number
  overscan?: number
  className?: string
  children: (item: T, position: RowPosition) => ReactNode
}) => {
  const listRef = useRef<HTMLUListElement>(null)
  const [listTop, setListTop] = useState(0)

  /** The scroll element, held in state rather than read from the ref at
   *  render.
   *
   * **This is the hazard the wrapper introduces, and it cost a debugging
   * session.** The scroller belongs to the *caller*, and this list is inside
   * it, so React has not attached the caller's ref yet when this component
   * first mounts -- a parent's ref is set after its children's. Reading
   * `scrollRef.current` inside `getScrollElement` therefore returned `null` on
   * the only render that mattered, the virtualizer had nothing to measure a
   * viewport against, and `getVirtualItems()` came back empty *forever*:
   * nothing re-rendered this component afterwards, so it never asked again.
   *
   * The symptom was a correctly sized `<ul>` -- the total height was right,
   * because that comes from the count and the estimate -- containing no rows
   * at all. A list that reserves exactly the right amount of space and draws
   * nothing in it.
   *
   * Neither original had this problem: each declared its virtualizer in the
   * same component that owned the ref, so its own effects ran after its own
   * refs were attached. Putting the virtualizer one level down is what created
   * the ordering, and holding the element in state is what closes it -- the
   * assignment below re-renders once, and that render has a scroller.
   *
   * The first attempt at this fix used `useLayoutEffect` and did not work,
   * which is the detail worth keeping: a layout effect is still too early. */
  const [scroller, setScroller] = useState<HTMLElement | null>(null)

  // `useEffect`, deliberately, and this is the whole of the ordering problem.
  // React commits bottom-up: for each fiber it attaches refs and then runs
  // *layout* effects, so a child's layout effect runs before its parent's ref
  // exists. Reading `scrollRef.current` there gets `null`, `setScroller(null)`
  // is a no-op against the initial `null`, nothing re-renders, and the list
  // never asks again. Passive effects run after the entire tree has committed,
  // by which point the caller's ref is attached.
  useEffect(() => {
    if (scrollRef.current !== scroller) setScroller(scrollRef.current)
  }, [scrollRef, scroller])

  // The offset stays in a layout effect: it is measured from this component's
  // own `<ul>`, whose ref *is* attached by then, and reading it before paint is
  // what stops a first frame drawn at the wrong offset. Every render rather
  // than once, because the offset changes when anything above the list grows
  // or collapses. Guarded by the equality check so it does not loop --
  // `useLayoutEffect` with no dependency array runs after every commit,
  // including the one this `setState` causes.
  //
  // The rule below wants `[]`, and `[]` would be wrong: it would measure once,
  // at mount, and never again -- which is the bug this effect exists to avoid,
  // since the offset moves whenever a fold opens above the list. The
  // `setState` is guarded by an equality check, so the "infinite chain of
  // updates" the rule warns about cannot happen: the second pass finds the
  // same number and does not write.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useLayoutEffect(() => {
    const element = listRef.current
    if (element)
      setListTop((current) => (current === element.offsetTop ? current : element.offsetTop))
  })

  // React Compiler cannot memoize `useVirtualizer`'s returned functions --
  // that is the library's documented shape, not a fault here -- so it skips
  // optimizing this component rather than risk a stale virtualizer. Confining
  // that trade to this file is a second, smaller reason for the wrapper: two
  // components opted out before, and now the ones that use it need not.
  // eslint-disable-next-line react-hooks/incompatible-library
  const virtualizer = useVirtualizer({
    count: items.length,
    getScrollElement: () => scroller,
    getItemKey: (index) => getKey(items[index]!, index),
    scrollMargin: listTop,
    estimateSize: estimate,
    measureElement: (element) => {
      const measured = element.getBoundingClientRect().height
      return measured || estimate(Number(element.getAttribute('data-index') ?? 0))
    },
    overscan,
  })

  return (
    <ul
      ref={listRef}
      className={className}
      style={{ height: virtualizer.getTotalSize(), position: 'relative' }}
    >
      {virtualizer.getVirtualItems().map((item) => {
        const row = items[item.index]
        if (row === undefined) return null
        return (
          // A keyed `Fragment` rather than a wrapper element: the row is the
          // caller's, and it is the thing the virtualizer measures and
          // positions, so nothing may come between it and the `<ul>`. This is
          // the one way React lets a key be attached from out here without
          // adding a node.
          <Fragment key={getKey(row, item.index)}>
            {children(row, {
              index: item.index,
              // The list's own offset comes back off, because `start` is in
              // the scroll container's coordinates and the row is positioned
              // within the list.
              top: item.start - virtualizer.options.scrollMargin,
              measure: virtualizer.measureElement,
            })}
          </Fragment>
        )
      })}
    </ul>
  )
}
