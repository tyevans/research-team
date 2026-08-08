import type { ProjectId } from '@domain/shared/identifier.ts'

import { DocumentList } from './DocumentList.tsx'
import { GraphPane } from './GraphPane.tsx'
import { TopicList } from './TopicList.tsx'

/** The project's research page: topics, seeding, documents and the graph.
 *
 * One region is still an empty shell -- seeding is a later task's work, so
 * it stays reviewable on its own and that task fills the pane without
 * touching the page around it. */
export const ResearchView = ({ projectId }: { projectId: ProjectId }) => (
  <section className="view view-research">
    <div className="view-head">
      <div>
        <h1>Research</h1>
      </div>
    </div>

    <div className="research-panes">
      <section className="pane pane-topics" aria-label="Topics">
        <header className="pane-head">
          <h2>Topics</h2>
        </header>
        <div className="pane-body">
          <TopicList projectId={projectId} />
        </div>
      </section>

      <section className="pane pane-seeding" aria-label="Seeding">
        <header className="pane-head">
          <h2>Seeding</h2>
        </header>
        <div className="pane-body" />
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
