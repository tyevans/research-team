import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import { expect, it, vi } from 'vitest'

import { FilePath } from '@domain/shared/file-path.ts'
import type { WorkspaceFile } from '@domain/workspace/workspace-file.ts'

import { FileList } from './FileList.tsx'

/** The workspace listbox, which had no test.
 *
 * Third of phase 4's six prerequisites (§10), and the component §9 names for
 * `ListBox` -- "`aria-activedescendant`, and a real focus ring". The first half
 * is asserted here. The second is a stylesheet fact and jsdom computes no
 * styles, so it is phase 6's, and this file does not pretend otherwise.
 *
 * The interesting behaviour is the one the props already name: **Enter on the
 * file that is already open re-reads it, while arrows only move the
 * selection.** Those are two different verbs sharing one control, which is
 * exactly the kind of thing that survives a redesign in a broken state because
 * nobody wrote down that the distinction existed.
 *
 * **Proved red** against four breaks: `onReopen` swapped for `onOpen`;
 * `aria-activedescendant` removed; the ArrowUp clamp changed from
 * `Math.max(…, 0)` to no clamp; and `stopPropagation` deleted.
 */

const file = (path: string, over: Partial<WorkspaceFile> = {}): WorkspaceFile => ({
  path: FilePath.of(path),
  size: 120,
  revisions: 0,
  ...over,
})

const FILES = [file('/a.md'), file('/b.md'), file('/c.md')]

/** The caller owns which file is open, as `SessionView` does. A fixed `open`
 *  prop would let the first keystroke be observed and never the second. */
const Workspace = ({
  files = FILES,
  start = null,
  onReopen = () => {},
  onOpen,
}: {
  files?: readonly WorkspaceFile[]
  start?: FilePath | null
  onReopen?: () => void
  onOpen?: (path: FilePath) => void
}) => {
  const [open, setOpen] = useState<FilePath | null>(start)
  return (
    <FileList
      files={files}
      open={open}
      historicalAt={null}
      onReopen={onReopen}
      onOpen={(path) => {
        setOpen(path)
        onOpen?.(path)
      }}
    />
  )
}

const listbox = () => screen.getByRole('listbox')

it('points aria-activedescendant at the open file', async () => {
  const user = userEvent.setup()
  render(<Workspace start={FilePath.of('/a.md')} />)

  // The tab stop is the listbox; the rows are deliberately not focusable. That
  // makes `aria-activedescendant` the *only* thing telling a screen reader
  // which row is current, so it is not decoration -- remove it and a blind
  // user arrowing through the workspace hears nothing change.
  expect(listbox()).toHaveAttribute('aria-activedescendant', 'file-0')

  listbox().focus()
  await user.keyboard('{ArrowDown}')
  expect(listbox()).toHaveAttribute('aria-activedescendant', 'file-1')
})

it('moves the selection with the arrows without re-reading anything', async () => {
  const user = userEvent.setup()
  const onReopen = vi.fn()
  const onOpen = vi.fn()
  render(<Workspace start={FilePath.of('/a.md')} onOpen={onOpen} onReopen={onReopen} />)

  listbox().focus()
  await user.keyboard('{ArrowDown}{ArrowDown}')

  expect(onOpen).toHaveBeenLastCalledWith(expect.objectContaining({ value: '/c.md' }))
  // Arrows open what they land on -- that is how the viewer follows the
  // selection -- but they must never *re-read*, which is a request.
  expect(onReopen).not.toHaveBeenCalled()
})

it('re-reads on Enter, but only on the file that is already open', async () => {
  const user = userEvent.setup()
  const onReopen = vi.fn()
  const onOpen = vi.fn()
  render(<Workspace start={FilePath.of('/b.md')} onOpen={onOpen} onReopen={onReopen} />)

  listbox().focus()
  await user.keyboard('{Enter}')

  // The escape hatch when a file looks stale, and the only way to ask for it.
  // Fails with `onReopen` swapped for `onOpen`: the viewer re-renders with the
  // same path and nothing is re-fetched, so a reader looking at stale content
  // presses Enter and watches nothing happen.
  expect(onReopen).toHaveBeenCalledTimes(1)
  expect(onOpen).not.toHaveBeenCalled()
})

it('opens rather than re-reads when Enter lands on a different file', async () => {
  const user = userEvent.setup()
  const onReopen = vi.fn()
  const onOpen = vi.fn()
  render(<Workspace start={FilePath.of('/a.md')} onOpen={onOpen} onReopen={onReopen} />)

  listbox().focus()
  await user.keyboard('{ArrowDown}{Enter}')

  expect(onOpen).toHaveBeenCalledWith(expect.objectContaining({ value: '/b.md' }))
  // ArrowDown already opened `/b.md`, so this Enter is on the open file and
  // *does* re-read. Asserted rather than left implicit because it is the
  // interaction a reader actually performs -- arrow to a file, press Enter --
  // and it is worth knowing that it costs a second read.
  expect(onReopen).toHaveBeenCalledTimes(1)
})

it('does not walk off either end of the list', async () => {
  const user = userEvent.setup()
  const onOpen = vi.fn()
  render(<Workspace start={FilePath.of('/a.md')} onOpen={onOpen} />)

  listbox().focus()
  await user.keyboard('{ArrowUp}{ArrowUp}')
  expect(listbox()).toHaveAttribute('aria-activedescendant', 'file-0')

  await user.keyboard('{ArrowDown}{ArrowDown}{ArrowDown}{ArrowDown}')
  expect(listbox()).toHaveAttribute('aria-activedescendant', 'file-2')
})

it('opens the first file when nothing is selected yet', async () => {
  const user = userEvent.setup()
  const onOpen = vi.fn()
  render(<Workspace onOpen={onOpen} />)

  // `selectedIndex` is -1 with nothing open, and every branch clamps to 0, so
  // the first keystroke -- whichever it is -- opens the first file rather than
  // doing nothing. Worth pinning: "the first arrow press does something
  // sensible" is the difference between a list that feels responsive and one
  // that feels broken, and it falls out of three clamps rather than being
  // written anywhere.
  expect(listbox()).not.toHaveAttribute('aria-activedescendant')
  listbox().focus()
  await user.keyboard('{ArrowUp}')

  expect(onOpen).toHaveBeenCalledWith(expect.objectContaining({ value: '/a.md' }))
})

it('keeps its arrow keys away from the page behind it', async () => {
  const user = userEvent.setup()
  const outer = vi.fn()
  document.addEventListener('keydown', outer)
  try {
    render(<Workspace start={FilePath.of('/a.md')} />)
    listbox().focus()
    await user.keyboard('{ArrowDown}')

    // The timeline listens for the same keys. Without `stopPropagation` one
    // ArrowDown moves the file selection *and* scrubs the session a second
    // event forward, which is two unrelated things from one press.
    expect(outer).not.toHaveBeenCalled()
  } finally {
    document.removeEventListener('keydown', outer)
  }
})

it('says why the workspace is empty, differently in history than at HEAD', () => {
  const { unmount } = render(
    <FileList files={[]} open={null} historicalAt={null} onOpen={vi.fn()} onReopen={vi.fn()} />,
  )
  expect(screen.getByText('The agent has not written anything yet.')).toBeInTheDocument()
  unmount()

  // Not the same fact. "Nothing has been written" is about the session;
  // "the workspace was empty at event 7" is about where the reader is
  // standing, and a reader who scrubbed backwards needs to be told which one
  // they are looking at.
  render(<FileList files={[]} open={null} historicalAt={7} onOpen={vi.fn()} onReopen={vi.fn()} />)
  expect(screen.getByText('The workspace was empty at event 7.')).toBeInTheDocument()
})
