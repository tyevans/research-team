import type { ProjectId } from '@domain/shared/identifier.ts'

import { courseHref } from '../routing/routes.ts'
import { DocumentList } from './DocumentList.tsx'
import { GraphPane } from './GraphPane.tsx'
import { SeedPanel } from './SeedPanel.tsx'
import { TopicList } from './TopicList.tsx'

/** The project's research page: seeding, topics, documents and the graph.
 *
 * Seeding sits above the topic list rather than beside it -- it is where a
 * reader with an empty queue starts, and the topics it opens land in the
 * pane directly below without this page wiring a second delivery path for
 * them (`open_topic` already appends to the log `TopicList`'s own query
 * invalidates on). */
export const ResearchView = ({ projectId }: { projectId: ProjectId }) => (
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

    <div className="research-panes">
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

      <section className="pane pane-graph" aria-label="Graph">
        <header className="pane-head">
          <h2>Graph</h2>
        </header>
        <div className="pane-body">
          <GraphPane projectId={projectId} />
        </div>
      </section>
    </div>
  </section>
)
