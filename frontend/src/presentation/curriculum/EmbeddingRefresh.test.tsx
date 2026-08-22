import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import type { DerivedFrom } from '@domain/knowledge/curriculum.ts'

import { EmbeddingRefresh } from './EmbeddingRefresh.tsx'

const derived = (over: Partial<DerivedFrom> = {}): DerivedFrom => ({
  entities: 40,
  relationships: 12,
  passages: 8,
  semanticEdges: 0,
  usedEmbeddings: false,
  truncated: false,
  ...over,
})

const show = (props: Partial<Parameters<typeof EmbeddingRefresh>[0]> = {}) =>
  render(
    <EmbeddingRefresh
      derivedFrom={derived()}
      pending={false}
      embedded={null}
      error={null}
      onRefresh={() => {}}
      {...props}
    />,
  )

describe('EmbeddingRefresh', () => {
  it('says plainly when the map used no embeddings at all', () => {
    // The state that is otherwise invisible: a projection clustered on the
    // graph alone renders exactly like one that used every signal.
    show()

    expect(screen.getByText(/clustered on the graph alone/i)).toBeInTheDocument()
  })

  it('offers the action even when embeddings were used', () => {
    // "Already embedded" is never "finished" — the graph keeps moving, and a
    // vector encodes the neighbourhood its entity had when it was extracted.
    show({ derivedFrom: derived({ usedEmbeddings: true, semanticEdges: 17 }) })

    expect(screen.getByRole('button', { name: /re-embed/i })).toBeEnabled()
    expect(screen.getByText(/17 links came from meaning/i)).toBeInTheDocument()
  })

  it('reports embedding nothing as a distinct outcome rather than success', () => {
    // Zero is what a build with embeddings switched off returns, and it is the
    // one result a reader would otherwise read as "it worked". A bare "done"
    // here would be a lie that costs somebody an afternoon.
    show({ embedded: 0 })

    expect(screen.getByText(/nothing was embedded/i)).toBeInTheDocument()
  })

  it('reports how many it wrote when it wrote some', () => {
    show({ embedded: 240 })

    expect(screen.getByText(/240 entities embedded/i)).toBeInTheDocument()
  })

  it('does not let a second run start while one is in flight', async () => {
    const onRefresh = vi.fn()
    show({ pending: true, onRefresh })

    const button = screen.getByRole('button')
    expect(button).toBeDisabled()
    await userEvent.click(button)
    expect(onRefresh).not.toHaveBeenCalled()
  })

  it('shows a failure rather than leaving the button looking idle', () => {
    show({ error: 'could not embed this project&rsquo;s entities' })

    expect(screen.getByText(/could not embed/i)).toBeInTheDocument()
  })
})
