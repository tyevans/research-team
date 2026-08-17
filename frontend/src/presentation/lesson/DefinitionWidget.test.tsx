/** The five states a `definition` renders, from a faked container.
 *
 * `text: null` is the fifth and the one worth reading the spec over: the
 * entity exists and the project cannot define it, which says the opposite of
 * `missing`. Folding them together would tell a reader an entity is absent
 * from a graph that contains it.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import type { ReactNode } from 'react'
import { expect, it, vi, type Mock } from 'vitest'

import type { AttemptsApi } from '@application/lesson/use-attempts.ts'
import type { Container as AppContainer } from '@app/container.ts'
import { ContainerProvider } from '@app/container-context.tsx'
import type { Definition, GraphNode } from '@domain/knowledge/graph.ts'
import type { ComponentBlock } from '@domain/lesson/document.ts'
import { ComponentId, ProjectId } from '@domain/shared/identifier.ts'

import { DefinitionWidget } from './DefinitionWidget.tsx'

const PROJECT = ProjectId('11111111-1111-4111-8111-111111111111')

const block = (data: Record<string, unknown>): ComponentBlock => ({
  kind: 'component',
  id: ComponentId('nicene'),
  type: 'definition',
  data,
  raw: '',
  lang: 'component:definition',
  unknown: false,
  errors: [],
  withheld: [],
  resolved: true,
})

/** Never called: a resolved component is not gradeable and nothing posts. It
 *  is passed because `RENDERERS` types every renderer with it. */
const attempts = {} as unknown as AttemptsApi

const definition = (over: Partial<Definition> = {}): Definition => ({
  text: 'The creed affirmed at Nicaea in 325.',
  citations: [{ sourceId: 'doc-1', start: 10, end: 40, atSeconds: null }],
  model: 'fake',
  generatedAt: '2026-01-01T00:00:00Z',
  stale: false,
  ...over,
})

const renderWidget = (
  data: Record<string, unknown>,
  {
    entities = [{ id: 'e1', name: 'Nicene Christianity', entityType: 'Concept' }],
    define = vi.fn().mockResolvedValue(definition()),
    projectId = PROJECT,
  }: {
    entities?: readonly GraphNode[]
    define?: Mock
    /** `| undefined` explicitly: `exactOptionalPropertyTypes` is on, so a
     *  caller passing `projectId: undefined` to reach the no-project case is
     *  a type error without it. */
    projectId?: ProjectId | undefined
  } = {},
) => {
  // `graphs`, not `graph`: the container exposes the repository under that
  // name and `useEntityReference` destructures it. A fake keyed `graph` type-
  // checks through the `as unknown as` cast and resolves nothing at runtime.
  const container = {
    graphs: { search: vi.fn().mockResolvedValue({ entities, truncated: false }) },
    definitions: { definition: define },
  } as unknown as AppContainer
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const wrapper = ({ children }: { children: ReactNode }) => (
    <ContainerProvider container={container}>
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    </ContainerProvider>
  )
  return {
    define,
    ...render(
      <DefinitionWidget
        block={block(data)}
        attempts={attempts}
        {...(projectId ? { projectId } : {})}
      />,
      { wrapper },
    ),
  }
}

it('shows the project definition and its citations once resolved', async () => {
  renderWidget({ entity: 'Nicene Christianity' })

  await waitFor(() => expect(screen.getByText(/creed affirmed at Nicaea/)).toBeInTheDocument())
  expect(screen.getByRole('link', { name: /doc-1/ })).toBeInTheDocument()
})

it('says the project cannot define an entity it does hold', async () => {
  const { define } = renderWidget(
    { entity: 'Nicene Christianity' },
    { define: vi.fn().mockResolvedValue(definition({ text: null })) },
  )

  await waitFor(() => expect(define).toHaveBeenCalled())
  // Distinct wording from `missing`, and the assertion that keeps it distinct:
  // this entity *is* in the graph, and saying otherwise would be false.
  expect(await screen.findByText(/no definition/i)).toBeInTheDocument()
  expect(screen.queryByText(/not in this project's graph/i)).not.toBeInTheDocument()
})

it('degrades to the plain name when the entity is not in the graph', async () => {
  const { define } = renderWidget({ entity: 'Theodosius' }, { entities: [] })

  await waitFor(() => expect(screen.getByText(/not in this project.s graph/i)).toBeInTheDocument())
  expect(screen.getByText('Theodosius')).toBeInTheDocument()
  expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  // The definition is never fetched for an entity with no id -- red against a
  // widget that calls the port with `null` and shows a network error.
  expect(define).not.toHaveBeenCalled()
})

it('renders the reference as prose when there is no project in scope', () => {
  const { define } = renderWidget({ entity: 'Nicene Christianity' }, { projectId: undefined })

  expect(screen.getByText('Nicene Christianity')).toBeInTheDocument()
  expect(define).not.toHaveBeenCalled()
})

it('offers a picker when two entities share the name', async () => {
  renderWidget(
    { entity: 'Constantine' },
    {
      entities: [
        { id: 'e1', name: 'Constantine', entityType: 'Person' },
        { id: 'e2', name: 'Constantine', entityType: 'Place' },
      ],
    },
  )

  await waitFor(() =>
    expect(screen.getByRole('button', { name: /Constantine.*Person/ })).toBeInTheDocument(),
  )
})

it('defines the candidate a reader picks out of the ambiguity', async () => {
  const { define } = renderWidget(
    { entity: 'Constantine' },
    {
      entities: [
        { id: 'e1', name: 'Constantine', entityType: 'Person' },
        { id: 'e2', name: 'Constantine', entityType: 'Place' },
      ],
    },
  )

  await waitFor(() => screen.getByRole('button', { name: /Place/ }))
  screen.getByRole('button', { name: /Place/ }).click()

  await waitFor(() => expect(define).toHaveBeenCalledWith(PROJECT, 'e2'))
})
