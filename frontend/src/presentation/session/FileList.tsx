import clsx from 'clsx'
import { useRef } from 'react'

import type { WorkspaceFile } from '@domain/workspace/workspace-file.ts'
import type { FilePath } from '@domain/shared/file-path.ts'

import { EmptyState } from '../common/primitives.tsx'
import { bytes } from '../formatting/format.ts'

/** The workspace at the selected point.
 *
 * A listbox rather than a grid: a file row has exactly one action, and the
 * simplest role that fits is the one assistive technology handles best. */
export const FileList = ({
  files,
  open,
  historicalAt,
  onOpen,
  onReopen,
}: {
  files: readonly WorkspaceFile[]
  open: FilePath | null
  historicalAt: number | null
  onOpen: (path: FilePath) => void
  /** Enter on the already-open file re-reads it; arrows only move the
   *  selection. Re-reading is the escape hatch when a file looks stale. */
  onReopen: () => void
}) => {
  const list = useRef<HTMLDivElement | null>(null)

  if (files.length === 0) {
    return (
      <EmptyState
        heading="No files."
        detail={
          historicalAt !== null
            ? `The workspace was empty at event ${historicalAt}.`
            : 'The agent has not written anything yet.'
        }
      />
    )
  }

  const selectedIndex = files.findIndex((file) => file.path.equals(open))

  const onKeyDown = (event: React.KeyboardEvent<HTMLDivElement>) => {
    const next =
      event.key === 'ArrowDown'
        ? Math.min(selectedIndex + 1, files.length - 1)
        : event.key === 'ArrowUp'
          ? Math.max(selectedIndex - 1, 0)
          : event.key === 'Enter'
            ? Math.max(selectedIndex, 0)
            : null
    if (next === null) return

    event.preventDefault()
    event.stopPropagation()
    const target = files[next]
    if (!target) return
    if (!target.path.equals(open)) onOpen(target.path)
    else if (event.key === 'Enter') onReopen()

    list.current?.querySelector('.file-row.selected')?.scrollIntoView({ block: 'nearest' })
  }

  return (
    <div
      ref={list}
      tabIndex={0}
      role="listbox"
      id="files-listbox"
      aria-label="files"
      aria-activedescendant={selectedIndex >= 0 ? `file-${selectedIndex}` : undefined}
      onKeyDown={onKeyDown}
    >
      {files.map((file, index) => {
        const selected = file.path.equals(open)
        return (
          /* An `option` in an `aria-activedescendant` listbox is deliberately
             not focusable: the tab stop is the listbox above, which carries
             `tabIndex={0}` and the arrow-key handler, and selection is
             communicated by `aria-activedescendant` pointing at the row's id.
             That is one of the two patterns the ARIA practices allow, and the
             rule only models the other one (roving tabindex). Giving each row
             its own tab stop -- which is what the rule asks for -- would put
             every file in the tab order and is a regression, not a fix.
             `click-events-have-key-events` is the same misreading: the keyboard
             route is `onKeyDown` on the listbox. */
          /* eslint-disable-next-line jsx-a11y/click-events-have-key-events, jsx-a11y/interactive-supports-focus */
          <div
            key={file.path.value}
            className={clsx('file-row', selected && 'selected')}
            role="option"
            id={`file-${index}`}
            aria-selected={selected}
            onClick={() => onOpen(file.path)}
          >
            <span className="file-path">{file.path.value}</span>
            <span className="file-meta">
              {typeof file.revisions === 'number' && file.revisions > 0
                ? `r${file.revisions}  `
                : ''}
              {bytes(file.size)}
            </span>
          </div>
        )
      })}
    </div>
  )
}
