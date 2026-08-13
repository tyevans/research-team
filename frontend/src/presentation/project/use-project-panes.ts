import type { Track } from '@presentation/layout/split-tracks.ts'
import { useSplitPanes } from '@presentation/layout/use-split-panes.ts'

/** Which view's layout this is. See `use-session-panes.ts`: the group is what
 *  keeps the stored layouts of different views apart, and one shared key meant
 *  the second writer erased the first's.
 *
 * A new string rather than reuse of `course` or `session`, and the difference
 * is not cosmetic. The pane ids under those keys are `stages`/`artifacts` and
 * `timeline`/`workspace`/`conversation`; this page's are `queue`/`holder`/
 * `material`. Reading a stale set under the same key would be a silent
 * reinterpretation of somebody's stored layout, where a new key reads as
 * absent — which is what a reader actually meant, since they never expressed a
 * preference about a page that did not exist. The cost is that a reader who
 * had folded the course page's stage rail meets the project page fully open
 * once; `preference-store.ts:3-5` records the same trade being taken before,
 * for the same reason, and the dead keys are left behind rather than migrated.
 */
const GROUP = 'project'

/** The project page's three columns, as data.
 *
 * **These numbers are chosen, not measured, and that is a known gap rather
 * than a claim.** `SESSION_TRACKS` records its values as confirmed in a
 * browser; there is no equivalent measurement behind these, because the page
 * they describe has never been looked at. What is reasoned rather than
 * observed: QUEUE is a column of short rows and stops improving with width;
 * HOLDER holds prose and a transcript, which is the one thing here that reads
 * better wide; MATERIAL holds documents and a graph canvas, which wants room
 * but is not what a reader watches. Hence the middle column carrying the most
 * weight and the two flanks carrying the same.
 *
 * The floors are the session view's, unchanged, because they are floors for
 * the same reason -- below roughly 280px a column of rows stops being a list.
 *
 * The plan's §6.3 names this as work for the browser suite: the number that
 * matters is where each region stops being usable, and jsdom cannot see it.
 * Left for the slice that gives each region its real content, since measuring
 * the widths of three regions holding other views' markup would be measuring
 * the wrong page.
 */
export const PROJECT_TRACKS: readonly Track[] = [
  { id: 'queue', min: 280, weight: 1 },
  { id: 'holder', min: 320, weight: 1.5 },
  { id: 'material', min: 280, weight: 1 },
]

/** The project page's half of its pane layout, which is only the group it
 *  remembers itself under. Shaped after `useSessionPanes` deliberately: the
 *  tracks and the group are the two halves of "this is the project's layout",
 *  and the tracks cannot live in a component that renders from props. */
export const useProjectPanes = () => useSplitPanes(GROUP)
