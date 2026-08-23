import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { ReactElement, ReactNode } from 'react'
import { describe, expect, it, vi } from 'vitest'

import type { Container as AppContainer } from '@app/container.ts'
import { ContainerProvider } from '@app/container-context.tsx'
import type { OntologyRepository } from '@application/ports/repositories.ts'
import { ProjectId } from '@domain/shared/identifier.ts'

import { OntologyPane } from './OntologyPane.tsx'

const project = ProjectId('11111111-1111-1111-1111-111111111111')

/** Every method throws until a test stubs it, matching this directory's other
 *  fakes: a pane that calls something it did not mean to fails loudly rather
 *  than resolving `undefined` and rendering an empty state that looks correct. */
const fakeOntology = (over: Partial<OntologyRepository> = {}): OntologyRepository => ({
  classes: vi.fn<OntologyRepository['classes']>().mockResolvedValue([]),
  ungrouped: vi.fn(() => {
    throw new Error('ungrouped was not stubbed for this test')
  }),
  discover: vi.fn(() => {
    throw new Error('discover was not stubbed for this test')
  }),
  ...over,
})

const wrapperFor = (
  ontology: OntologyRepository,
): (({ children }: { children: ReactNode }) => ReactElement) => {
  const container = { ontology } as unknown as AppContainer
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } })
  return ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>
      <ContainerProvider container={container}>{children}</ContainerProvider>
    </QueryClientProvider>
  )
}

const show = (ontology: OntologyRepository) =>
  render(<OntologyPane projectId={project} />, { wrapper: wrapperFor(ontology) })

describe('OntologyPane', () => {
  it('reads every ungrouped document, one at a time', async () => {
    // The assertion is that the calls *reached the repository*, with the right
    // arguments, and not that the button rendered or that nothing threw. This
    // whole feature shipped as a route and a repository method nothing called,
    // and a test asserting only on the rendered summary would pass against
    // exactly that build.
    const discover = vi.fn<OntologyRepository['discover']>().mockResolvedValue(1)
    const ontology = fakeOntology({
      ungrouped: vi.fn<OntologyRepository['ungrouped']>().mockResolvedValue(['a', 'b']),
      discover,
    })
    show(ontology)

    await userEvent.click(await screen.findByRole('button', { name: /read 2 documents/i }))

    await waitFor(() => expect(discover).toHaveBeenCalledTimes(2))
    expect(discover.mock.calls).toEqual([
      [project, 'a'],
      [project, 'b'],
    ])
  })

  it('separates a document it could not read from one that states nothing', async () => {
    // `null` and `0` arrive at the same callback and mean opposite things
    // about whether to press again. A pane that treated both as "done" would
    // report a finished corpus with a third of it unread.
    const ontology = fakeOntology({
      ungrouped: vi.fn<OntologyRepository['ungrouped']>().mockResolvedValue(['a', 'b', 'c']),
      discover: vi
        .fn<OntologyRepository['discover']>()
        .mockResolvedValueOnce(2)
        .mockResolvedValueOnce(0)
        .mockResolvedValueOnce(null),
    })
    show(ontology)

    await userEvent.click(await screen.findByRole('button', { name: /read 3 documents/i }))

    expect(await screen.findByText(/1 was not read/i)).toBeInTheDocument()
    expect(screen.getByText(/1 states no classes/i)).toBeInTheDocument()
  })

  it('keeps what a failed sweep already read, rather than reporting nothing happened', async () => {
    const ontology = fakeOntology({
      ungrouped: vi.fn<OntologyRepository['ungrouped']>().mockResolvedValue(['a', 'b']),
      discover: vi
        .fn<OntologyRepository['discover']>()
        .mockResolvedValueOnce(3)
        .mockRejectedValueOnce(new Error('the model timed out')),
    })
    show(ontology)

    await userEvent.click(await screen.findByRole('button', { name: /read 2 documents/i }))

    expect(await screen.findByText(/the model timed out/)).toBeInTheDocument()
    expect(screen.getByText(/press again to carry on/i)).toBeInTheDocument()
  })

  it('does not offer the sweep while the work list is still unknown', async () => {
    // A failed or pending read must not render as a finished corpus. The
    // component takes `null` for both, and this pins the pane passing it.
    const ungrouped = vi
      .fn<OntologyRepository['ungrouped']>()
      .mockRejectedValue(new Error('unwired'))
    show(fakeOntology({ ungrouped }))

    await waitFor(() => expect(ungrouped).toHaveBeenCalled())
    expect(screen.queryByText(/every extracted document has been read/i)).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /read/i })).not.toBeInTheDocument()
  })
})
