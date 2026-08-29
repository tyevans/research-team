import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { Excerpt } from './Excerpt.tsx'
import { excerpt } from './fixtures.ts'

describe('Excerpt', () => {
  it('shows which span of the document was read', () => {
    // An agent quoting 9% of a document from near its start is making a
    // materially different claim from one that read the whole thing, and
    // `@1529-3872 of 25784` inside a monospace paragraph does not distinguish
    // them at a glance.
    render(<Excerpt artifact={excerpt} phase="settled" />)
    expect(screen.getByText(/1\.5k–3\.9k of 25\.8k/)).toBeInTheDocument()
    const ruler = screen.getByTestId('ruler-fill')
    expect(ruler).toHaveStyle({ width: '9.09%' })
    expect(ruler).toHaveStyle({ marginLeft: '5.93%' })
  })

  it('keeps the raw id and uri available without showing them', () => {
    // The title is what a reader scanning a run is looking for; the id is what
    // a bug report needs, and only that.
    render(<Excerpt artifact={excerpt} phase="settled" />)
    expect(screen.getByTitle('https://manuscriptreport.com/genres')).toHaveTextContent(
      'manuscriptreport.com · types of fictional genres',
    )
  })

  it('offers no expander for an excerpt already shown in full', () => {
    render(<Excerpt artifact={excerpt} phase="settled" />)
    expect(screen.queryByRole('button')).not.toBeInTheDocument()
  })

  it('truncates a long excerpt behind an expander', () => {
    const long = { ...excerpt, text: 'x'.repeat(900) }
    render(<Excerpt artifact={long} phase="settled" />)
    expect(screen.getByRole('button', { name: /full excerpt/ })).toBeInTheDocument()
  })

  it('draws a zero-length ruler rather than dividing by zero', () => {
    // `char_count` is 0 on a source whose text never loaded. `NaN%` is not a
    // width, so the fill would silently keep whatever the previous render gave
    // it -- an excerpt bar that means nothing and looks like one that does.
    render(<Excerpt artifact={{ ...excerpt, char_count: 0 }} phase="settled" />)
    expect(screen.getByTestId('ruler-fill')).toHaveStyle({ width: '0%' })
  })
})
