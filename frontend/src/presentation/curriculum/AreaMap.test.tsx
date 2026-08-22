import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import type { Curriculum } from '@domain/knowledge/curriculum.ts'

import { AreaMap } from './AreaMap.tsx'

const curriculum = (over: Partial<Curriculum> = {}): Curriculum => ({
  areas: [
    {
      slug: 'the-principate',
      title: 'The Principate',
      summary: null,
      size: 12,
      truncatedMembers: true,
      members: [
        {
          entityId: 'e1',
          name: 'Augustus',
          entityType: 'person',
          centrality: 4,
          temporal: '27 BC',
        },
        {
          entityId: 'e2',
          name: 'Praetorian Guard',
          entityType: 'organisation',
          centrality: 2,
          temporal: null,
        },
      ],
    },
  ],
  path: {
    slug: 'complete',
    title: '',
    destination: null,
    areaSlugs: ['the-principate'],
    edges: [],
  },
  derivedFrom: {
    entities: 300,
    relationships: 40,
    passages: 900,
    semanticEdges: 0,
    usedEmbeddings: false,
    truncated: false,
  },
  ...over,
})

const href = (slug: string) => `#/p/x/area/${slug}`

describe('AreaMap', () => {
  it('shows the entities the graph put in an area, not only its title', () => {
    // The map's one job is to be falsifiable at a glance: a reader who knows
    // the subject can say "those two are the same area" only if they can see
    // what is in each. A plausible generated title fits a wrong cluster
    // perfectly, so a card showing only titles is a card that cannot be
    // checked -- and this test fails against exactly that card.
    render(<AreaMap curriculum={curriculum()} selected={null} areaHref={href} />)

    expect(screen.getByText('Augustus')).toBeInTheDocument()
    expect(screen.getByText('Praetorian Guard')).toBeInTheDocument()
  })

  it('says how many members it did not show', () => {
    // A card showing five of five and one showing five of sixty are different
    // claims about an area, and a reader counting rows cannot tell them apart.
    render(<AreaMap curriculum={curriculum()} selected={null} areaHref={href} />)

    expect(screen.getByText('+10 more')).toBeInTheDocument()
  })

  it('says what the projection was built from', () => {
    // A map over forty entities and one over four thousand draw identically.
    // Without this line a reader cannot tell a thin projection from a rich one,
    // or from a feature that never ran.
    render(<AreaMap curriculum={curriculum()} selected={null} areaHref={href} />)

    expect(screen.getByText(/300 entities/)).toBeInTheDocument()
    expect(screen.getByText(/40 stated relationships/)).toBeInTheDocument()
  })

  it('warns when the graph was larger than one read returns', () => {
    render(
      <AreaMap
        curriculum={curriculum({
          derivedFrom: { ...curriculum().derivedFrom, truncated: true },
        })}
        selected={null}
        areaHref={href}
      />,
    )

    expect(screen.getByText(/cover part of it/)).toBeInTheDocument()
  })

  it('marks the selected area for assistive technology, not only in colour', () => {
    render(<AreaMap curriculum={curriculum()} selected="the-principate" areaHref={href} />)

    expect(screen.getByRole('link', { name: /Augustus/ })).toHaveAttribute('aria-current', 'true')
  })

  it('tells an empty project to extract, and a sparse one why it is sparse', () => {
    // Two different empty states wanting two different next actions. Telling a
    // reader with 300 unconnected entities to "add sources and extract" is
    // advice that will not help, and it is the advice a single empty state
    // would give them.
    const { unmount } = render(
      <AreaMap
        curriculum={curriculum({
          areas: [],
          derivedFrom: { ...curriculum().derivedFrom, entities: 0 },
        })}
        selected={null}
        areaHref={href}
      />,
    )
    expect(screen.getByText(/graph is empty/)).toBeInTheDocument()
    unmount()

    render(<AreaMap curriculum={curriculum({ areas: [] })} selected={null} areaHref={href} />)
    expect(screen.getByText(/too few are connected/)).toBeInTheDocument()
  })
})
