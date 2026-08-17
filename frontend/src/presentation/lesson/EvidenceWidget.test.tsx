/** A claim, and the passages a reader can check it against.
 *
 * The load-bearing case is the second one: the widget shows the offsets the
 * server *actually served*, not the ones the author asked for. The route
 * clamps rather than 422s, so an author who guessed past the end of a
 * document gets a nearby excerpt -- and a widget that printed the requested
 * range beside a different excerpt would be lying about what the reader is
 * looking at.
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

import { EvidenceWidget } from './EvidenceWidget.tsx'

const PROJECT = ProjectId('11111111-1111-4111-8111-111111111111')

const block = (data: Record<string, unknown>) =>
  componentBlock({ type: 'evidence', id: 'state-religion', data })

const attempts = {} as unknown as AttemptsApi

const renderWidget = (
  data: Record<string, unknown>,
  {
    read = vi.fn().mockResolvedValue({
      sourceId: 'doc-1',
      title: 'Theodosian Code',
      text: 'cunctos populos, quos clementiae nostrae regit imperium',
      start: 4120,
      end: 4175,
    }),
    // `null` and not `undefined` for "no project in scope". A destructuring
    // default fires on `undefined`, so `{ projectId: undefined }` restores
    // `PROJECT` and the no-project test silently exercises the ordinary path
    // instead -- measured: written that way it failed on `read` having been
    // called once, with the project it was supposed not to have.
    projectId = PROJECT,
  }: { read?: ReturnType<typeof vi.fn>; projectId?: ProjectId | null } = {},
) => {
  // `documents`, plural, is the key the container really exposes
  // (`container.ts:68`). The cast makes a wrong key typecheck cleanly and
  // resolve to nothing at runtime, so the symptom would be a widget stuck in
  // `isPending` forever rather than a type error.
  const container = { documents: { read } } as unknown as AppContainer
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const wrapper = ({ children }: { children: ReactNode }) => (
    <ContainerProvider container={container}>
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    </ContainerProvider>
  )
  return {
    read,
    ...render(
      <EvidenceWidget
        block={block(data)}
        attempts={attempts}
        {...(projectId ? { projectId } : {})}
      />,
      { wrapper },
    ),
  }
}

const CLAIM = 'Theodosius made Nicene Christianity the state religion in AD 380.'

it('shows the claim and the passage it rests on', async () => {
  const { read } = renderWidget({
    claim: CLAIM,
    sources: [{ source: 'doc-1', start: 4120, end: 4380 }],
  })

  expect(screen.getByText(CLAIM)).toBeInTheDocument()
  await waitFor(() => expect(screen.getByText(/cunctos populos/)).toBeInTheDocument())
  expect(read).toHaveBeenCalledWith(PROJECT, 'doc-1', { start: 4120, end: 4380 })
})

it('reports the offsets the server served, not the ones asked for', async () => {
  // The route clamps (`app.py:1635`) and answers with the real range. Red
  // against a widget that prints its own `start`/`end` from the YAML: the
  // reader would see "4120-4380" over an excerpt that is neither.
  renderWidget({ claim: CLAIM, sources: [{ source: 'doc-1', start: 4120, end: 99999 }] })

  await waitFor(() => expect(screen.getByText(/4120/)).toBeInTheDocument())
  expect(screen.getByText(/4175/)).toBeInTheDocument()
  expect(screen.queryByText(/99999/)).not.toBeInTheDocument()
})

it('keeps the claim readable when the passage cannot be fetched', async () => {
  // A source id the model invented is the ordinary failure here, and the
  // claim is still the answer's sentence. An error panel over a reader's own
  // prose is the degradation this feature refuses everywhere.
  renderWidget(
    { claim: CLAIM, sources: [{ source: 'doc-nope', start: 0, end: 10 }] },
    { read: vi.fn().mockRejectedValue(new Error('404')) },
  )

  expect(screen.getByText(CLAIM)).toBeInTheDocument()
  await waitFor(() => expect(screen.getByText(/could not be quoted/i)).toBeInTheDocument())
  expect(screen.queryByRole('alert')).not.toBeInTheDocument()
})

it('renders the claim alone with no project in scope, and fetches nothing', () => {
  const { read } = renderWidget(
    { claim: CLAIM, sources: [{ source: 'doc-1', start: 0, end: 10 }] },
    { projectId: null },
  )

  expect(screen.getByText(CLAIM)).toBeInTheDocument()
  expect(read).not.toHaveBeenCalled()
})

it('omits an absent offset from the range it asks for', async () => {
  // `start:` absent means "from the beginning", not `0`-and-`0`. Red against
  // a reader that defaults both to 0, which asks for an empty excerpt.
  const { read } = renderWidget({ claim: CLAIM, sources: [{ source: 'doc-1' }] })

  await waitFor(() => expect(read).toHaveBeenCalledWith(PROJECT, 'doc-1', {}))
})
