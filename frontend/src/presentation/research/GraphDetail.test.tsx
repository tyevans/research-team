import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import type { ReactElement, ReactNode } from 'react'
import { expect, it, vi } from 'vitest'

import type { Container as AppContainer } from '@app/container.ts'
import { ContainerProvider } from '@app/container-context.tsx'
import type { DefinitionsRepository, UsagesRepository } from '@application/ports/repositories.ts'
import type { Definition, GraphView, Usage } from '@domain/knowledge/graph.ts'
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

const aDefinition = (over: Partial<Definition> = {}): Definition => ({
  text: 'Acme Corporation is a supplier of laboratory reagents.',
  citations: [],
  model: 'test-model',
  generatedAt: '2026-08-14T00:00:00Z',
  stale: false,
  ...over,
})

const fakeDefinitions = (over: Partial<DefinitionsRepository> = {}): DefinitionsRepository => ({
  definition: vi.fn().mockResolvedValue(aDefinition()),
  ...over,
})

const renderDetail = (ui: ReactElement, parts: Partial<AppContainer> = {}) => {
  const container = {
    usages: fakeUsages(),
    definitions: fakeDefinitions(),
    ...parts,
  } as unknown as AppContainer
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

it('shows the definition above the passages', async () => {
  const usage = aUsage({ text: 'Acme supplies the reagents used in the trial.' })
  renderDetail(
    <GraphDetail
      projectId={PROJECT}
      view={VIEW}
      selected="ada"
      onSelect={noop}
      onRemove={noop}
      onClose={noop}
    />,
    {
      definitions: fakeDefinitions({
        definition: vi
          .fn()
          .mockResolvedValue(aDefinition({ text: 'Acme Corporation is a supplier of reagents.' })),
      }),
      usages: fakeUsages({ usages: vi.fn().mockResolvedValue([usage]) }),
    },
  )

  const definition = await screen.findByText(/Acme Corporation is a supplier/)
  const passage = await screen.findByText(/Acme supplies/)
  // `compareDocumentPosition` over `getByText` rather than trusting section
  // order in the JSX: a heading swap that left the text in the right visual
  // place but the wrong DOM order would still read correctly to an eye but
  // wrongly to a screen reader walking the tree in source order.
  expect(
    definition.compareDocumentPosition(passage) & Node.DOCUMENT_POSITION_FOLLOWING,
  ).toBeTruthy()
})

it("renders the definition's citations, linked to the source document", async () => {
  const sourceId = '33333333-3333-3333-3333-333333333333'
  renderDetail(
    <GraphDetail
      projectId={PROJECT}
      view={VIEW}
      selected="ada"
      onSelect={noop}
      onRemove={noop}
      onClose={noop}
    />,
    {
      definitions: fakeDefinitions({
        definition: vi.fn().mockResolvedValue(
          aDefinition({
            citations: [{ sourceId, start: 5, end: 40 }],
          }),
        ),
      }),
    },
  )

  await screen.findByText(/Acme Corporation is a supplier/)
  // The backend refuses to store a definition citing nothing -- a definition
  // whose citations never reach the screen is indistinguishable from an
  // unsourced gloss, which is the exact failure this feature exists to
  // prevent. `getByText` alone would pass for a citation rendered with a
  // wrong or missing href, so this pins the link too.
  const citationLink = screen.getByText(sourceId.slice(0, 8))
  expect(citationLink.closest('a')).toHaveAttribute(
    'href',
    projectHref(PROJECT, { facet: 'doc', id: sourceId }),
  )
})

it('keeps old text visible and shows an updating indication for a stale definition', async () => {
  renderDetail(
    <GraphDetail
      projectId={PROJECT}
      view={VIEW}
      selected="ada"
      onSelect={noop}
      onRemove={noop}
      onClose={noop}
    />,
    {
      definitions: fakeDefinitions({
        definition: vi.fn().mockResolvedValue(aDefinition({ text: 'old text', stale: true })),
      }),
    },
  )

  expect(await screen.findByText('old text')).toBeInTheDocument()
  // Not blanked, not swapped for a spinner -- a reader who already saw this
  // text keeps seeing it, with a note that a newer one may be on the way.
  expect(screen.getByText(/updating/i)).toBeInTheDocument()
})

it('does not block the passages on the definition still loading', async () => {
  // Never resolves within this test's lifetime, the same device the
  // usages-loading test above uses -- the point is what the passages show
  // *before* the definition fetch settles.
  const definitions = fakeDefinitions({
    definition: vi.fn(() => new Promise<Definition>(() => {})),
  })
  const usage = aUsage({ text: 'Acme supplies the reagents used in the trial.' })

  renderDetail(
    <GraphDetail
      projectId={PROJECT}
      view={VIEW}
      selected="ada"
      onSelect={noop}
      onRemove={noop}
      onClose={noop}
    />,
    { definitions, usages: fakeUsages({ usages: vi.fn().mockResolvedValue([usage]) }) },
  )

  expect(await screen.findByText(/Acme supplies/)).toBeInTheDocument()
  expect(screen.getByText(/generating a definition/i)).toBeInTheDocument()
})
