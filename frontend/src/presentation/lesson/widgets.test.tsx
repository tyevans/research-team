import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { Prose } from './widgets.tsx'

/** `Prose` is the one component every widget's text goes through, which is
 *  why it is the one place worth fixing an empty state. `Markdown` prints a
 *  padded grey mono "(empty file)" for blank input -- right for a file, and
 *  drawn inside `compare` cells, `mcq` prompts, flashcard faces, evidence
 *  claims and stored definitions until this guard existed. */
describe('Prose', () => {
  it('draws nothing at all for text that is blank', () => {
    // Red against the build before the guard, which rendered
    // `<div class="empty">(empty file)</div>` for every one of these.
    for (const blank of [null, '', '   ', '\n\n']) {
      const { container, unmount } = render(<Prose text={blank} />)
      expect(container).toBeEmptyDOMElement()
      unmount()
    }
  })

  it('still renders text that says something', () => {
    // The other half, and not a formality: the cheapest way to make the test
    // above green is to return `null` unconditionally, and nothing else in
    // this file would notice.
    render(<Prose text="Actium removed Antony." />)

    expect(screen.getByText('Actium removed Antony.')).toBeInTheDocument()
  })
})
