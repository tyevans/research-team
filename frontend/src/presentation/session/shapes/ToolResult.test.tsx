import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { ToolResult } from './ToolResult.tsx'
import {
  acknowledgement,
  delegation,
  entityList,
  excerpt,
  fileChange,
  hitList,
  hitListMessage,
  inventory,
  toolMessage,
} from './fixtures.ts'

describe('ToolResult', () => {
  it('falls back to the tool text when there is no artifact', () => {
    render(<ToolResult message={toolMessage(null)} phase="settled" />)
    expect(screen.getByText(/19 match\(es\)/)).toBeInTheDocument()
  })

  it('renders a shape when there is an artifact', () => {
    render(<ToolResult message={hitListMessage} phase="settled" />)
    // The model's own string is gone: the whole point is that the reader gets
    // the structure instead, not the structure as well.
    expect(screen.queryByText(/19 match\(es\) for/)).not.toBeInTheDocument()
    expect(screen.getByText('manuscriptreport.com')).toBeInTheDocument()
  })

  it('falls back rather than throwing on an artifact it cannot parse', () => {
    // Red if `artifactOf` used `parse`: the render would throw and take the
    // transcript with it.
    render(<ToolResult message={toolMessage({ shape: 'hit_list', version: 1 })} phase="settled" />)
    expect(screen.getByText(/19 match\(es\)/)).toBeInTheDocument()
  })

  it('renders the caller’s own fallback markup when it supplies one', () => {
    // `ActivityFeed` and `Segments` each keep their existing element, so a
    // message with no artifact renders byte for byte what it renders today.
    // Without this, one of the two would be silently restyled by the other's
    // default, and nothing would go red.
    const { container } = render(
      <ToolResult
        message={toolMessage(null)}
        phase="settled"
        fallback={<div className="provisional-body">the old body</div>}
      />,
    )
    expect(container.querySelector('.provisional-body')).toHaveTextContent('the old body')
    expect(container.querySelector('.stream-fallback')).toBeNull()
  })

  it('ignores the fallback once an artifact parses', () => {
    render(
      <ToolResult
        message={toolMessage(acknowledgement)}
        phase="settled"
        fallback={<div>the old body</div>}
      />,
    )
    expect(screen.queryByText('the old body')).not.toBeInTheDocument()
    expect(screen.getByTestId('ack')).toBeInTheDocument()
  })

  it('names the tool that ran, not the tool the shape was designed around', () => {
    // A shape is shared: `hit_list` serves `search_sources` and `web_search`
    // both. Red if a shape hard-codes its own name in the header, which is
    // wrong for every producer but one and reads as authoritative while being
    // wrong. `search` was paired with `entity_list` in the plan and with
    // `hit_list` in the spec; the spec won, and this is the assertion that
    // makes the disagreement cost nothing.
    render(<ToolResult message={toolMessage(hitList, '…', 'web_search')} phase="settled" />)
    expect(screen.getByText('web_search')).toBeInTheDocument()
    expect(screen.queryByText('search_sources')).not.toBeInTheDocument()
  })

  it('falls back to the shape’s commonest producer when the name is absent', () => {
    // Every message written before `message_view` stopped dropping `name`
    // arrives with it null, and a header that read an empty tool name would
    // look like a rendering failure rather than like old history.
    render(<ToolResult message={toolMessage(hitList, '…', null)} phase="settled" />)
    expect(screen.getByText('search_sources')).toBeInTheDocument()
  })

  it.each([
    ['hit_list', hitList, 'hit-source'],
    ['entity_list', entityList, 'entity'],
    ['excerpt', excerpt, 'stream-body'],
    ['inventory', inventory, 'inventory-item'],
    ['acknowledgement', acknowledgement, 'ack'],
    ['file_change', fileChange, 'diff'],
    ['delegation', delegation, 'worker'],
  ])('dispatches %s to a renderer that draws something', (_shape, artifact, testId) => {
    // Over every member of the union rather than one hand-picked example: a
    // `switch` missing a case returns `undefined`, React renders nothing, and
    // the result is one shape silently drawing an empty card. Nothing throws
    // and nothing logs, so only an assertion per shape can see it.
    const { getAllByTestId } = render(
      <ToolResult message={toolMessage(artifact)} phase="settled" />,
    )
    expect(getAllByTestId(testId).length).toBeGreaterThan(0)
  })
})
