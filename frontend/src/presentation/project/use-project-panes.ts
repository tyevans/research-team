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
 * **The three floors were measured in Chromium on 2026-08-14**, against the
 * real page with all three regions loaded -- four stages and four topics in
 * QUEUE, a scrub bar over an eight-message transcript in HOLDER, six documents
 * and a twelve-node graph with its canvas drawn in MATERIAL.
 * `project-tracks.browser.test.tsx` is that measurement and holds the method;
 * what follows is what it found.
 *
 * A floor here is the width below which the region paints content outside a box
 * that clips it, with no scroller and no ellipsis to reach it by -- not a taste
 * judgement about legibility, which is not something a test can hold.
 *
 * | region | floor | what sets it | measured clean at |
 * | --- | --- | --- | --- |
 * | queue | 344 | the seeding form, 317px and unwrapping | 343 |
 * | holder | 342 | `.scrub-bar`, 341px | 342 |
 * | material | 352 | the five-tab strip, 351px and unwrapping | 352 |
 *
 * Each floor is a pixel or two above what measured clean, deliberately: the
 * check carries `TruncatedText`'s 1px slack for fractional layout, and 343 of
 * QUEUE and 350 of MATERIAL clear it only by spending that slack.
 *
 * **These replace `280/320/280`, which were the session view's floors adopted
 * unmeasured, and the old numbers shipped a defect.** At 1181 -- the narrowest
 * viewport where a template is written at all -- the fr shares are 337/506/337,
 * so MATERIAL got 337px for a tab strip that is 351px wide and does not shrink:
 * the Graph tab was painted past the pane's right edge, present and unclickable.
 * QUEUE's seeding form went the same way 14px later. Nobody met it because the
 * page had only ever been looked at at 1440.
 *
 * **The floors were the lever rather than the weights, and that is the whole
 * argument for this shape of fix.** `minmax(min, 1fr)` takes the floor only
 * where the fr share falls under it, so at 1181 the columns become 344/485/352
 * and at 1440 they are 411/617/411 -- what they measured before this change.
 * Reweighting would have bought the same clearance at 1181 by reshaping every
 * width above it, which is a redesign of the page to fix its narrowest 60px.
 *
 * HOLDER's 342 never binds in the wide band: 1.5 of 3.5 at 1181 is 506, and
 * with the two flanks on their floors it still gets 485. It is written down
 * because it was measured and because it is the number that starts mattering
 * the day a fourth region arrives, not because it does anything today.
 *
 * **Still reasoned rather than observed:** the weights. `1 / 1.5 / 1` says
 * HOLDER is what a reader watches and the two flanks are interchangeable, and
 * nothing here measures that -- it is a claim about attention, not about
 * layout. The floors say where each region breaks; they say nothing about where
 * each region is *good*, and a test cannot tell the difference.
 */
export const PROJECT_TRACKS: readonly Track[] = [
  { id: 'queue', min: 344, weight: 1 },
  { id: 'holder', min: 342, weight: 1.5 },
  { id: 'material', min: 352, weight: 1 },
]

/** The project page's half of its pane layout, which is only the group it
 *  remembers itself under. Shaped after `useSessionPanes` deliberately: the
 *  tracks and the group are the two halves of "this is the project's layout",
 *  and the tracks cannot live in a component that renders from props. */
export const useProjectPanes = () => useSplitPanes(GROUP)
