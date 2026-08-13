import { page } from 'vitest/browser'
import { render } from 'vitest-browser-react'
import { expect, it } from 'vitest'

import { FilePath } from '@domain/shared/file-path.ts'
import type { WorkspaceFile } from '@domain/workspace/workspace-file.ts'

import { FileList } from './FileList.tsx'

/** Whether the file list's focus ring is actually on screen, which is a
 *  measurement and therefore cannot be asked anywhere else.
 *
 * `FileList.test.tsx` holds everything jsdom can judge — the roles, the
 * `aria-activedescendant` wiring, the arrow-key routing — and can hold no more
 * of this: jsdom applies no stylesheet, so `getComputedStyle` on the focused
 * listbox reports the initial `outline: none` no matter which rules matched,
 * every rect is 0x0, and a ring drawn entirely outside a clipping ancestor is
 * indistinguishable there from one the reader can see.
 *
 * **Proved red.** Against the stylesheet before this change — global
 * `:focus-visible` from `tokens.css` and nothing scoped to `.files` — the first
 * test fails on its second assertion with the listbox's ring at
 * `-3..423 x -3..523` against a padding box of `0..420 x 0..176`: clipped on
 * every side, zero pixels visible. The second test fails outright, because
 * nothing drew on `.files` at all. The third fails because
 * `.file-row.selected` painted `--k-file` focused or not. The fourth fails
 * because `.files` suppressed its ring with `outline: none`.
 *
 * What breaks them again, stated so a future edit is recognisable rather than
 * mysterious: removing the `.files:has([role='listbox']:focus-visible)` rules
 * from `workspace.css`; changing its `outline-offset` back to a positive value
 * (test two, which is the whole finding); or giving the listbox in `FileList.tsx`
 * a class that reintroduces an outward ring of its own (test one).
 */

/** Enough rows to overflow `.files` and make its `overflow: auto` a real clip
 *  rather than a no-op — the unclipped case is not the one that shipped. */
const files: readonly WorkspaceFile[] = Array.from({ length: 20 }, (_, index) => ({
  path: FilePath.of(`src/module_${index}.py`),
  size: 1024 + index,
  revisions: 1,
}))

const OPEN = files[3]!.path

/** The wrapper is `.files` verbatim from `SessionView.tsx`. Mounting the
 *  listbox bare would measure a component the console never renders: the
 *  clipping ancestor is the entire subject. */
const Files = () => (
  <div className="files" style={{ width: '420px' }}>
    <FileList files={files} open={OPEN} historicalAt={null} onOpen={() => {}} onReopen={() => {}} />
  </div>
)

/** The outermost edge an element's outline reaches, in viewport coordinates.
 *  An outline is drawn `outline-offset` beyond the border box and is
 *  `outline-width` thick, so a negative offset pulls it inside. */
const ringBox = (element: HTMLElement) => {
  const style = getComputedStyle(element)
  const reach = parseFloat(style.outlineWidth) + parseFloat(style.outlineOffset)
  const box = element.getBoundingClientRect()
  return {
    drawn: style.outlineStyle !== 'none' && parseFloat(style.outlineWidth) > 0,
    top: box.top - reach,
    left: box.left - reach,
    right: box.right + reach,
    bottom: box.bottom + reach,
  }
}

/** What `overflow` actually clips: the padding box, not the border box. */
const clipBox = (element: HTMLElement) => {
  const box = element.getBoundingClientRect()
  return {
    top: box.top + element.clientTop,
    left: box.left + element.clientLeft,
    right: box.left + element.clientLeft + element.clientWidth,
    bottom: box.top + element.clientTop + element.clientHeight,
  }
}

const focusTheList = async () => {
  await render(<Files />)
  const listbox = page.getByRole('listbox').element() as HTMLElement
  const files_ = listbox.parentElement as HTMLElement
  listbox.focus()
  // Asserted rather than assumed. `:focus-visible` on a programmatic `focus()`
  // is a heuristic, and if this engine declined to match it every rule under
  // test would be inert while the geometry assertions below still passed.
  expect(listbox.matches(':focus-visible')).toBe(true)
  return { listbox, files: files_ }
}

it('keeps the file list from scrolling its own focus ring out of sight', async () => {
  const { listbox, files: scroller } = await focusTheList()

  // The precondition, asserted rather than assumed: with no overflow there is
  // no clip and this test would pass against the defect it exists to catch.
  expect(scroller.scrollHeight).toBeGreaterThan(scroller.clientHeight)

  // The finding. Anything the listbox draws for itself is drawn *inside* a
  // parent that clips at its padding box, so a ring reaching past that edge is
  // a ring nobody sees.
  const ring = ringBox(listbox)
  const clip = clipBox(scroller)
  if (ring.drawn) {
    expect(ring.top).toBeGreaterThanOrEqual(clip.top)
    expect(ring.left).toBeGreaterThanOrEqual(clip.left)
    expect(ring.right).toBeLessThanOrEqual(clip.right)
  }
})

it('draws the ring on the scroller, where nothing can clip it away', async () => {
  const { files: scroller } = await focusTheList()

  const ring = ringBox(scroller)
  expect(ring.drawn).toBe(true)

  // Inside its own border box, which is what makes the ring proof against
  // whatever the surrounding pane does with `overflow`. A positive
  // `outline-offset` here would put the console back one clip removed from the
  // bug this file was written for.
  const box = scroller.getBoundingClientRect()
  expect(ring.top).toBeGreaterThanOrEqual(box.top)
  expect(ring.left).toBeGreaterThanOrEqual(box.left)
  expect(ring.right).toBeLessThanOrEqual(box.right)
  expect(ring.bottom).toBeLessThanOrEqual(box.bottom)

  // And it is on screen: the scroller's own box is inside the viewport, so
  // unlike the listbox's it does not scroll away under the reader's arrows.
  expect(box.top).toBeGreaterThanOrEqual(0)
  expect(box.bottom).toBeLessThanOrEqual(window.innerHeight)
})

it('marks the row the arrows will move from, and only while they can', async () => {
  const { listbox } = await focusTheList()
  const selected = listbox.querySelector('.file-row.selected') as HTMLElement
  const focused = getComputedStyle(selected).borderLeftColor

  listbox.blur()
  expect(getComputedStyle(selected).borderLeftColor).not.toBe(focused)
})

it('gives the scroller itself a ring, because it can be focused', async () => {
  // This is the assumption that did not survive being measured. `.files`
  // carries no `tabIndex` and looked like an inert wrapper, which is why it
  // used to carry an `outline: none` that read as dead code — and Chromium
  // focuses a scroll container anyway. `scroller.focus()` below moves focus off
  // the listbox and onto it; deleting the suppression without replacing it
  // would have given the console a focusable element wearing the global
  // outward ring.
  const { listbox, files: scroller } = await focusTheList()
  scroller.focus()
  expect(document.activeElement).toBe(scroller)
  expect(document.activeElement).not.toBe(listbox)

  const ring = ringBox(scroller)
  expect(ring.drawn).toBe(true)
  const box = scroller.getBoundingClientRect()
  expect(ring.top).toBeGreaterThanOrEqual(box.top)
  expect(ring.left).toBeGreaterThanOrEqual(box.left)
})
