import type { ProjectId } from '@domain/shared/identifier.ts'

import { TopicList } from './TopicList.tsx'

/** The project's research page: topics, seeding, documents and the graph.
 *
 * Three regions are still an empty shell -- this task fills only the topic
 * queue, so the other three stay reviewable on their own and later tasks can
 * fill one at a time without touching the page around them. */
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
        <div className="pane-body" />
      </section>

      <section className="pane pane-graph" aria-label="Graph">
        <header className="pane-head">
          <h2>Graph</h2>
        </header>
        <div className="pane-body" />
      </section>
    </div>
  </section>
)
