import type { ProjectId } from '@domain/shared/identifier.ts'

/** The project's research page: topics, seeding, documents and the graph.
 *
 * An empty shell for now -- four labelled regions and nothing that fetches,
 * so this task's routing change is reviewable on its own and later tasks can
 * fill one region at a time without touching the page around it. */
export const ResearchView = ({ projectId: _projectId }: { projectId: ProjectId }) => (
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
        <div className="pane-body" />
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
