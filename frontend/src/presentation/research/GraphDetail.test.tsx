import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
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

/** Open the mentions fold, which is closed when the panel mounts.
 *
 * A helper rather than three lines repeated in every passage test: the fold is
 * a property of the panel, not of any one of the things behind it, and a test
 * about what a passage renders should not read as a test about a toggle. */
const openMentions = async () => {
  const user = userEvent.setup()
  await user.click(screen.getByRole('button', { name: /mentions/i }))
}

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

  await openMentions()

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

  await openMentions()

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

  await openMentions()

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

  await openMentions()

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
            citations: [{ sourceId, start: 5, end: 40, atSeconds: null }],
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

it("renders today's link, byte-for-byte, for a citation with no moment", async () => {
  // The overwhelming majority of citations: every text source has no locator
  // map, so `atSeconds` is `null` for almost every citation this feature will
  // ever render. A regression here would touch nearly every citation in the
  // product, which is why this pins the *exact* href rather than just
  // checking it lacks a `?t=`.
  const sourceId = '44444444-4444-4444-4444-444444444444'
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
            citations: [{ sourceId, start: 5, end: 40, atSeconds: null }],
          }),
        ),
      }),
    },
  )

  await screen.findByText(/Acme Corporation is a supplier/)
  const citationLink = screen.getByText(sourceId.slice(0, 8))
  expect(citationLink.closest('a')).toHaveAttribute(
    'href',
    projectHref(PROJECT, { facet: 'doc', id: sourceId }),
  )
})

it('links a citation at second zero to the seek query, not a bare link', async () => {
  // The falsy trap: `0` is a real citation at a source's first second, and
  // `citation.atSeconds ? …` would silently drop the query for exactly this
  // case. This is the test most likely to be skipped for that reason.
  const sourceId = '55555555-5555-5555-5555-555555555555'
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
            citations: [{ sourceId, start: 5, end: 40, atSeconds: 0 }],
          }),
        ),
      }),
    },
  )

  await screen.findByText(/Acme Corporation is a supplier/)
  const citationLink = screen.getByText(sourceId.slice(0, 8))
  expect(citationLink.closest('a')).toHaveAttribute(
    'href',
    `${projectHref(PROJECT, { facet: 'doc', id: sourceId })}?t=0`,
  )
})

it('links a citation carrying an offset to the seek query', async () => {
  const sourceId = '66666666-6666-6666-6666-666666666666'
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
            citations: [{ sourceId, start: 5, end: 40, atSeconds: 252 }],
          }),
        ),
      }),
    },
  )

  await screen.findByText(/Acme Corporation is a supplier/)
  const citationLink = screen.getByText(sourceId.slice(0, 8))
  expect(citationLink.closest('a')).toHaveAttribute(
    'href',
    `${projectHref(PROJECT, { facet: 'doc', id: sourceId })}?t=252`,
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

  await openMentions()

  expect(await screen.findByText(/Acme supplies/)).toBeInTheDocument()
  expect(screen.getByText(/generating a definition/i)).toBeInTheDocument()
})

it('keeps the mentions folded away until asked', async () => {
  // Bound to a local rather than read back off the repository object, which is
  // what `unbound-method` objects to: `usages.usages` detached from `usages` is
  // a method reference the lint cannot prove is safe to call.
  const usagesFn = vi.fn().mockResolvedValue([aUsage()])
  const usages = fakeUsages({ usages: usagesFn })
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

  await screen.findByText(/Acme Corporation is a supplier/)
  expect(screen.queryByText(/Acme supplies/)).not.toBeInTheDocument()
  // Not merely hidden: the fetch is gated on the fold, so a passage list
  // nobody asked for costs no BM25 query. This is the assertion that fails if
  // `enabled` is dropped and the section is only visually collapsed.
  expect(usagesFn).not.toHaveBeenCalled()

  await openMentions()

  expect(await screen.findByText(/Acme supplies/)).toBeInTheDocument()
  expect(usagesFn).toHaveBeenCalledTimes(1)
})

it('renders a passage as markdown rather than as its source characters', async () => {
  const usage = aUsage({
    text: 'ontifices, which Livy treats as\nMajor **prodigies** were expiated.',
  })
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

  await openMentions()

  // The emphasis as an element, not as asterisks. `findByText` on the whole
  // sentence would pass either way, because it matches the concatenated text
  // content -- so this asks for the tag.
  const emphasis = await screen.findByText('prodigies')
  expect(emphasis.tagName).toBe('STRONG')
})

it('starts a passage at a boundary rather than mid-sentence', async () => {
  const usage = aUsage({
    text: 'ontifices, which Livy treats as\nMajor prodigies were expiated.',
  })
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

  await openMentions()

  expect(await screen.findByText(/Major prodigies were expiated/)).toBeInTheDocument()
  // The half-sentence the chunker cut is gone, not merely pushed down.
  expect(screen.queryByText(/ontifices/)).not.toBeInTheDocument()
})
