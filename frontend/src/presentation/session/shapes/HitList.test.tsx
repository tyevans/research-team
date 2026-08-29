import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'

import { HitList } from './HitList.tsx'
import { hitList } from './fixtures.ts'

const many = {
  ...hitList,
  total: 40,
  sources: Array.from({ length: 8 }, (_, index) => ({
    source_id: `s${index}`,
    title: `source ${index}`,
    label: null,
    char_count: 1000,
    total: 8 - index,
    hits: [{ start: 100 * index, end: 100 * index + 10, snippet: `snippet ${index}` }],
  })),
}

describe('HitList', () => {
  it('shows the source title, not the id', () => {
    render(<HitList artifact={hitList} phase="settled" />)
    expect(screen.getByText('manuscriptreport.com')).toBeInTheDocument()
    expect(
      screen.queryByText(/manuscriptreport-com-types-of-fictional-genres-42e281d8/),
    ).not.toBeInTheDocument()
  })

  it('places every hit against its own document’s length', () => {
    // The denominator is that source's `char_count`, not the longest document
    // in the result. A shared denominator would make a tick mean "9% of the
    // way into the biggest thing we found", which is not a fact about
    // anything. 1529 of 25784 is 5.93%.
    render(<HitList artifact={hitList} phase="settled" />)
    const ticks = screen.getAllByTestId('spark')[0]?.querySelectorAll('i')
    expect(ticks?.[0]).toHaveStyle({ left: '5.93%' })
  })

  it('sorts sources by how many matches they hold', () => {
    render(<HitList artifact={hitList} phase="settled" />)
    const names = screen.getAllByTestId('hit-source').map((node) => node.dataset['name'])
    expect(names).toEqual(['manuscriptreport.com', 'reedsy.com'])
  })

  it('caps at five sources and says how many are behind the expander', () => {
    // The cap does a second job beyond height: a forty-match result must not
    // bury the reply underneath it.
    render(<HitList artifact={many} phase="settled" />)
    expect(screen.getAllByTestId('hit-source')).toHaveLength(5)
    expect(screen.getByRole('button', { name: /all 40 matches/ })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /3 more sources/ })).toBeInTheDocument()
  })

  it('shows the rest when the expander is opened', async () => {
    render(<HitList artifact={many} phase="settled" />)
    await userEvent.click(screen.getByRole('button'))
    expect(screen.getAllByTestId('hit-source')).toHaveLength(8)
  })

  it('offers no expander when everything is already on screen', () => {
    // A disclosure over nothing is a control that punishes the reader for
    // trying it.
    render(<HitList artifact={hitList} phase="settled" />)
    expect(screen.queryByRole('button')).not.toBeInTheDocument()
  })

  it('names what the tool suppressed separately from what the card hid', () => {
    // "We showed you four of eleven" and "there were eleven" are different
    // facts. `suppressed` is what never reached the wire; the cap is what this
    // card chose not to draw, and a reader chasing a missing match needs to
    // know which happened.
    render(<HitList artifact={{ ...hitList, suppressed: 6 }} phase="settled" />)
    expect(screen.getByRole('button', { name: /6 suppressed/ })).toBeInTheDocument()
  })

  it('shows one representative snippet, not nineteen', () => {
    render(<HitList artifact={hitList} phase="settled" />)
    expect(screen.getByText(/Define the rules of your magic/)).toBeInTheDocument()
    expect(screen.queryByText(/a soft magic system/)).not.toBeInTheDocument()
  })
})
