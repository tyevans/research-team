/** `Markdown`, from a reader's point of view: what a `[[src:...]]` reference
 *  becomes on the page, and what it must never become. */
import { render, screen } from '@testing-library/react'
import { expect, it } from 'vitest'

import { ProjectId } from '@domain/shared/identifier.ts'

import { Markdown } from './content.tsx'

const PROJECT = ProjectId('11111111-1111-1111-1111-111111111111')

it('renders a reference as a link to the source', () => {
  render(<Markdown source="see [[src:keynote@252]]" projectId={PROJECT} />)
  // `?t=252`, not `#t=252`: the href is already a hash route
  // (`#/p/<id>/doc/<id>`), and a URL has exactly one fragment -- a second
  // `#t=` after it wouldn't be a fragment at all, just literal characters
  // inside the one that already started. `expandReferences`' own comment
  // in references.ts explains why the offset travels as a query instead.
  expect(screen.getByRole('link')).toHaveAttribute('href', expect.stringContaining('t=252'))
})

/** What a reader actually sees. Asserted through the rendered DOM rather than
 *  on `expandReferences`' string, because the marker only survives if
 *  `renderMarkdown`'s allow-list keeps `sup` and `aria-label` -- and a
 *  stripped tag raises nothing. */
it('shows a numbered marker, not a fifty-character slug', () => {
  render(<Markdown source="a claim [[src:keynote@252]]" projectId={PROJECT} />)
  const link = screen.getByRole('link', { name: 'Source 1: keynote' })
  expect(link).toHaveTextContent('1')
  expect(link).toHaveAttribute('title', 'keynote')
  expect(link.closest('sup')).not.toBeNull()
  expect(screen.queryByText(/keynote/)).not.toBeInTheDocument()
})

/** The claim is about what reaches the page, so this asserts on the rendered
 *  DOM rather than on `expandReferences`' output directly -- it would still
 *  pass if someone later moved sanitisation ahead of the reference pre-pass,
 *  which is the one ordering this whole feature depends on. */
it('cannot produce an href the sanitiser would reject', () => {
  render(<Markdown source={'[[src:javascript:alert(1)]]'} projectId={PROJECT} />)
  expect(screen.queryByRole('link')).not.toBeInTheDocument()
  expect(screen.getByText(/\[\[src:javascript/)).toBeInTheDocument()
})

/** No `projectId` is a real caller shape (`FileView`, the lesson widgets),
 *  not a test-only gap -- see the callers listed in content.tsx's docstring.
 *  A reference with nowhere to resolve to renders as the same literal text an
 *  unmatched or malformed reference already does. */
it('renders a reference as literal text when there is no project to link into', () => {
  render(<Markdown source="see [[src:keynote@252]]" />)
  expect(screen.queryByRole('link')).not.toBeInTheDocument()
  expect(screen.getByText(/\[\[src:keynote@252\]\]/)).toBeInTheDocument()
})
