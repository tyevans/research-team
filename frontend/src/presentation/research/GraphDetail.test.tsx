import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import type { ReactElement, ReactNode } from 'react'
import { expect, it, vi } from 'vitest'

import type { Container as AppContainer } from '@app/container.ts'
import { ContainerProvider } from '@app/container-context.tsx'
import type { UsagesRepository } from '@application/ports/repositories.ts'
import type { GraphView, Usage } from '@domain/knowledge/graph.ts'
import { ProjectId } from '@domain/shared/identifier.ts'

import { OverlayHost } from '../layout/OverlayHost.tsx'
import { projectHref } from '../routing/routes.ts'
import { GraphDetail } from './GraphDetail.tsx'

const PROJECT = ProjectId('11111111-1111-1111-1111-111111111111')

const ADA = {
  id: 'ada',
  name: 'Ada Lovelace',
  entityType: 'Person',
}

/** One node, no edges: every test here is about the usages section, which
 *  renders whether or not the entity has any recorded relationships. */
const VIEW: GraphView = {
  nodes: [ADA],
  links: [],
  expanded: new Set(['ada']),
}

const aUsage = (over: Partial<Usage> = {}): Usage => ({
  sourceId: '22222222-2222-2222-2222-222222222222',
  start: 10,
  end: 40,
  text: 'Acme supplies the reagents used in the trial.',
  score: 0.8,
  ...over,
})

const fakeUsages = (over: Partial<UsagesRepository> = {}): UsagesRepository => ({
  usages: vi.fn().mockResolvedValue([]),
  ...over,
})

const renderDetail = (ui: ReactElement, parts: Partial<AppContainer> = {}) => {
  const container = { usages: fakeUsages(), ...parts } as unknown as AppContainer
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } })
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>
      <ContainerProvider container={container}>
        {/* `GraphDetail` closes on Escape through `useEscape`, which needs a
         *  host in scope -- see `OverlayHost.tsx`'s own docstring on why a
         *  `window` listener was the bug this replaced. */}
        <OverlayHost>{children}</OverlayHost>
      </ContainerProvider>
    </QueryClientProvider>
  )
  return render(ui, { wrapper })
}

const noop = () => {}

it('lists a passage with the document it came from', async () => {
  const usage = aUsage()
  renderDetail(
    <GraphDetail
      projectId={PROJECT}
      view={VIEW}
      selected="ada"
      onSelect={noop}
      onRemove={noop}
      onClose={noop}
    />,
    { usages: fakeUsages({ usages: vi.fn().mockResolvedValue([usage]) }) },
  )

  const passage = await screen.findByText(/Acme supplies/)
  expect(passage).toBeInTheDocument()
  // The document it came from, not just the passage -- the short id is this
  // corpus's own convention for naming a source inline (`CitationList` uses
  // the same truncation).
  expect(screen.getByText(usage.sourceId.slice(0, 8))).toBeInTheDocument()

  // A wrong href is invisible to `findByText` above -- this is what pins it.
  // The frontend's own `doc` facet, not the raw API route: that route answers
  // JSON, not a page a reader can land on, and `Selection`'s `PlainFacet` arm
  // has no `start`/`end` to carry today, so this asserts the id only rather
  // than a span this build cannot yet express.
  const link = passage.closest('a')
  expect(link).not.toBeNull()
  expect(link).toHaveAttribute('href', projectHref(PROJECT, { facet: 'doc', id: usage.sourceId }))
})

it('says nothing was found rather than showing an empty box', async () => {
  renderDetail(
    <GraphDetail
      projectId={PROJECT}
      view={VIEW}
      selected="ada"
      onSelect={noop}
      onRemove={noop}
      onClose={noop}
    />,
    { usages: fakeUsages({ usages: vi.fn().mockResolvedValue([]) }) },
  )

  expect(await screen.findByText(/no mentions/i)).toBeInTheDocument()
})

it('keeps showing the edge list while usages are still loading', async () => {
  // Never resolves within this test's lifetime -- the point is what is on
  // screen *before* the usages fetch settles, not after.
  const usages = fakeUsages({ usages: vi.fn(() => new Promise<Usage[]>(() => {})) })

  renderDetail(
    <GraphDetail
      projectId={PROJECT}
      view={VIEW}
      selected="ada"
      onSelect={noop}
      onRemove={noop}
      onClose={noop}
    />,
    { usages },
  )

  expect(screen.getByRole('heading', { name: /relationships/i })).toBeInTheDocument()
})
