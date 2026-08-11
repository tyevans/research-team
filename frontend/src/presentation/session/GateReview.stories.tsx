import type { Meta, StoryObj } from '@storybook/react-vite'

import type { GateContext, GateFinding } from '@domain/approval/approval.ts'
import { SessionId } from '@domain/shared/identifier.ts'

import { GateReview } from './GateReview.tsx'

/** The three shapes a stage gate arrives in.
 *
 * They are separate stories rather than one page because the distinction that
 * matters is between two kinds of *absence*, and absence is only visible next
 * to what it is not: a gate with no findings has to say so, and a gate with no
 * artifact paths has to say nothing at all. On one page the second one looks
 * like a rendering failure; named, it is the tool path.
 */
const meta: Meta<typeof GateReview> = {
  title: 'session/GateReview',
  component: GateReview,
}

export default meta

type Story = StoryObj<typeof GateReview>

const SESSION = SessionId('22222222-2222-2222-2222-222222222222')

const finding = (over: Partial<GateFinding> = {}): GateFinding => ({
  check: 'cites_are_real',
  severity: 'blocking',
  message: 'Two citations name documents that are not in the workspace.',
  cites: ['docs/plan.md#L4'],
  suggestedEdit: null,
  ...over,
})

const context = (over: Partial<GateContext> = {}): GateContext => ({
  stage: 'synthesis',
  findingsArtifact: 'reviews/synthesis-findings.md',
  artifactPaths: ['out/synthesis.md', 'out/synthesis-notes.md'],
  blocked: false,
  artifactsReviewed: 2,
  linksReviewed: 7,
  unimplementedChecks: [],
  unreadableArtifacts: [],
  findings: [],
  ...over,
})

/** Everything ran and nothing objected. The "no check raised anything" line is
 *  the whole story — a clean pass that rendered blank would be unreadable from
 *  a pass whose findings failed to arrive. */
export const CleanPass: Story = {
  args: { sessionId: SESSION, context: context() },
}

/** The loud case: blocked, findings at three severities, one of them a level
 *  `severityLabel` has a phrase for (`human_gate`) and one it does not
 *  (`nitpick`) — the second is there to show a level nobody has taught the UI
 *  about still renders as itself rather than disappearing. */
export const BlockedWithFindings: Story = {
  args: {
    sessionId: SESSION,
    context: context({
      blocked: true,
      artifactsReviewed: 3,
      linksReviewed: 12,
      unimplementedChecks: ['sources_are_diverse', 'no_dangling_todo'],
      unreadableArtifacts: ['out/draft.docx'],
      findings: [
        finding(),
        finding({
          check: 'no_unsupported_claims',
          severity: 'blocking',
          message: 'The conclusion asserts a figure no cited source states.',
          cites: [],
          suggestedEdit: 'Drop the figure or cite the table it came from.',
        }),
        finding({
          check: 'reads_cleanly',
          severity: 'advisory',
          message: 'Three paragraphs repeat the same framing.',
          cites: [],
        }),
        finding({
          check: 'scope_agreed',
          severity: 'human_gate',
          message: 'Widening to adjacent fields needs a person to agree.',
          cites: ['docs/scope.md'],
        }),
        finding({
          check: 'house_style',
          severity: 'nitpick',
          message: 'Two headings use title case and the rest do not.',
          cites: [],
        }),
      ],
    }),
  },
}

/** The hand-driven tool path: the gate is posed before anything is written, so
 *  `artifactPaths` is empty and the component lists no files rather than an
 *  empty list or a "none" row. See `gate_context()` in `stage_exit.py` — paths
 *  that answer 404 would be worse than no paths. */
export const ToolPathWithoutArtifacts: Story = {
  args: {
    sessionId: SESSION,
    context: context({
      artifactPaths: [],
      artifactsReviewed: 0,
      linksReviewed: 0,
      findings: [finding({ severity: 'invariant', message: 'The stage wrote no artifact.' })],
    }),
  },
}
