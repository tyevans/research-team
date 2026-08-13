import type { ProjectId } from '@domain/shared/identifier.ts'

import { Pane } from '../layout/Pane.tsx'
import { projectHref } from '../routing/routes.ts'
import { DocumentList } from './DocumentList.tsx'
import { GraphPane } from './GraphPane.tsx'
import { SeedPanel } from './SeedPanel.tsx'
import { TopicList } from './TopicList.tsx'
import { useResearchPanes } from './use-research-panes.ts'

/** The project's research page: seeding, topics, documents and the graph.
 *
 * A rail and a stage rather than four equal panes. The four regions do not
 * carry equal weight -- the graph is the artifact the page exists to show, and
 * topics and documents are the context you read it against -- so a 2x2 grid
 * that gave each of them a quarter of the screen was describing them as peers
 * when they are not. The graph takes the whole stage and the rest stacks down
 * one side.
 *
 * The page itself does not scroll. Each region does, independently, which is
 * what makes the graph able to fill the viewport: a scrolling page forces
 * every pane inside it to a fixed pixel height, and three fixed-height scroll
 * boxes inside a fourth scrolling page is the arrangement this replaces.
 *
 * **Not a `Split`, and that is a decision rather than an oversight.** `Split`
 * is a row of resizable columns whose sizes are declared once as `Track`s, and
 * it exists because the session view had two declarations of three columns
 * that disagreed. This page has one declaration of two columns
 * (`.research-workbench`) and nothing to reconcile, and the two things `Split`
 * would add are both wrong here: its collapse rule refuses to hide the last
 * open pane, which is right for three peer columns and meaningless for a rail
 * whose three panes may all fold at once; and a track per column would make
 * the rail's three stacked panes children of a track that is not theirs, since
 * `Split` has no second axis and is documented as never getting one. What the
 * page does take from the layout system is `Pane`, four times -- which is
 * where `RailPane`, a fourth fold implementation, goes.
 *
 * Seeding sits at the top of the rail rather than in the stage: it is where a
 * reader with an empty queue starts, and the topics it opens land directly
 * below it without this page wiring a second delivery path for them
 * (`open_topic` already appends to the log, which the topic queue's own query
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
}) => {
  const { folded, toggle } = useResearchPanes()

  return (
    <section className="view view-research">
      <div className="view-head">
        <div>
          <h1>Research</h1>
        </div>
        <div className="view-head-actions">
          {/* The project page with no selection, which is the course today. */}
          <a className="btn btn-quiet" href={projectHref(projectId)}>
            Course
          </a>
          <a className="btn btn-quiet" href={projectHref(projectId, { facet: 'ask', id: null })}>
            Ask
          </a>
        </div>
      </div>

      <div className="research-workbench">
        <div className="research-rail">
          {/* Kept mounted when folded, unlike the two lists below. A subject
              half-typed into the seeding box should survive a fold, and the
              panel's stream subscription is how a run started before the fold
              reports that it finished -- unmounting it means a run completing
              behind a folded pane is never seen. */}
          <Pane
            id="seeding"
            label="Seeding"
            collapseTo="strip"
            collapsed={folded.has('seeding')}
            onToggle={() => toggle('seeding')}
          >
            <SeedPanel projectId={projectId} />
          </Pane>

          {/* Both lists unmount when folded. For documents this is required
              rather than tidy: a virtualizer inside a hidden-but-mounted pane
              measures a zero-height scroll container and caches that, so the
              pane comes back empty. Topics follows it for a weaker but real
              reason -- a folded list that keeps invalidating its query on
              every topic frame is doing the work of a pane nobody is looking
              at. The cost of both is a refetch on expand if the cache entry
              has gone stale, and a filter box that comes back empty. */}
          <Pane
            id="topics"
            label="Topics"
            collapseTo="strip"
            // The list inside owns the scroll so its filter bar stays pinned
            // while the rows move under it; documents likewise, because the
            // virtualizer owns a scroll container and a body scrolling around
            // it is a box inside a box with the virtualizer measuring the
            // wrong one.
            scroll="regions"
            minContent={240}
            unmountWhenCollapsed
            collapsed={folded.has('topics')}
            onToggle={() => toggle('topics')}
          >
            <TopicList projectId={projectId} />
          </Pane>

          <Pane
            id="documents"
            label="Documents"
            collapseTo="strip"
            scroll="regions"
            minContent={240}
            unmountWhenCollapsed
            collapsed={folded.has('documents')}
            onToggle={() => toggle('documents')}
          >
            <DocumentList projectId={projectId} />
          </Pane>
        </div>

        {/* No toggle: the stage is what the page is for, and a control that
            folds away the only reason to be here is one nobody should be
            offered. `Pane` renders no toggle when it is given neither an
            `onToggle` nor an enclosing `Split`, so this is the absence of a
            prop rather than a flag.

            `regions` because the canvas and the command panel below it are two
            areas that size themselves; a body scrolling around them would put
            a scrollbar on a graph that is meant to fill its pane. */}
        <Pane id="graph" label="Graph" scroll="regions">
          <GraphPane projectId={projectId} entity={entity} onEntity={onEntity} />
        </Pane>
      </div>
    </section>
  )
}
