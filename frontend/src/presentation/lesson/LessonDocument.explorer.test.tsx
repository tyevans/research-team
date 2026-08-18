/** The seam, and only the seam: that a block the server typed `explorer`
 *  reaches `ExplorerWidget` rather than the unknown-fence path.
 *
 * This is the assertion CLAUDE.md's `EntityDefinitionRunner` paragraph is
 * about. A component that is registered, validated, projected, serialised and
 * fully implemented, and is simply absent from `RENDERERS`, renders as a
 * `<pre>` -- nothing raises, nothing logs, the request succeeds, and every
 * unit test in this feature stays green. The failure is visible only by
 * looking, or by this.
 *
 * Deliberately does not assert on what the widget draws. That is
 * `ExplorerWidget.test.tsx`'s job, and duplicating it here would make this file
 * fail for reasons that have nothing to do with the wiring.
 */
import { render, screen, waitFor } from '@testing-library/react'
import { expect, it, vi } from 'vitest'

import type { AttemptsApi } from '@application/lesson/use-attempts.ts'
import { componentBlock } from '@presentation/ask/ask-fixtures.ts'

import { band, harness, PROJECT } from './timeline-widget-harness.tsx'
import { LessonDocument } from './LessonDocument.tsx'

vi.mock('../research/TimelineCanvas.tsx', () => ({
  TimelineCanvas: () => <div data-testid="timeline-canvas" />,
}))

it('routes an explorer block to the explorer widget, not to the unknown fence', async () => {
  const timeline = vi
    .fn()
    .mockResolvedValue({ bands: [band('b1')], undatedCount: 3, truncated: false })

  render(
    <LessonDocument
      doc={{
        blocks: [
          { kind: 'markdown', text: 'Some prose.' },
          componentBlock({
            type: 'explorer',
            id: 'e1',
            data: {
              over: 'timeline',
              prompt: 'Pull the window back.',
              vary: ['window'],
              from: '0300-01-01',
            },
          }),
        ],
      }}
      attempts={{} as unknown as AttemptsApi}
      projectId={PROJECT}
    />,
    { wrapper: harness(timeline) },
  )

  // The two halves of "wired", and both are needed. The section label is
  // `LessonDocument`'s own frame and proves the type was recognised; the
  // request proves `projectId` was threaded through to the widget. A widget
  // rendered without a project satisfies the first and draws a sentence saying
  // it cannot look anything up.
  expect(screen.getByLabelText('explorer component')).toBeInTheDocument()
  await waitFor(() => expect(timeline).toHaveBeenCalledWith(PROJECT, { from: '0300-01-01' }))
  expect(screen.queryByText(/```component:explorer/)).not.toBeInTheDocument()
})
