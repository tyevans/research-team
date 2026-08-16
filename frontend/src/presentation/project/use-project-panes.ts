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

/** The project page's two columns -- a sidebar and the content beside it.
 *
 * **This was three columns until this slice, and HOLDER's row is gone from the
 * table below rather than merely unused.** The holding session is a tab in
 * MATERIAL now; `ProjectView.tsx`'s `regionOf` carries the argument and the
 * cost. What survives here is the floors, because a floor is a measurement and
 * measurements do not stop being true when the layout around them changes.
 *
 * A floor is the width below which the region paints content outside a box that
 * clips it, with no scroller and no ellipsis to reach it by -- not a taste
 * judgement about legibility, which is not something a test can hold.
 * `project-tracks.browser.test.tsx` is where each number was taken and holds the
 * method.
 *
 * | region | floor | what sets it | measured at |
 * | --- | --- | --- | --- |
 * | queue | 344 | the seeding form, 317px and unwrapping | 343 |
 * | material | 582 | the eight-tab strip, 581.6px laid out | 581.6 |
 *
 * **The material row was re-measured on 2026-08-15 at the merge, and the merge
 * is the reason.** Two branches each added a seventh tab without seeing the
 * other -- main folded the holding session in (537, against a 536.3px strip),
 * this branch added Tree (468, against a 467px strip on the old three-column
 * shape). Both floors are wrong for the eight-tab strip they produce together,
 * and taking either side of the conflict would have kept a number that was
 * measured against a strip that no longer exists. Re-measured after resolving:
 * red at 537 against 581.6, so 582.
 *
 * Each floor is a pixel or two above what measured clean, deliberately: the
 * check carries `TruncatedText`'s 1px slack for fractional layout, and QUEUE's
 * 343 clears it only by spending that slack.
 *
 * **MATERIAL's floor moves with its tab strip, and has been re-measured five
 * times for that reason** -- once when Task 10 added a sixth tab (red at 352
 * against a strip that had grown to 421), once when the holding session became
 * a seventh (422 against 536.3), once at the merge that made Tree an eighth
 * (537 against 581.6), and once when Classes made it a ninth (582 against
 * 645.875), all in Chromium. The row does not wrap and has no
 * scroller, so a floor
 * that lagged the strip clips the newest tab past the pane's edge: present,
 * painted, unclickable. That is not hypothetical -- it is what the old
 * unmeasured `280/320/280` did to the Graph tab, on a page that had only ever
 * been looked at at 1440.
 *
 * **646 does not bind anywhere in the wide band, and is written down anyway.**
 * MATERIAL is `1fr` beside a quarter-width sidebar, so it takes 837 at 1181 and
 * more above -- three hundred pixels of clearance. The number is the guard, not
 * the geometry: it is what fails, at the width where a reader would lose a tab,
 * if a tenth tab arrives and this line does not move with it. The measurement
 * that takes it is `project-tracks.browser.test.tsx`'s claim 3, which sums the
 * strip's laid-out children rather than reading `scrollWidth` -- in a pane this
 * wide the strip does not overflow, so `scrollWidth` reports the pane and would
 * make the assertion vacuously true.
 *
 * **QUEUE is sized by a ceiling rather than a weight, and that is the change
 * this slice makes to the shape of the table.** A weight is a share of what the
 * floors left over, so the same `1fr` is a different fraction of the window at
 * every width -- fine for peers, wrong for a sidebar, which is a *fraction of
 * the page* by definition. `max: '25%'` says so directly. The floor still wins
 * underneath it: below roughly 1376px, 25% is less than 344 and the column
 * takes 344 instead, so the seeding form never clips no matter how narrow the
 * band gets. MATERIAL keeps a weight because `1fr` of one flexible track is
 * simply "the rest", which is what a content area is.
 */
export const PROJECT_TRACKS: readonly Track[] = [
  { id: 'queue', min: 344, max: '25%' },
  { id: 'material', min: 646, weight: 1 },
]

/** **Rejected: folding the sidebar automatically below the wide breakpoint.**
 *
 * It was written, tested and backed out in the same slice, and the reason is
 * worth more than the code was. The idea was that below 1181px `splitTemplate`
 * withdraws its template, so an open sidebar would stop being a quarter beside
 * the content and become a full-width band above it -- fold it, and the reader
 * with less room keeps the content area whole.
 *
 * What that missed is that the fold has a *control*. Overriding the collapsed
 * set on the way into `Split` leaves the reader's own set untouched, which is
 * what stops a transient fold being persisted -- and it also means clicking
 * "Expand Queue" writes a set that the override immediately re-folds. The
 * button is present, focusable, correctly named, and does nothing. That is a
 * worse failure than the band it was fixing, and it is invisible to every test
 * that does not click the control at that width.
 *
 * The band does not need it: `responsive.css` gives 821-1180 its own two-column
 * template, so the sidebar keeps its proportion there without any of this.
 * Below 821 the panes genuinely stack, and folding is left to the reader --
 * where the control works.
 */

/** The project page's half of its pane layout, which is only the group it
 *  remembers itself under. Shaped after `useSessionPanes` deliberately: the
 *  tracks and the group are the two halves of "this is the project's layout",
 *  and the tracks cannot live in a component that renders from props. */
export const useProjectPanes = () => useSplitPanes(GROUP)
