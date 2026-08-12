import { composeStories } from '@storybook/react-vite'
import { cleanup, render, screen } from '@testing-library/react'
import { expect, it } from 'vitest'

import { SessionId } from '@domain/shared/identifier.ts'

import { GateReview } from './GateReview.tsx'
import * as stories from './GateReview.stories.tsx'

const { CleanPass, BlockedWithFindings, ToolPathWithoutArtifacts } = composeStories(stories)

const SESSION = SessionId('22222222-2222-2222-2222-222222222222')

/** The distinction this component exists to hold: empty is not unavailable.
 *
 * Both halves are asserted in one test because either alone is satisfiable by
 * a component that is simply wrong in the other direction — rendering nothing
 * for both passes the second assertion, and rendering a "none" row for both
 * passes the first.
 */
it('says a clean gate is clean and says nothing at all about absent artifacts', () => {
  render(<CleanPass />)
  expect(screen.getByText('No check raised anything against this stage.')).toBeInTheDocument()

  // Both stories in one document would leave the clean pass's own artifact
  // list standing and pass this by accident.
  cleanup()

  render(<ToolPathWithoutArtifacts />)
  expect(screen.queryByText('what it wrote')).not.toBeInTheDocument()
  expect(screen.queryByText(/no artifacts/i)).not.toBeInTheDocument()
})

it('groups findings by severity and words each severity through severityLabel', () => {
  render(<BlockedWithFindings />)

  // Two blocking findings, one heading: the count is what proves grouping
  // rather than a chip per finding.
  expect(screen.getByText('blocking')).toBeInTheDocument()
  expect(screen.getAllByText('cites_are_real')).toHaveLength(1)
  expect(screen.getAllByRole('heading', { level: 4 })).toHaveLength(4)
  // `human_gate` is the label course.ts gives it; the raw key would be a
  // second severity vocabulary.
  expect(screen.getByText('needs a person')).toBeInTheDocument()
  expect(screen.queryByText('human_gate')).not.toBeInTheDocument()
  // A severity nobody taught the UI about still renders as itself.
  expect(screen.getByText('nitpick')).toBeInTheDocument()
})

it('shows a finding’s cites and suggested edit when it has them', () => {
  render(<BlockedWithFindings />)

  expect(screen.getByText('cites docs/plan.md#L4')).toBeInTheDocument()
  expect(screen.getByText('→ Drop the figure or cite the table it came from.')).toBeInTheDocument()
})

it('marks a blocked gate and words the unimplemented checks as the course view does', () => {
  render(<BlockedWithFindings />)

  expect(screen.getByText('blocked')).toBeInTheDocument()
  expect(
    screen.getByText(
      'This stage declares 2 checks that nothing implements: sources_are_diverse, no_dangling_todo. Nothing they would have found is known.',
    ),
  ).toBeInTheDocument()
  expect(screen.getByText('out/draft.docx')).toBeInTheDocument()
})

it('links the findings artifact and every artifact path into the session file viewer', () => {
  render(<BlockedWithFindings />)

  expect(screen.getByRole('link', { name: 'full findings report' })).toHaveAttribute(
    'href',
    `#/s/${SESSION}/file/${encodeURIComponent('reviews/synthesis-findings.md')}`,
  )
  expect(screen.getByRole('link', { name: 'out/synthesis.md' })).toBeInTheDocument()
  expect(screen.getByRole('link', { name: 'out/synthesis-notes.md' })).toBeInTheDocument()
})

/** Every count and list at zero or blank, in one render.
 *
 * This is the shape a gate posed before anything ran actually has, and each
 * field is a separate way to put `undefined` on the page or throw on a
 * `.length` — so the assertion is that the component renders at all and
 * carries no `undefined`, not that any one row appears.
 */
it('renders a gate whose every count is zero and every list is empty', () => {
  render(
    <GateReview
      sessionId={SESSION}
      context={{
        stage: 'intake',
        findingsArtifact: '',
        artifactPaths: [],
        blocked: false,
        artifactsReviewed: 0,
        linksReviewed: 0,
        unimplementedChecks: [],
        unreadableArtifacts: [],
        findings: [],
      }}
    />,
  )

  expect(screen.getByText('intake')).toBeInTheDocument()
  expect(screen.getByText('reviewed 0 artifacts and 0 links')).toBeInTheDocument()
  expect(screen.queryByRole('link')).not.toBeInTheDocument()
  expect(document.body.textContent).not.toContain('undefined')
})

/** Both explanations on this component, reached by keyboard.
 *
 * This test fails against the version that shipped: both sentences were
 * `title` attributes, which a keyboard reaches never, and #126 removed the
 * `title` prop from `Chip` underneath one of them — so `main` did not compile.
 * Asserting the text is present would not have caught either problem, because
 * a `title` *is* present in the DOM. Focusing the trigger and finding a
 * `tooltip` role is what separates a reachable explanation from an attribute.
 *
 * There is no `OverlayHost` in this file, and its absence is the second thing
 * being checked. A `Tooltip` with no host renders no content at all
 * (`Tooltip.tsx`), so this test only passes because `.storybook/preview.tsx`
 * wraps every story in one and `setProjectAnnotations` carries that into the
 * suite. Delete either and both assertions below fail — which is the point of
 * putting the host there rather than in each file that needs it.
 */
it('makes both explanations reachable by focus rather than by hover alone', async () => {
  render(<BlockedWithFindings />)

  // The chip is a `<span>`, so the tooltip wrapper is what puts it in the tab
  // order — it is a button whose accessible name is the chip's text.
  screen.getByRole('button', { name: 'blocked' }).focus()
  expect(await screen.findByRole('tooltip')).toHaveTextContent(
    'A blocking finding stands against this stage.',
  )

  // A fresh document for the second trigger. Moving focus from the chip to the
  // link inside one render leaves the chip's tooltip on screen for as long as
  // Radix's close takes, and `findByRole` then answers with whichever it finds
  // first — which passed while asserting the wrong element.
  cleanup()

  render(<BlockedWithFindings />)

  // The findings link is already focusable, so it is its own trigger under
  // `asChild`: the same element carries the href and opens the explanation.
  screen.getByRole('link', { name: 'full findings report' }).focus()
  expect(await screen.findByRole('tooltip')).toHaveTextContent('reviews/synthesis-findings.md')
})
