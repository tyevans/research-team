import clsx from 'clsx'
import { useCallback, useEffect, useRef, useState } from 'react'

import { Tooltip } from './Tooltip.tsx'

/** Text that may be clipped, and can be read in full when it is.
 *
 * **The defect this closes.** Two places truncate an entity's words and
 * neither offers any way to read them: `EntityRef` ellipsises a label in a
 * narrow rail -- `entity-entityref--long-label-in-a-narrow-rail` is a story
 * that exists to show a question nobody can finish reading -- and
 * `EntityStatus` clipped its detail at a fixed `24ch` with a thousand pixels
 * free beside it. `EntityStatus`'s own docstring argues against the `title`
 * attribute, correctly, and then shipped something strictly worse than
 * `title`: at least `title` could be read.
 *
 * **Why a component rather than a rule in the stylesheet.** Whether text is
 * clipped is a measurement, not a property of the markup. CSS can truncate but
 * cannot tell anybody it did, and React cannot know without asking the
 * browser. So the wrapper is where the measurement lives, once, and the two
 * call sites get the answer rather than each growing a ref and an observer.
 *
 * **The tooltip is attached only while the text is actually clipped**, which
 * is the whole reason for the measurement. Attaching one unconditionally is
 * simpler and was rejected: the trigger goes in the tab order, so every
 * entity reference in the console -- seven sites, several of them in lists --
 * would become a focus stop offering a sentence the reader can already see.
 * A tab order padded with redundant stops is the cost, and it is paid by the
 * keyboard users this change is for.
 *
 * **`asChild` over a `<span>`, which `Tooltip` explicitly warns about.** The
 * warning is that such a trigger opens on hover and never on focus, because
 * nothing put it in the tab order. Here `tabIndex={0}` does, deliberately and
 * only while clipped. The alternative -- `Tooltip`'s default wrapper button --
 * cannot work at these two call sites: the truncation rules (`min-width: 0`,
 * `overflow: hidden`) live on the text element, and a wrapper would become the
 * flex item in its place, so the parent would size to the full text and
 * nothing would truncate at all. A focusable static element described by
 * `aria-describedby` is the standard shape for "there is more here"; a button
 * would promise a press that does nothing.
 *
 * **The cost, named because it is real and was accepted rather than missed:**
 * crossing the threshold remounts the span, so a reader focused on a clipped
 * label loses focus to the body if a pane is dragged wide enough to un-clip
 * it. Keeping one element would mean mounting the tooltip unconditionally and
 * suppressing it, which is the tab-order cost above paid in full to avoid a
 * case that needs a live resize of a focused label. If that turns out to
 * happen, `Tooltip` grows a prop and this comment says why it did.
 *
 * **Under jsdom this renders plain text and never a tooltip**, because
 * `scrollWidth` and `clientWidth` are both 0 there and nothing is ever
 * clipped. That is not a gap in the tests so much as the reason
 * `TruncatedText.browser.test.tsx` exists: the claim is a measurement, and it
 * is asserted in the one suite that can take one.
 */
export const TruncatedText = ({
  text,
  className,
}: {
  /** The full text, both rendered and -- when clipped -- explained. A string
   *  rather than `ReactNode` on purpose: the tooltip shows the same value the
   *  element does, and markup that had been clipped mid-tag could not be. */
  text: string
  /** The class carrying the truncation rules. It goes on the text element
   *  itself under `asChild`, so the element count and the flex layout are the
   *  same whether or not a tooltip is attached -- a layout that changed when
   *  text happened to get longer would be worse than the clipping. */
  className?: string
}) => {
  const node = useRef<HTMLSpanElement | null>(null)
  const [clipped, setClipped] = useState(false)

  /** The one-pixel slack is not superstition: `scrollWidth` and `clientWidth`
   *  are integers rounded from fractional layout, so a box sized exactly to
   *  its text reports a 1px difference often enough to matter -- which would
   *  attach a tooltip to text that is entirely visible, the exact noise the
   *  measurement exists to avoid. */
  const measure = (element: HTMLSpanElement) =>
    setClipped(element.scrollWidth > element.clientWidth + 1)

  /** A ref *callback* rather than a `useEffect` over a `useRef`, and this is
   *  the whole correctness of the component rather than a style preference.
   *
   * Attaching the tooltip changes the element's parents, so React unmounts the
   * span and mounts a new one. An effect keyed on `[text]` does not re-run for
   * that -- `text` did not change -- so its closure keeps observing the old,
   * now-detached node. A detached element measures 0 by 0, the observer fires
   * with that, and the component concludes the text is no longer clipped and
   * unwraps it: an oscillation that settles on *unclipped*, which is the
   * feature silently not working. It was diagnosed exactly that way, from a
   * browser test that measured 423 against 200 and found no tooltip.
   *
   * A ref callback runs again on every mount, so the observer always watches
   * the node that is actually on the page. React 19 runs the returned function
   * as its cleanup. */
  const attach = useCallback((element: HTMLSpanElement | null) => {
    node.current = element
    if (!element) return

    // The element's own box, because that is what the ellipsis responds to.
    // Watching the window instead would miss a pane being dragged narrower,
    // which is the case this console actually has. `observe` also fires once
    // immediately, which is the initial measurement.
    const observer = new ResizeObserver(() => measure(element))
    observer.observe(element)
    return () => observer.disconnect()
  }, [])

  // Longer or shorter text can cross the threshold without the box changing
  // size at all, so the observer never fires and only this sees it.
  useEffect(() => {
    if (node.current) measure(node.current)
  }, [text])

  const body = (
    <span
      ref={attach}
      // The focus ring is on the element only while it is focusable, and it is
      // spelled as utilities rather than a class in a stylesheet because the
      // stylesheet that would own it depends on the caller -- this component
      // is used from `entity.css`'s components today and is not theirs. The
      // values are the ones `components.css` already uses for every focusable
      // thing in the console; a focus stop nobody can see is not a focus stop.
      className={clsx(
        className,
        clipped &&
          'focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent',
      )}
      // The rule is right in general and wrong here, which is the only reason
      // to silence one. It exists because a focus stop that does nothing when
      // you press it is a trap for a keyboard user. This one does something:
      // arriving on it is what reveals the rest of the text, through
      // `aria-describedby`, and it is only in the tab order while there is
      // something to reveal. There is no ARIA role for "trigger of a tooltip"
      // to satisfy the rule honestly with; `role="button"` would satisfy it by
      // promising a press that does nothing.
      // eslint-disable-next-line jsx-a11y/no-noninteractive-tabindex
      tabIndex={clipped ? 0 : undefined}
    >
      {text}
    </span>
  )

  return clipped ? (
    <Tooltip explanation={text} asChild>
      {body}
    </Tooltip>
  ) : (
    body
  )
}
