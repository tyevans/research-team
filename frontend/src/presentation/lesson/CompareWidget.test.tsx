/** A table whose column heads are resolved against the project's graph.
 *
 * The resolution is the whole of what this adds over a markdown table, so the
 * cases that matter are the mixed ones: a table where one head resolved and
 * another did not must still be a readable table. A widget that refused to
 * draw because one name missed would be strictly worse than the prose it
 * replaced.
 *
 * This is the one widget that resolves *several* entities at once, so the
 * degraded states are per column rather than per block -- which is why "one
 * head missing leaves the rest intact" is a test here and is not one anywhere
 * else in this directory.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { ReactNode } from 'react'
import { expect, it, vi } from 'vitest'

import type { Container as AppContainer } from '@app/container.ts'
import { ContainerProvider } from '@app/container-context.tsx'
import type { AttemptsApi } from '@application/lesson/use-attempts.ts'
import { ProjectId } from '@domain/shared/identifier.ts'
import { componentBlock } from '@presentation/ask/ask-fixtures.ts'

import { CompareWidget } from './CompareWidget.tsx'

const PROJECT = ProjectId('11111111-1111-4111-8111-111111111111')

const block = (data: Record<string, unknown>) =>
  componentBlock({ type: 'compare', id: 'two-emperors', data })

const attempts = {} as unknown as AttemptsApi

/** Resolves whichever names are in `known`, and finds nothing for the rest --
 *  which is how a mixed table is built. */
const searchOver = (known: Record<string, string>) =>
  vi.fn().mockImplementation((_project: unknown, name: string) =>
    Promise.resolve({
      entities: known[name] ? [{ id: known[name], name, entityType: 'Person' }] : [],
      truncated: false,
    }),
  )

const DATA = {
  entities: ['Diocletian', 'Constantine'],
  rows: [
    { label: 'Reign', cells: ['284-305', '306-337'] },
    { label: 'Religious policy', cells: ['Persecution'] },
  ],
}

const renderWidget = (
  data: Record<string, unknown> = DATA,
  {
    search = searchOver({ Diocletian: 'e1', Constantine: 'e2' }),
    // `null` and not `undefined` for "no project in scope", copying
    // `EvidenceWidget.test.tsx`: a destructuring default fires on `undefined`,
    // so `{ projectId: undefined }` would restore `PROJECT` and the
    // no-project test would silently exercise the ordinary path instead.
    projectId = PROJECT,
  }: { search?: ReturnType<typeof vi.fn>; projectId?: ProjectId | null } = {},
) => {
  // `graphs`, plural, is the key the container really exposes -- the same key
  // `useEntityReference` destructures. The cast makes a wrong key typecheck
  // cleanly and resolve to nothing at runtime, so the symptom would be every
  // column head stuck in `loading` forever rather than a type error.
  const container = { graphs: { search } } as unknown as AppContainer
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const wrapper = ({ children }: { children: ReactNode }) => (
    <ContainerProvider container={container}>
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    </ContainerProvider>
  )
  return {
    search,
    user: userEvent.setup(),
    ...render(
      <CompareWidget
        block={block(data)}
        attempts={attempts}
        {...(projectId ? { projectId } : {})}
      />,
      { wrapper },
    ),
  }
}

it('draws a column per entity and a row per label', () => {
  renderWidget()

  const table = screen.getByRole('table')
  // Three columns: the row-label column, then one per entity.
  expect(within(table).getAllByRole('columnheader')).toHaveLength(3)
  expect(within(table).getAllByRole('rowheader')).toHaveLength(2)
  expect(within(table).getByText('284-305')).toBeInTheDocument()
})

it('shows the entity type of a head that resolved', async () => {
  renderWidget()

  // The resolution is what this adds over a markdown table, and the type is
  // how a reader sees it happened.
  await waitFor(() => {
    expect(screen.getAllByText('Person')).toHaveLength(2)
  })
})

it('keeps the table readable when one head is not in the graph', async () => {
  renderWidget(DATA, { search: searchOver({ Constantine: 'e2' }) })

  await waitFor(() => {
    expect(screen.getByText(/not in this project’s graph/i)).toBeInTheDocument()
  })
  // The rest of the table is intact -- red against a widget that refuses to
  // draw when any head misses.
  expect(screen.getByText('284-305')).toBeInTheDocument()
  expect(screen.getByRole('table')).toBeInTheDocument()
  expect(screen.queryByRole('alert')).not.toBeInTheDocument()
})

it('pads a short row rather than shifting its cells left', () => {
  // "Religious policy" has one cell and two entities. Red against a renderer
  // that maps over `cells`: the single value would land under Diocletian and
  // Constantine would silently lose a column, which reads as data rather
  // than as a gap.
  renderWidget()

  const row = screen.getByRole('row', { name: /Religious policy/ })
  expect(within(row).getAllByRole('cell')).toHaveLength(2)
})

it('links a resolved head into this project’s entity facet', async () => {
  // The registry's own summary tells the authoring model the browser "links
  // the ones it finds", and linking is the whole of what this adds over a
  // markdown table. Red against the first draft, which drew a bare span and
  // made that prompt text a false promise.
  renderWidget()

  const link = await screen.findByRole('link', { name: 'Diocletian' })
  expect(link).toHaveAttribute('href', `#/p/${PROJECT}/entity/e1`)
})

it('draws a picker inside an ambiguous column head, and links what is picked', async () => {
  // `compare` is the first widget to mount several frames at once, so it is
  // the first place `ambiguous` can stack: this header row is two pickers,
  // each a paragraph and a button list inside a `<th>`. Pinned rather than
  // suppressed -- a head with no picker can never be disambiguated, and an
  // unresolvable head can never be linked. Red against any later change that
  // quietly hides the picker in a header.
  const twins = vi.fn().mockImplementation((_project: unknown, name: string) =>
    Promise.resolve({
      entities: [
        { id: `${name}-a`, name, entityType: 'Person' },
        { id: `${name}-b`, name, entityType: 'Place' },
      ],
      truncated: false,
    }),
  )
  const { user } = renderWidget(DATA, { search: twins })

  // Four buttons: two candidates under each of the two heads. Awaited on the
  // buttons rather than on the headers, which are present from the first
  // render and would resolve while both frames are still `loading`.
  await waitFor(() => {
    expect(screen.getAllByRole('button')).toHaveLength(4)
  })
  const heads = screen.getAllByRole('columnheader')
  // Both entity heads carry a picker; the corner cell carries nothing.
  expect(within(heads[1] as HTMLElement).getAllByRole('button')).toHaveLength(2)
  expect(within(heads[2] as HTMLElement).getAllByRole('button')).toHaveLength(2)
  // Still a table, and still not an error.
  expect(screen.getByRole('table')).toBeInTheDocument()
  expect(screen.getByText('284-305')).toBeInTheDocument()
  expect(screen.queryByRole('alert')).not.toBeInTheDocument()

  await user.click(within(heads[1] as HTMLElement).getAllByRole('button')[0] as HTMLElement)

  expect(screen.getByRole('link', { name: 'Diocletian' })).toHaveAttribute(
    'href',
    `#/p/${PROJECT}/entity/Diocletian-a`,
  )
})

it('draws the table with no project in scope, and looks nothing up', () => {
  const { search } = renderWidget(DATA, { projectId: null })

  expect(screen.getByRole('table')).toBeInTheDocument()
  expect(screen.getByText('Diocletian')).toBeInTheDocument()
  expect(search).not.toHaveBeenCalled()
})
