import { cva } from 'class-variance-authority'

import { statusLabel, statusTone, type StatusTone } from '@domain/entity/status.ts'

import { TruncatedText } from '../common/TruncatedText.tsx'

/** A status, spelled and toned in one place.
 *
 * This is the first use of `class-variance-authority` in the codebase, and it
 * is what CVA is actually for. The `Button` in `common/primitives.tsx` builds
 * its class with
 * `clsx('btn', small && 'btn-sm', tone !== 'default' && \`btn-${tone}\`)` — a
 * template string assembling a class name, which no tool can check and which
 * fails silently for a tone that has no stylesheet rule. `DispatchChip` in
 * `TopicList.tsx` is what that failure mode looks like once it has grown up:
 * a fifth chip implementation with five bespoke status classes that does not
 * use the shared `Chip` at all.
 *
 * Under CVA the tone map is a typed object, so a tone with no entry is a type
 * error at the call site rather than an unstyled chip discovered by a reader,
 * and the set of tones is enumerable — which is what lets one story show all
 * five side by side.
 *
 * The tone is *derived* from the status rather than passed in, and that is the
 * point rather than a convenience: C-F26's rule that only `queue_empty` earns
 * the `done` tone, and C-F46's that `human_gate` is a pause rather than a
 * failure, are properties of the status itself. A `tone` prop would let one
 * call site paint `budget_exhausted` green.
 */
const chip = cva('ent-status', {
  variants: {
    tone: {
      neutral: 'ent-status-neutral',
      live: 'ent-status-live',
      good: 'ent-status-good',
      held: 'ent-status-held',
      bad: 'ent-status-bad',
    } satisfies Record<StatusTone, string>,
  },
  defaultVariants: { tone: 'neutral' },
})

export const EntityStatus = ({
  status,
  detail,
}: {
  /** The wire value, not a label. Spelling is this component's job — that rule
   *  is written three times as `.replace('_', ' ')` today, in two files. */
  status: string
  /** Why the status is what it is, when the caller knows: a dispatch failure's
   *  reason, a block's cause. Rendered as text beside the status rather than
   *  as a `title`, because `title` is not keyboard-reachable, not available on
   *  touch, and inconsistently announced — the defect S-D3 counts nine of.
   *
   *  It was then clipped at a fixed `24ch` with no way to read the rest, which
   *  is `title` again with the one thing `title` was good at removed. It now
   *  shrinks only when the row does, and says so when it has. */
  detail?: string
}) => (
  <span className={chip({ tone: statusTone(status) })}>
    {/* An element rather than a bare text node, so it can be told not to
        shrink. As a text node it is an anonymous flex item, which takes the
        default `flex: 0 1 auto` and cannot be addressed by any rule — so a
        narrow row shrank the status itself, which is the chip's identity,
        rather than the explanation beside it. */}
    <span className="ent-status-label">{statusLabel(status)}</span>
    {detail === undefined ? null : <TruncatedText text={detail} className="ent-status-detail" />}
  </span>
)
