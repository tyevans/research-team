import type { ProjectId } from '@domain/shared/identifier.ts'

import { courseHref } from '../routing/routes.ts'
import { DocumentList } from './DocumentList.tsx'
import { GraphPane } from './GraphPane.tsx'
import { SeedPanel } from './SeedPanel.tsx'
import { TopicList } from './TopicList.tsx'

/** The project's research page: seeding, topics, documents and the graph.
 *
 * A rail and a stage rather than four equal panes. The four regions do not
 * carry equal weight -- the graph is the artifact the page exists to show,
 * and topics and documents are the context you read it against -- so a 2x2
 * grid that gave each of them a quarter of the screen was describing them as
 * peers when they are not. The graph now takes the whole stage and the rest
 * stacks down one side.
 *
 * The page itself does not scroll. Each region does, independently, which is
 * what makes the graph able to fill the viewport: a scrolling page forces
 * every pane inside it to a fixed pixel height, and three fixed-height scroll
 * boxes inside a fourth scrolling page is the arrangement this replaces.
 *
 * Seeding sits at the top of the rail rather than in the stage: it is where a
 * reader with an empty queue starts, and the topics it opens land directly
 * below it without this page wiring a second delivery path for them
 * (`open_topic` already appends to the log `TopicList`'s own query
 * invalidates on).
 */
export const ResearchView = ({
  projectId,
  entity,
  onEntity,
}: {
  projectId: ProjectId
  /** The selected entity, owned by the route rather than by the graph store --
   *  see `Route`'s `research` variant. */
  entity: string | null
  onEntity: (id: string | null) => void
}) => (
  <section className="view view-research">
    <div className="view-head">
      <div>
        <h1>Research</h1>
      </div>
      <div className="view-head-actions">
        <a className="btn btn-quiet" href={courseHref(projectId)}>
          Course
        </a>
      </div>
    </div>

    <div className="research-workbench">
      <div className="research-rail">
        <section className="pane pane-seeding" aria-label="Seeding">
          <header className="pane-head">
            <h2>Seeding</h2>
          </header>
          <div className="pane-body">
            <SeedPanel projectId={projectId} />
          </div>
        </section>

        <section className="pane pane-topics" aria-label="Topics">
          <header className="pane-head">
            <h2>Topics</h2>
          </header>
          <div className="pane-body">
            <TopicList projectId={projectId} />
          </div>
        </section>

        <section className="pane pane-documents" aria-label="Documents">
          <header className="pane-head">
            <h2>Documents</h2>
          </header>
          <div className="pane-body">
            <DocumentList projectId={projectId} />
          </div>
        </section>
      </div>

      <section className="pane pane-graph" aria-label="Graph">
        <GraphPane projectId={projectId} entity={entity} onEntity={onEntity} />
      </section>
    </div>
  </section>
)
