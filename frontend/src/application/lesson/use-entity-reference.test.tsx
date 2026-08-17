/** Resolution as the widgets see it: a project, a reference, one of five states.
 *
 * The container is faked rather than the HTTP layer, matching every other hook
 * test in this suite -- what is under test is which state a page of results
 * becomes and when a fetch happens at all, not how a URL is spelled.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderHook, waitFor } from '@testing-library/react'
import type { ReactNode } from 'react'
import { expect, it, vi } from 'vitest'

import type { Container as AppContainer } from '@app/container.ts'
import { ContainerProvider } from '@app/container-context.tsx'
import type { GraphNode } from '@domain/knowledge/graph.ts'
import { ProjectId } from '@domain/shared/identifier.ts'

import { useEntityReference } from './use-entity-reference.ts'

const PROJECT = ProjectId('11111111-1111-4111-8111-111111111111')

const node = (id: string, name: string, entityType = 'Person'): GraphNode => ({
  id,
  name,
  entityType,
})

// `graphs`, not `graph`: the container names the port in the plural
// (`container.ts:70`), and a fake keyed on the singular would leave the hook
// reading `undefined` and throwing rather than searching.
const wrapperFor = (search: ReturnType<typeof vi.fn>) => {
  const container = { graphs: { search } } as unknown as AppContainer
  // `retry: false` so a rejected search reaches the assertion in one tick
  // rather than three -- the default backoff would make every failure case
  // here a multi-second test.
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return ({ children }: { children: ReactNode }) => (
    <ContainerProvider container={container}>
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    </ContainerProvider>
  )
}

it('resolves a name that matches exactly one entity', async () => {
  const search = vi
    .fn()
    .mockResolvedValue({ entities: [node('e1', 'Constantine')], truncated: false })
  const { result } = renderHook(
    () => useEntityReference(PROJECT, { entity: 'Constantine', entityId: null }),
    { wrapper: wrapperFor(search) },
  )

  await waitFor(() => expect(result.current.state).toBe('resolved'))
  expect(search).toHaveBeenCalledWith(PROJECT, 'Constantine')
})

it('is unavailable with no project in scope, and fetches nothing', () => {
  // A course file can carry a `definition` widget and be read from a session,
  // which has no project. Red against a hook that calls the port with
  // `undefined` -- the request would 404 on a URL with the word "undefined"
  // in it, and the reader would see a failure where the honest answer is
  // "this page cannot look that up".
  const search = vi.fn()
  const { result } = renderHook(
    () => useEntityReference(undefined, { entity: 'Constantine', entityId: null }),
    { wrapper: wrapperFor(search) },
  )

  expect(result.current).toEqual({ state: 'unavailable' })
  expect(search).not.toHaveBeenCalled()
})

it('short-circuits on entity_id without searching', () => {
  // The escape hatch is exact by construction, so spending a request to
  // confirm it would buy nothing. The synthesised node carries the author's
  // name and an empty `entityType`, which is what the frame renders.
  const search = vi.fn()
  const { result } = renderHook(
    () => useEntityReference(PROJECT, { entity: 'Constantine', entityId: 'e9' }),
    { wrapper: wrapperFor(search) },
  )

  expect(result.current).toEqual({
    state: 'resolved',
    entity: { id: 'e9', name: 'Constantine', entityType: '' },
  })
  expect(search).not.toHaveBeenCalled()
})

it('is missing when the search comes back empty', async () => {
  const search = vi.fn().mockResolvedValue({ entities: [], truncated: false })
  const { result } = renderHook(
    () => useEntityReference(PROJECT, { entity: 'Nobody', entityId: null }),
    { wrapper: wrapperFor(search) },
  )

  await waitFor(() => expect(result.current).toEqual({ state: 'missing' }))
})

it('is ambiguous when two entities share the name', async () => {
  const search = vi.fn().mockResolvedValue({
    entities: [node('e1', 'Constantine', 'Person'), node('e2', 'Constantine', 'Place')],
    truncated: false,
  })
  const { result } = renderHook(
    () => useEntityReference(PROJECT, { entity: 'Constantine', entityId: null }),
    { wrapper: wrapperFor(search) },
  )

  await waitFor(() => expect(result.current.state).toBe('ambiguous'))
})

it('is unavailable when the search rejects, not missing', async () => {
  // 503 (no graph read model wired) and "no such entity" say opposite things
  // about the corpus, and a reader told "not in this project's graph" by a
  // server that never looked has been told something false.
  const search = vi.fn().mockRejectedValue(new Error('503'))
  const { result } = renderHook(
    () => useEntityReference(PROJECT, { entity: 'Constantine', entityId: null }),
    { wrapper: wrapperFor(search) },
  )

  await waitFor(() => expect(result.current).toEqual({ state: 'unavailable' }))
})

it('is unavailable for an empty reference, and fetches nothing', () => {
  // `entity:` absent is a validation error the server already reported; the
  // widget still has to draw. Searching for "" would return the whole graph.
  const search = vi.fn()
  const { result } = renderHook(() => useEntityReference(PROJECT, { entity: '', entityId: null }), {
    wrapper: wrapperFor(search),
  })

  expect(result.current).toEqual({ state: 'unavailable' })
  expect(search).not.toHaveBeenCalled()
})
