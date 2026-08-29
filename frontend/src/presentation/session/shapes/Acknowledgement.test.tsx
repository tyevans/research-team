import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { Acknowledgement } from './Acknowledgement.tsx'
import { acknowledgement } from './fixtures.ts'

describe('Acknowledgement', () => {
  it('renders one line with no expander', () => {
    // These are the stream's punctuation. Giving a write the same weight as a
    // search result is most of what makes the current feed read as noise, so
    // "there is nothing to open" is the design decision, not an omission.
    render(<Acknowledgement artifact={acknowledgement} phase="settled" />)
    expect(screen.queryByRole('button')).not.toBeInTheDocument()
    expect(screen.getByTestId('ack')).toHaveTextContent(
      'recorded a finding — hard vs soft magic systems · topic “worldbuilding”',
    )
  })

  it('marks a failed acknowledgement', () => {
    render(<Acknowledgement artifact={{ ...acknowledgement, ok: false }} phase="settled" />)
    expect(screen.getByTestId('ack')).toHaveAttribute('data-ok', 'false')
  })

  it('changes its glyph when the write did not succeed', () => {
    // The glyph is what a reader scanning the gutter sees; a failed write that
    // kept the tick would read as done.
    const { rerender } = render(<Acknowledgement artifact={acknowledgement} phase="settled" />)
    expect(screen.getByTestId('stream-glyph')).toHaveAttribute('data-tone', 'ok')
    rerender(<Acknowledgement artifact={{ ...acknowledgement, ok: false }} phase="settled" />)
    expect(screen.getByTestId('stream-glyph')).toHaveAttribute('data-tone', 'fail')
  })

  it('omits the detail rather than printing a bare separator', () => {
    render(<Acknowledgement artifact={{ ...acknowledgement, detail: null }} phase="settled" />)
    expect(screen.getByTestId('ack')).not.toHaveTextContent('·')
  })
})
