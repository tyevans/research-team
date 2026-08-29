import type { ReactNode } from 'react'

import type { ProjectId, TopicId } from '@domain/shared/identifier.ts'

import { Drawer } from '../../common/Drawer.tsx'
import { SeedPanel } from '../../research/SeedPanel.tsx'
import { TopicList } from '../../research/TopicList.tsx'
import { BulkResearch } from './BulkResearch.tsx'

/** The drawer's name, and the toolbar button's accessible name and tooltip.
 *
 * One constant for all three, following `AutonomyLock`'s `HEADING`: the
 * sentence a reader hovers is the sentence they land on, and two spellings of
 * one name is how a button comes to promise something the panel does not say.
 */
export const TOPICS_HEADING = 'Seed and manage this project’s topics'

/** The project's topics, whole, behind one door.
 *
 * A `Drawer` for `AutonomyLock`'s reason and `docs/design/
 * topic-actions-on-the-row.md` §4.3's, now applied to the list as well as to
 * the controls above it: a surface a reader visits *when they have a question
 * in hand* should not hold permanent width on every visit that is about
 * something else. QUEUE was a quarter of the project page whatever tab was
 * open. `TopicControls` carries that argument in full.
 *
 * **This reverses a decision made one slice ago, and the reversal is stated
 * where it was made.** The docstring this replaces refused to bring the search
 * box and the filter tabs in here, on the grounds that "a filter is not a
 * setting -- it is a statement about what the list in front of you currently
 * *is*, and putting it behind a door means a reader can be looking at three of
 * twelve topics with nothing on screen saying so." That argument is sound and
 * it is now moot: the list is behind the door too, so the filter and the rows
 * it describes are on screen together or not at all. What the old arrangement
 * could produce -- a filtered list on the page and its filter out of sight --
 * is exactly what this arrangement cannot.
 *
 * **Sections above, queue below, and the order is an argument.** Seeding is
 * what an *empty* project needs and the fan-out is what a *seeded* one needs,
 * so the two read top to bottom in the order a project meets them; it is also
 * the order of cost, since seeding opens questions and the fan-out spends a
 * turn on each of them. The rows come last because they are the part that
 * scrolls, and a scroller under two fixed blocks is the only arrangement where
 * the blocks stay put.
 *
 * **The fan-out is rendered through `TopicList`'s `header` slot rather than
 * beside it**, and that is the safety property rather than a filing choice.
 * Its guarantee is that the number on its button and the number of turns it
 * starts are the same by construction -- the ids come from the very array the
 * rows are rendered from. A `BulkResearch` rendered here as a sibling would
 * need its own read of "which topics are shown", which is the second
 * definition the whole design exists to avoid.
 */
export const TopicsDrawer = ({
  projectId,
  openTopic,
  onOpenTopic,
  onClose,
}: {
  projectId: ProjectId
  /** Which topic the route has open. Threaded down to `TopicList`, which
   *  fetches its detail and renders the manage pane under the rows. */
  openTopic: TopicId | null
  onOpenTopic: (topicId: TopicId | null) => void
  onClose: () => void
}) => (
  <Drawer heading={TOPICS_HEADING} label={TOPICS_HEADING} onClose={onClose}>
    <div className="flex h-full min-h-0 flex-col gap-[14px]">
      <DrawerSection
        heading="Seeding"
        detail="Name a subject and the project opens questions about it."
      >
        <SeedPanel projectId={projectId} />
      </DrawerSection>

      <TopicList
        projectId={projectId}
        open={openTopic}
        onOpen={onOpenTopic}
        // The heading says "shown" and the button says the number, which is the
        // same fact twice on purpose: the scope is the thing a person can get
        // wrong here, and it is the one thing that cannot be recovered by
        // pressing Stop faster than forty turns start.
        header={(shownTopicIds) => (
          <DrawerSection
            heading="Every topic shown"
            detail="Acts on the topics the filter below is showing, not on every topic in the project."
          >
            <BulkResearch projectId={projectId} topicIds={shownTopicIds} />
          </DrawerSection>
        )}
      />
    </div>
  </Drawer>
)

/** One titled block of the drawer.
 *
 * `<h3>` because `Drawer` renders the dialog's own `<h2>`; a section heading
 * that skipped to `<h4>` or repeated the `<h2>` would misreport the nesting to
 * anything reading the outline rather than the picture.
 */
export const DrawerSection = ({
  heading,
  detail,
  children,
}: {
  heading: string
  /** One sentence under the heading, saying what the controls do. Optional
   *  because a section whose controls say it themselves does not need one. */
  detail?: string
  children: ReactNode
}) => (
  <section className="flex flex-col gap-[8px]">
    <h3 className="m-0 text-sm font-semibold">{heading}</h3>
    {detail === undefined ? null : <p className="m-0 text-xs text-fg-dim">{detail}</p>}
    {children}
  </section>
)
