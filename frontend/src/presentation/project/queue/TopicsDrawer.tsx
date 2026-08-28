import type { ReactNode } from 'react'

import type { ProjectId } from '@domain/shared/identifier.ts'

import { Drawer } from '../../common/Drawer.tsx'
import { SeedPanel } from '../../research/SeedPanel.tsx'

/** The drawer's name, and the toolbar button's accessible name and tooltip.
 *
 * One constant for all three, following `AutonomyLock`'s `HEADING`: the
 * sentence a reader hovers is the sentence they land on, and two spellings of
 * one name is how a button comes to promise something the panel does not say.
 */
export const TOPICS_HEADING = 'Seed and manage this project’s topics'

/** What configures the queue, behind a door; what describes it stays inline.
 *
 * A `Drawer` for `AutonomyLock`'s reason and `docs/design/
 * topic-actions-on-the-row.md` §4.3's: a control touched once per project
 * should not hold permanent height on a rail whose job is a list. Seeding was
 * a card at the bottom of a 320px header, which is to say the one thing an
 * *empty* project needs was the thing furthest from the top of it.
 *
 * **The search box and the filter tabs deliberately did not come with it**,
 * and the ask that prompted this slice said "seeding and browsing" -- so this
 * is a departure, stated where it is made. A filter is not a setting. It is a
 * statement about what the list in front of you currently *is*, and putting it
 * behind a door means a reader can be looking at three of twelve topics with
 * nothing on screen saying so. The tabs already carry their counts for exactly
 * that reason. What moves in here is everything that configures the queue;
 * what stays out is everything that describes it.
 *
 * **Sections, for one section.** `DrawerSection` exists before there are two
 * of them because the next slice adds "find sources for every topic shown" --
 * a bulk verb over whatever the filter is showing -- and a body that is a bare
 * `<SeedPanel/>` invites appending a second control with no heading between
 * them. The cost is one wrapper that currently earns nothing; what it buys is
 * that the second thing in here has an obvious shape to take.
 */
export const TopicsDrawer = ({
  projectId,
  onClose,
}: {
  projectId: ProjectId
  onClose: () => void
}) => (
  <Drawer heading={TOPICS_HEADING} label={TOPICS_HEADING} onClose={onClose}>
    <div className="flex flex-col gap-[14px]">
      <DrawerSection
        heading="Seeding"
        detail="Name a subject and the project opens questions about it."
      >
        <SeedPanel projectId={projectId} />
      </DrawerSection>
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
    <h3 className="font-semibold m-0 text-sm">{heading}</h3>
    {detail === undefined ? null : <p className="m-0 text-xs text-fg-dim">{detail}</p>}
    {children}
  </section>
)
