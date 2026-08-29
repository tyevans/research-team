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

  it('keeps the raw uri available without showing it', () => {
    // The title is what a reader scanning a run is looking for; the uri is what
    // a bug report needs, and only that. It reaches the reader through a
    // `Tooltip` rather than a `title` attribute -- see the S-D3 note in
    // `EntityList.test.tsx` for why, and why this asserts the trigger rather
    // than the sentence.
    render(<Excerpt artifact={excerpt} phase="settled" />)
    expect(screen.getByRole('button')).toHaveTextContent(
      'manuscriptreport.com · types of fictional genres',
    )
  })

  it('offers no expander for an excerpt already shown in full', () => {
    // By name, not by role: the header's argument is a tooltip trigger and
    // therefore also a button, so a bare `queryByRole('button')` here would be
    // green for the wrong reason -- it would fail even with an expander
    // correctly absent.
    render(<Excerpt artifact={excerpt} phase="settled" />)
    expect(screen.queryByRole('button', { name: /excerpt/ })).not.toBeInTheDocument()
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
