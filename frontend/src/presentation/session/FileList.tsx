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
        title="No files."
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
    let next = selectedIndex
    if (event.key === 'ArrowDown') next = Math.min(selectedIndex + 1, files.length - 1)
    else if (event.key === 'ArrowUp') next = Math.max(selectedIndex - 1, 0)
    else if (event.key === 'Enter') next = selectedIndex < 0 ? 0 : selectedIndex
    else return

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
          <div
            key={file.path.value}
            className={clsx('file-row', selected && 'selected')}
            role="option"
            id={`file-${index}`}
            aria-selected={selected}
            onClick={() => onOpen(file.path)}
          >
            <span className="file-path" title={file.path.value}>
              {file.path.value}
            </span>
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
