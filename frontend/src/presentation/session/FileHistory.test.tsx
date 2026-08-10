import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, it, vi } from 'vitest'

import type { Container as AppContainer } from '@app/container.ts'
import { ContainerProvider } from '@app/container-context.tsx'
import type { WorkspaceRepository } from '@application/ports/repositories.ts'
import { EventIndex } from '@domain/session/event-index.ts'
import { FilePath } from '@domain/shared/file-path.ts'
import { SessionId } from '@domain/shared/identifier.ts'
import type { FileRevision } from '@domain/workspace/workspace-file.ts'

import { FileHistory } from './FileHistory.tsx'

/** The one thing this file asserts: a revision header can be opened without a
 *  mouse.
 *
 *  Written with the `jsx-a11y` fix it guards, not before it — the header was a
 *  bare `<div onClick>` until then, so there was no keyboard behaviour to test
 *  first. Proved red by reverting the fix: with `role`, `tabIndex` and
 *  `onKeyDown` removed the header is not reachable by Tab and Enter does
 *  nothing, and both assertions below fail.
 *
 *  Everything else `FileHistory` does — the query states, the diff subject
 *  rules — is left untested here on purpose. This is a targeted net for one
 *  behaviour change, not the coverage that directory is owed. */

const SESSION = SessionId('33333333-3333-3333-3333-333333333333')
const PATH = FilePath.of('notes/report.md')

const aRevision = (over: Partial<FileRevision> = {}): FileRevision => ({
  index: EventIndex(1),
  type: 'file_written',
  occurredAt: '2026-01-01T10:00:00Z',
  content: 'after\n',
  oldString: null,
  newString: null,
  replaceAll: null,
  ...over,
})

/** `readFile` is never reached on this path — the history list renders its own
 *  diffs from the revisions it already holds — so it throws rather than
 *  returning a plausible-looking empty string, which is the convention
 *  `TopicStatusDialog.test.tsx` uses. */
const container = (history: readonly FileRevision[]) =>
  ({
    workspace: {
      history: vi.fn(() => Promise.resolve(history)),
      readFile: vi.fn(() => {
        throw new Error('FileHistory should never call readFile()')
      }),
    } satisfies WorkspaceRepository,
  }) as unknown as AppContainer

const renderHistory = (revisions: readonly FileRevision[]) =>
  render(
    <ContainerProvider container={container(revisions)}>
      <QueryClientProvider
        client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
      >
        <FileHistory sessionId={SESSION} path={PATH} />
      </QueryClientProvider>
    </ContainerProvider>,
  )

it('folds a revision with the keyboard, not only with a mouse', async () => {
  const user = userEvent.setup()
  renderHistory([aRevision()])

  // Expanded by default, which is the component's own choice: a revision list
  // nobody opens is a list of timestamps.
  const header = await screen.findByRole('button', { expanded: true })

  await user.tab()
  expect(header).toHaveFocus()

  await user.keyboard('{Enter}')
  expect(header).toHaveAttribute('aria-expanded', 'false')

  // Space too, and it must not scroll the page while it is at it — which is
  // what the `preventDefault` in the handler is for.
  await user.keyboard(' ')
  expect(header).toHaveAttribute('aria-expanded', 'true')
})

it('still folds on click', async () => {
  const user = userEvent.setup()
  renderHistory([aRevision()])

  const header = await screen.findByRole('button', { expanded: true })
  await user.click(header)

  // The mouse route is the one that already worked; this is here so a future
  // rewrite into a real `<button>` cannot quietly drop it.
  expect(header).toHaveAttribute('aria-expanded', 'false')
})
