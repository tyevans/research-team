import { Chip } from '../common/primitives.tsx'
import { Tooltip } from '../common/Tooltip.tsx'

/** What is happening in a project right now, if anything.
 *
 * **The hook that used to live here is gone.** `useProjectActivity` read the
 * global roster and picked one project's entry out of it, once per drawn row.
 * That cost no extra requests -- every call shared one cache entry -- but it
 * did mean a project row could not be rendered without a query client, which
 * is the whole reason `ProjectBoardRow` is props-only now. The board reads the
 * roster once and passes each row its label; the picking logic moved with it,
 * to `activityOf` in `ProjectBoard.tsx`, including the explicit "a run
 * outranks a turn" precedence that `workers[0]` would have lost.
 *
 * What is left is the drawing, which is what a second surface would want to
 * share.
 */

/** The marker itself, in the amber the timeline already spends on tool
 *  activity — a run *is* tool activity, so liveness reads as the colour the
 *  event log uses for it rather than as a colour invented here. */
export const ActivityChip = ({ label }: { label: string | null }) =>
  label ? (
    <Tooltip explanation="Something is running in this project right now">
      <Chip tone="held">⟳ {label}</Chip>
    </Tooltip>
  ) : null
