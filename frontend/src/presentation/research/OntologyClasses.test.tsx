import { render, screen, within } from '@testing-library/react'
import { expect, it } from 'vitest'

import type { OntologyClass } from '@domain/knowledge/ontology.ts'

import { OntologyClasses } from './OntologyClasses.tsx'

const href = (evidence: OntologyClass['evidence']) =>
  `/sources/${evidence.sourceId}?start=${evidence.start}&end=${evidence.end}`

const aClass = (over: Partial<OntologyClass> = {}): OntologyClass => ({
  id: 'c1',
  name: 'Difficulty',
  kind: 'ordered_scale',
  declaredCount: null,
  members: [],
  rejectedMembers: [],
  evidence: { sourceId: 'songs', start: 0, end: 66 },
  parentClassId: null,
  stale: false,
  complete: true,
  ...over,
})

it('draws an ordered scale in its stated order, with the positions visible', () => {
  // The ordinal is the information: a scale drawn without it is a bag with
  // extra steps, and the canvas cannot show it at all -- which is the entire
  // reason this view exists beside the graph.
  render(
    <OntologyClasses
      classes={[
        aClass({
          name: 'Rank',
          members: [
            { name: 'D rank', ordinal: 0 },
            { name: 'S rank', ordinal: 4 },
          ],
        }),
      ]}
      sourceHref={href}
    />,
  )

  // An `<ol>` because the order is meaningful -- a screen reader announces it
  // as a list of N items in sequence, which is the same claim the visual
  // ordering makes. Read in document order, its items must be the stated
  // order, each with its position beside it.
  const scale = document.querySelector('ol')
  expect(scale).not.toBeNull()
  const items = within(scale as HTMLElement).getAllByRole('listitem')
  expect(items.map((item) => item.textContent)).toEqual(['0D rank', '4S rank'])
})

it('draws an unordered set without positions', () => {
  // Numbering a bag would read a sequence into it that the document never
  // stated. Would pass with the scale branch deleted entirely, which is why
  // the ordered case above asserts the ordinal is present.
  render(
    <OntologyClasses
      classes={[
        aClass({
          name: 'Cult',
          kind: 'unordered_set',
          members: [
            { name: 'Official cults', ordinal: null },
            { name: 'Mystery cults', ordinal: null },
          ],
        }),
      ]}
      sourceHref={href}
    />,
  )

  expect(screen.getByText('Official cults')).toBeInTheDocument()
  // A `<ul>`, not an `<ol>`: the element itself is the claim that order
  // carries no meaning here, and it is the half a sighted reader cannot see.
  expect(document.querySelector('ol')).toBeNull()
  expect(screen.queryByText('0')).not.toBeInTheDocument()
})

it('shows the checksum and the rejections together', () => {
  // Separately, "2 of 6" is an unexplained gap and a rejection list is noise.
  // Together they are the reader's whole basis for telling an invented member
  // from a document genuinely short one -- opposite conclusions about whether
  // to trust the pass.
  render(
    <OntologyClasses
      classes={[
        aClass({
          declaredCount: 6,
          complete: false,
          members: [
            { name: 'EASY', ordinal: 0 },
            { name: 'MASTER', ordinal: 4 },
          ],
          rejectedMembers: [{ name: 'LEGEND', reason: 'not found in the document, verbatim' }],
        }),
      ]}
      sourceHref={href}
    />,
  )

  expect(screen.getByText('2 of 6 stated')).toBeInTheDocument()
  expect(screen.getByText('LEGEND')).toBeInTheDocument()
  expect(screen.getByText(/not found in the document/)).toBeInTheDocument()
})

it('links a class to the span of the document that stated it', () => {
  // A link into the source, not a quotation. Quoted text proves the model
  // wrote a sentence; opening the document proves the sentence is in it.
  render(<OntologyClasses classes={[aClass()]} sourceHref={href} />)

  expect(screen.getByRole('link', { name: /evidence in songs/i })).toHaveAttribute(
    'href',
    '/sources/songs?start=0&end=66',
  )
})

it('reports a member count rather than a checksum when the document stated none', () => {
  // Saying "1 of 1" where nothing was counted would look like a verification
  // and be nothing of the kind.
  render(
    <OntologyClasses
      classes={[aClass({ members: [{ name: 'EASY', ordinal: 0 }] })]}
      sourceHref={href}
    />,
  )

  expect(screen.getByText('1 member')).toBeInTheDocument()
  expect(screen.queryByText(/stated/)).not.toBeInTheDocument()
})

it('says when the graph moved under a class', () => {
  // Shown rather than hidden: the text still describes something, and a reader
  // deciding whether to trust it needs to know it may be out of date.
  render(<OntologyClasses classes={[aClass({ stale: true })]} sourceHref={href} />)

  expect(screen.getByText(/re-extracted since this was found/i)).toBeInTheDocument()
})

it('nests a subclass under its parent', () => {
  render(
    <OntologyClasses
      classes={[
        aClass({ id: 'version', name: 'Song version', kind: 'taxonomy' }),
        aClass({
          id: 'purchased',
          name: 'Purchased separately',
          kind: 'unordered_set',
          parentClassId: 'version',
          members: [{ name: 'Alternate Vocal Versions', ordinal: null }],
        }),
      ]}
      sourceHref={href}
    />,
  )

  const parent = screen.getByText('Song version').closest('li')
  expect(parent).not.toBeNull()
  expect(within(parent as HTMLElement).getByText('Purchased separately')).toBeInTheDocument()
})

it('invites a pass rather than reporting an error when nothing has been found', () => {
  // An empty screen is a real answer here, not a failure -- a project nobody
  // has run a pass on has no classes, and saying so as an invitation is the
  // difference between an empty state and a broken one.
  render(<OntologyClasses classes={[]} sourceHref={href} />)

  expect(screen.getByText(/no classes found yet/i)).toBeInTheDocument()
  expect(screen.getByText(/run a discovery pass/i)).toBeInTheDocument()
})
