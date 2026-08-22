import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { GraphExportBar } from './GraphExportBar.tsx'

const show = (entity: string | null, entityName: string | null = null) =>
  render(
    <GraphExportBar
      graphUrl={(format, entityId) => `/graph.${format}?entity=${entityId ?? 'all'}`}
      entity={entity}
      entityName={entityName}
    />,
  )

describe('GraphExportBar', () => {
  it('offers all three formats', () => {
    show(null)

    expect(screen.getByRole('link', { name: /drawing \(\.html\)/i })).toHaveAttribute(
      'href',
      '/graph.html?entity=all',
    )
    expect(screen.getByRole('link', { name: /\.json/i })).toHaveAttribute(
      'href',
      '/graph.json?entity=all',
    )
    expect(screen.getByRole('link', { name: /\.graphml/i })).toHaveAttribute(
      'href',
      '/graph.graphml?entity=all',
    )
  })

  it('narrows every link to the selected entity, and says so', () => {
    // The mismatch worth avoiding: asking for an export while looking at one
    // node and receiving the whole project. The file opens and is not the
    // picture that was on screen.
    show('n7', 'Julius Caesar')

    expect(screen.getByText(/Julius Caesar/)).toBeInTheDocument()
    for (const format of ['html', 'json', 'graphml']) {
      expect(screen.getByRole('link', { name: new RegExp(format, 'i') })).toHaveAttribute(
        'href',
        `/graph.${format}?entity=n7`,
      )
    }
  })

  it('marks every link as a download', () => {
    // Without `download` the browser navigates to the HTML export instead of
    // saving it, which renders a page that looks like part of this console.
    show(null)

    for (const link of screen.getAllByRole('link')) {
      expect(link).toHaveAttribute('download')
    }
  })
})
