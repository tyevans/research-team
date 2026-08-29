import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { SHAPE_GLYPH } from '@domain/conversation/artifact.ts'

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
    // `ProvisionalBubble` and `Segments` each keep their existing element, so
    // a message with no artifact renders byte for byte what it renders today.
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
    expect(container.querySelector('[data-testid="stream-fallback"]')).toBeNull()
  })

  it('leaves a caller’s fallback outside the stream’s own wrapper', () => {
    // `.stream` carries the monospace family, the smaller size and the dimmed
    // colour every shape is drawn in. A fallback inside it would be restyled
    // while still containing the right text, so every assertion above would
    // stay green — which is why this is asserted on the element and not on
    // what it says. Red if the wrapper moves back out to the call sites and
    // one of them wraps unconditionally.
    const { container } = render(
      <ToolResult
        message={toolMessage(null)}
        phase="settled"
        fallback={<div className="provisional-body">the old body</div>}
      />,
    )
    expect(container.querySelector('.stream')).toBeNull()

    const shaped = render(<ToolResult message={hitListMessage} phase="settled" />)
    expect(shaped.container.querySelector('[data-testid="stream"] > [data-phase]')).not.toBeNull()
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
    ['hit_list', hitList],
    ['entity_list', entityList],
    ['excerpt', excerpt],
    ['inventory', inventory],
    ['acknowledgement', acknowledgement],
    ['file_change', fileChange],
    ['delegation', delegation],
  ] as const)('draws %s with the glyph the registry holds', (shape, artifact) => {
    // `SHAPE_GLYPH` pairs a result with its call: a reader scrolling sees one
    // mark repeated, which is what lets the machinery blur into a texture
    // rather than reading as seven unrelated novelties. Each shape used to
    // write the character into a prop itself, so the registry was exported,
    // asserted to be complete, and used by nothing — seven copies of a value
    // whose whole purpose is that there is one of it.
    //
    // Parametrised over every shape rather than sampled, because a divergence
    // is per-shape by construction: six correct copies say nothing about the
    // seventh, and nothing on screen puts a call and its result side by side
    // for a reader to catch it.
    render(<ToolResult message={toolMessage(artifact)} phase="settled" />)
    expect(screen.getByTestId('stream-glyph')).toHaveTextContent(SHAPE_GLYPH[shape])
  })

  it('marks a failed write with a glyph the registry deliberately does not hold', () => {
    // The one override, and the reason `Row` still takes a `glyph` at all. A
    // write that failed is a state of the *result*, not a shape of its own,
    // and `SHAPE_GLYPH` is `Record<Shape, string>` whose test asserts one
    // distinct mark per shape — so a second acknowledgement glyph cannot live
    // there without making the registry mean something else.
    render(<ToolResult message={toolMessage({ ...acknowledgement, ok: false })} phase="settled" />)
    const glyph = screen.getByTestId('stream-glyph')
    expect(glyph).toHaveAttribute('data-tone', 'fail')
    expect(glyph).not.toHaveTextContent(SHAPE_GLYPH.acknowledgement)
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
