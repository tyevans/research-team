import type { Track } from '@presentation/layout/split-tracks.ts'
import { useSplitPanes } from '@presentation/layout/use-split-panes.ts'

/** Which view's layout this is. The research rail and the course page remember
 *  their own under different groups, and the three are different sets of panes
 *  -- one shared key meant the second writer erased the first's. */
const GROUP = 'session'

/** The session view's three columns, as data.
 *
 * These are the values that are **live today**, not the ones `panes.css`
 * declared: the hook wrote `grid-template-columns` inline and an inline style
 * outranks a stylesheet unconditionally, so `panes.css:73`'s
 * `minmax(300px, 1.05fr) minmax(320px, 1.5fr) minmax(300px, 1.15fr)` has never
 * taken effect on a wide screen. Confirmed in a browser rather than reasoned
 * about. Adopting it here would have been a silent 20px change to two columns
 * and a weight change to a third, arriving as a side effect of a refactor;
 * whether it is the better design is a separate question with a separate
 * argument, and it is not this change's to make.
 */
export const SESSION_TRACKS: readonly Track[] = [
  { id: 'timeline', min: 280, weight: 1.05 },
  { id: 'workspace', min: 320, weight: 1.5 },
  { id: 'conversation', min: 280, weight: 1.05 },
]

/** The session view's half of its pane layout, which is now only the group it
 *  remembers itself under.
 *
 * The body of this hook moved to `useSplitPanes`, unchanged, when the course
 * page needed the same twenty lines with a different string in them. Kept as a
 * named hook rather than inlining `useSplitPanes('session')` at the call site
 * so that `SESSION_TRACKS` and the group stay in one file: they are the two
 * halves of "this is the session's layout", and the tracks cannot live in a
 * component that renders from props.
 */
export const useSessionPanes = () => useSplitPanes(GROUP)
