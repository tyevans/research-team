import type { ProjectId, SessionId } from '@domain/shared/identifier.ts'

import { projectHref } from '../../routing/routes.ts'
import { AutonomyPanel } from '../../course/AutonomyPanel.tsx'
import { ExtractionPane } from '../../course/ExtractionPane.tsx'
import { RunPanel } from '../../course/RunPanel.tsx'
import { Workers } from '../../course/Workers.tsx'
import { SeedPanel } from '../../research/SeedPanel.tsx'

/** The controls that act on the queue, above the queue.
 *
 * Slice 0 parked four controls loose in the QUEUE pane, in the order the course
 * page happened to have them, under a comment promising this component. The
 * promise was not cosmetic: parked directly in the pane they were four sibling
 * bands with no relationship declared between them and nothing separating them
 * from the list underneath, so a reader scrolling the queue scrolled the run
 * panel away with it and a reader looking for the run panel had to know it was
 * above the stages rather than below them.
 *
 * **The seed control is here because deleting `ResearchView` orphaned it.**
 * `SeedPanel` had exactly one mount, at the top of the research rail, and the
 * argument recorded there for that position transfers whole -- it is where a
 * reader with an empty queue starts, and the topics it opens land directly
 * below it. That is still true, and the list below it is now the *whole* queue
 * rather than half of one. Without this, the same commit that deletes the
 * research view deletes the only way to seed a project.
 *
 * **Order, and why it is not the course page's.** What is happening now
 * (roster, and the extraction detail under it), then what starts more of it
 * (the run panel), then what adds to the queue by hand (seeding), then the
 * policy the first two run under. That is a descending order of "how often does
 * somebody touch this", which is the ordering a header band earns; the course
 * page's order was the order the features landed in.
 *
 * **Dressed in utilities, which is the standing policy and not a port.** The
 * three `<section>`s that carried `worker-panel`, `run-panel` and
 * `autonomy-panel` were three copies of one card -- the same seven
 * declarations, written once in `course.css` and once in `components.css` --
 * and the wrapper is new markup here rather than moved markup, so it is dressed
 * where new surfaces are dressed. What it costs: the card is now spelled in one
 * place and the two stylesheet copies are dead, so `.run-panel` is deleted from
 * `components.css` and `.worker-panel` and `.autonomy-panel` from `course.css`
 * in this commit. Nothing writes any of the three any more -- the sweep in this
 * slice's report is what establishes that -- and a dead rule left in a file
 * that is itself scheduled to die is a rule somebody has to re-decide later.
 *
 * `course.css` itself does **not** die here, which the plan's §2.1 expected it
 * to. Five component families it dresses are still on screen after this
 * commit; the report enumerates them.
 *
 * **Not a scroller.** The header keeps its height and the list below it scrolls,
 * which is the whole point of separating them -- so this deliberately does not
 * take `flex-1` or `overflow-auto`, and the pane's own body remains the one
 * scroller. A focus ring inside it is therefore not at risk of the clipping
 * §5.2 of the plan describes; the rows in the list below are, and they are
 * unchanged from where they already lived.
 */
export const QueueHeader = ({
  projectId,
  watching,
  onWatch,
  holdingSessionId,
}: {
  projectId: ProjectId
  /** The session whose transcript HOLDER is showing, so the roster can mark it.
   *  Owned by the route. */
  watching: SessionId | null
  /** `null` is reachable: `Workers` calls this with `null` to clear the
   *  selection when the marked row is clicked again. */
  onWatch: (sessionId: SessionId | null) => void
  /** Where an autonomy write is recorded. `null` renders the panel read-only
   *  rather than offering controls that would 404 -- `AutonomyPanel`'s rule,
   *  unchanged by the move. */
  holdingSessionId: SessionId | null
}) => (
  <div
    className="flex flex-col gap-3 border-0 border-b border-solid border-line pb-3"
    data-region-header="queue"
  >
    {/* The way in to the ask page, and it is here because slice 1 deleted the
        only two there were.

        `CourseView` and `ResearchView` each carried an "Ask" link in their
        `view-head-actions`, and the commit that deleted both views deleted the
        last inbound link to a page that still exists, still routes and still
        works -- `App.tsx` renders it for `#/p/<id>/ask` today. The page even
        links *back* here, so the door was one-way for a whole slice. Nothing
        caught it: no test asserts that a route is reachable, and the two
        deletions were correct in themselves.

        In QUEUE because `regionOf` already answers `queue` for `ask`, and the
        reason there is the reason here -- a question you are putting to the
        project is a thing you want *done*, which is what this region collects.
        It is not a card: the four below are panels you read and act inside,
        this is a link that leaves the page, and dressing it as one of them
        would be the wrong promise. */}
    <a
      className="flex items-center justify-between rounded-md border border-solid border-line px-[12px] py-3 text-sm text-fg-dim no-underline hover:bg-bg-hover hover:text-fg"
      href={projectHref(projectId, { facet: 'ask', id: null })}
    >
      Ask this project
      {/* Decorative: the sentence already says it goes somewhere, and a screen
          reader announcing "right arrow" after it adds nothing. */}
      <span aria-hidden="true">-&gt;</span>
    </a>

    {/* The way in to the dialogue page, and it is the ONLY one.
        `facet: 'dialogue'` had zero `projectHref` call sites where
        `facet: 'ask'` has three, so a surface that routes, renders and grades
        was reachable only by typing `#/p/<id>/dialogue` -- the same one-way
        door the comment above records, shipped again one plan later. A facet
        with no entrance is not shipped.

        Beside the ask rather than anywhere else, because it is the same kind
        of thing: a conversation with the project, and this is where a reader
        looks for one. The two are deliberately not one link with a mode
        switch -- the direction is what differs, and a reader choosing between
        "I have a question" and "ask me questions" is choosing between two
        activities, not two settings. */}
    <a
      className="flex items-center justify-between rounded-md border border-solid border-line px-[12px] py-3 text-sm text-fg-dim no-underline hover:bg-bg-hover hover:text-fg"
      href={projectHref(projectId, { facet: 'dialogue', id: null })}
    >
      Be asked about this project
      <span aria-hidden="true">-&gt;</span>
    </a>

    <section className={CARD} aria-label="Working now">
      <Workers projectId={projectId} watching={watching} onWatch={onWatch} />
      {/* Inside the same card rather than beside it: the roster row is the
          summary -- "an extraction is running" -- and this is the detail under
          it, so a reader who sees the row is asking the question this answers. */}
      <ExtractionPane projectId={projectId} />
    </section>

    <section className={CARD} aria-label="Autonomous research">
      <RunPanel projectId={projectId} />
    </section>

    <section className={CARD} aria-label="Seeding">
      <SeedPanel projectId={projectId} />
    </section>

    <section className={CARD} aria-label="Autonomy">
      <AutonomyPanel sessionId={holdingSessionId} />
    </section>
  </div>
)

/** The card the three course-page bands each declared for themselves.
 *
 * `px-[12px]` is arbitrary because 12px is not on the spacing scale
 * (3/6/10/14) and the rules this replaces used the literal; rounding it to
 * `px-3` would move every band's left edge by 2px for tidiness, which is a
 * visual change smuggled into a re-parenting. `gap-[8px]` is the same case, and
 * `AutonomyAllowAll` records the same reasoning for the same two numbers.
 *
 * `border-solid` is not decoration and was missing until now: `border` sets
 * four widths and no style, and with no preflight imported every side's style
 * stays the browser's `none`. All four cards have been drawing no border at all
 * since slice 1 -- the same half-a-rule `BACKLOG.md` B55 records for the band's
 * bottom line, which is fixed in the same commit. Found by writing the link
 * above it and noticing the link had an edge and the cards did not.
 */
const CARD =
  'flex flex-col gap-[8px] rounded-md border border-solid border-line bg-bg-panel px-[12px] py-3'
