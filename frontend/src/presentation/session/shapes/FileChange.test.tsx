import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { FileChange } from './FileChange.tsx'
import { fileChange } from './fixtures.ts'

describe('FileChange', () => {
  it('draws the proportion of the file the edit touched', () => {
    render(<FileChange artifact={fileChange} phase="settled" />)
    expect(screen.getByText('+34 −9')).toBeInTheDocument()
    // 43 of 212 lines.
    expect(screen.getByTestId('bar-fill')).toHaveStyle({ width: '20.28%' })
  })

  it('shows the actual before and after, not a thirty-character summary', () => {
    render(<FileChange artifact={fileChange} phase="settled" />)
    expect(screen.getByTestId('diff')).toHaveTextContent('− the old line')
    expect(screen.getByTestId('diff')).toHaveTextContent('+ the new line')
  })

  it('draws no diff block for a change that carried no text', () => {
    render(<FileChange artifact={{ ...fileChange, before: null, after: null }} phase="settled" />)
    expect(screen.queryByTestId('diff')).not.toBeInTheDocument()
    // By name: the header's argument is a tooltip trigger and therefore also a
    // button, so a bare role query here would report the path and not the
    // expander.
    expect(screen.queryByRole('button', { name: /full change/ })).not.toBeInTheDocument()
  })

  it('puts a long change behind an expander', () => {
    // Most edits are not the one the reader is looking for, and an unfolded
    // 300-line rewrite buries the reply the same way a 40-match result would.
    render(<FileChange artifact={{ ...fileChange, after: 'y'.repeat(600) }} phase="settled" />)
    expect(screen.getByRole('button', { name: /full change/ })).toBeInTheDocument()
  })
})
