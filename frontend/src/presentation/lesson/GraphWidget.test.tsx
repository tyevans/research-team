/** What jsdom *can* judge about the graph widget: which request it makes, and
 *  which of its states it draws.
 *
 * It cannot judge the one thing this widget's design turns on -- whether the
 * canvas has a height inside a markdown flow -- because jsdom lays nothing out
 * and applies no stylesheet. That assertion lives in
 * `GraphWidget.browser.test.tsx`, and writing it here as a comment is
 * precisely the failure CLAUDE.md names.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import type { ReactNode } from 'react'
import { expect, it, vi } from 'vitest'

import type { Container as AppContainer } from '@app/container.ts'
import { ContainerProvider } from '@app/container-context.tsx'
import type { AttemptsApi } from '@application/lesson/use-attempts.ts'
import { ProjectId } from '@domain/shared/identifier.ts'
import { componentBlock } from '@presentation/ask/ask-fixtures.ts'

import { GraphWidget } from './GraphWidget.tsx'

// The canvas is `React.lazy` over `react-force-graph-2d`; a real force
// simulation is not what any assertion here is about, and letting it mount
// would make every case wait on a d3 tick.
vi.mock('../research/GraphCanvas.tsx', () => ({
  GraphCanvas: ({ view }: { view: { nodes: readonly { id: string }[] } }) => (
    <div data-testid="graph-canvas" data-nodes={String(view.nodes.length)} />
  ),
}))

const PROJECT = ProjectId('11111111-1111-4111-8111-111111111111')

const attempts = {} as unknown as AttemptsApi

const hood = {
  root: { id: 'e1', name: 'Constantine', entityType: 'Person' },
  entities: [{ id: 'e2', name: 'Nicaea', entityType: 'Place' }],
  relationships: [{ source: 'e1', target: 'e2', relationshipType: 'convened' }],
}

const renderWidget = (
  data: Record<string, unknown>,
  {
    entities = [{ id: 'e1', name: 'Constantine', entityType: 'Person' }],
    neighborhood = vi.fn().mockResolvedValue(hood),
    // `null` and not `undefined` for "no project in scope". A destructuring
    // default fires on `undefined`, so `{ projectId: undefined }` restores
    // `PROJECT` and the no-project test silently exercises the ordinary path
    // instead -- measured on the `evidence` widget, where it did exactly that.
    projectId = PROJECT,
  }: {
    entities?: { id: string; name: string; entityType: string }[]
    neighborhood?: ReturnType<typeof vi.fn>
    projectId?: ProjectId | null
  } = {},
) => {
  // `graphs`, plural, is the key the container really exposes
  // (`container.ts:70`). The cast makes a wrong key typecheck cleanly and
  // resolve to nothing at runtime, so the symptom would be a widget stuck in
  // `loading` forever rather than a type error.
  const container = {
    graphs: { search: vi.fn().mockResolvedValue({ entities, truncated: false }), neighborhood },
  } as unknown as AppContainer
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const wrapper = ({ children }: { children: ReactNode }) => (
    <ContainerProvider container={container}>
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    </ContainerProvider>
  )
  return {
    neighborhood,
    ...render(
      <GraphWidget
        block={componentBlock({ type: 'graph', id: 'constantine-around', data })}
        attempts={attempts}
        {...(projectId ? { projectId } : {})}
      />,
      { wrapper },
    ),
  }
}

it('draws the neighbourhood of a name that resolved', async () => {
  const { neighborhood } = renderWidget({ entity: 'Constantine', depth: 1 })

  await waitFor(() => {
    expect(neighborhood).toHaveBeenCalledWith(PROJECT, 'e1', 1)
  })
  // The root arrives in its own field and is not repeated in `entities`, so a
  // merge that reads only `entities` draws the edges without the node. Two is
  // the count that catches it.
  await waitFor(() => {
    expect(screen.getByTestId('graph-canvas')).toHaveAttribute('data-nodes', '2')
  })
})

it('asks for the depth the author wrote', async () => {
  const { neighborhood } = renderWidget({ entity: 'Constantine', depth: 2 })

  await waitFor(() => {
    expect(neighborhood).toHaveBeenCalledWith(PROJECT, 'e1', 2)
  })
})

it('degrades to the plain name when the entity is not in the graph', async () => {
  const { neighborhood } = renderWidget({ entity: 'Theodosius', depth: 1 }, { entities: [] })

  await waitFor(() => {
    expect(screen.getByText(/not in this project['’]s graph/i)).toBeInTheDocument()
  })
  expect(neighborhood).not.toHaveBeenCalled()
  expect(screen.queryByRole('alert')).not.toBeInTheDocument()
})

it('renders the reference as prose with no project in scope, and fetches nothing', () => {
  const { neighborhood } = renderWidget({ entity: 'Constantine', depth: 1 }, { projectId: null })

  expect(screen.getByText('Constantine')).toBeInTheDocument()
  expect(neighborhood).not.toHaveBeenCalled()
})

it('keeps the reference readable when the neighbourhood 404s', async () => {
  // An inferred node's id comes from the ontology table and belongs to no
  // stored entity, so `/neighborhood` really does 404 for a name that
  // resolved. Prose, not a panel.
  renderWidget(
    { entity: 'Constantine', depth: 1 },
    { neighborhood: vi.fn().mockRejectedValue(new Error('404')) },
  )

  await waitFor(() => {
    expect(screen.getByText(/no neighbourhood/i)).toBeInTheDocument()
  })
  expect(screen.queryByRole('alert')).not.toBeInTheDocument()
})
