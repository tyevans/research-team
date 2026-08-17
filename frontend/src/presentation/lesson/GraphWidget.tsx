import { useQuery } from '@tanstack/react-query'
import { lazy, Suspense, useMemo } from 'react'

import { useContainer } from '@app/container-context.tsx'
import type { AttemptsApi } from '@application/lesson/use-attempts.ts'
import { useEntityReference } from '@application/lesson/use-entity-reference.ts'
import { queryKeys } from '@application/queries/keys.ts'
import { resolvedWidgetQuery } from '@application/queries/resolved-widget.ts'
import { emptyGraph, expand } from '@domain/knowledge/graph.ts'
import type { ComponentBlock } from '@domain/lesson/document.ts'
import { readGraphRef } from '@domain/lesson/widgets.ts'
import type { ProjectId } from '@domain/shared/identifier.ts'

import { ResolvedFrame } from './ResolvedFrame.tsx'

// Lazy for `GraphPane`'s reason: the ~60 kB canvas/d3-force bundle should be
// fetched when a reader actually meets a graph, not as part of rendering an
// ask answer that mostly is not one.
const GraphCanvas = lazy(() =>
  import('../research/GraphCanvas.tsx').then((module) => ({ default: module.GraphCanvas })),
)

/** One entity's neighbourhood, drawn inside an answer.
 *
 * `GraphCanvas` rather than `GraphBrowser`: the browser's props are a
 * console's worth of search and filter state, none of which a block in a
 * document has or wants.
 *
 * **The box is the load-bearing part.** `GraphCanvas` measures its container
 * with a `ResizeObserver` and a markdown flow gives it no height, so without
 * an explicit box the canvas measures 0 and draws nothing -- with no error
 * anywhere. Asserted in `GraphWidget.browser.test.tsx`, because a computed
 * height is exactly what jsdom cannot judge.
 *
 * `attempts` is in the signature and unused, for `DefinitionWidget`'s reason:
 * every entry in `RENDERERS` takes it, and a resolved component is not
 * gradeable.
 */
export const GraphWidget = ({
  block,
  projectId,
}: {
  block: ComponentBlock
  attempts: AttemptsApi
  projectId?: ProjectId
}) => {
  const reference = readGraphRef(block)
  const resolved = useEntityReference(projectId, reference)

  return (
    <div className="cmp-body">
      <ResolvedFrame reference={resolved} name={reference.entity}>
        {/* Narrowed here rather than cast inside `Neighbourhood`, copying
            `DefinitionWidget`: `useEntityReference` answers `unavailable`
            whenever there is no project, and `ResolvedFrame` reaches this
            render prop only from its `resolved` arm -- so the `null` arm is
            unreachable and exists only to make the narrow possible. */}
        {(entity) =>
          projectId ? (
            <Neighbourhood
              projectId={projectId}
              entityId={entity.id}
              name={entity.name}
              depth={reference.depth}
            />
          ) : null
        }
      </ResolvedFrame>
    </div>
  )
}

/** Split out so `useQuery` is mounted only once there is an id to give it -- a
 *  hook cannot be called conditionally, and the alternative is fetching with a
 *  null id behind an `enabled` flag on every state that has no entity. */
const Neighbourhood = ({
  projectId,
  entityId,
  name,
  depth,
}: {
  projectId: ProjectId
  entityId: string
  name: string
  depth: number
}) => {
  const { graphs } = useContainer()
  const hood = useQuery({
    queryKey: queryKeys.neighborhood(projectId, entityId, depth),
    queryFn: () => graphs.neighborhood(projectId, entityId, depth),
    // One policy for every resolved widget; the reasoning is in the constant.
    // An inferred node's id belongs to no stored entity, so its 404 is
    // permanent and the app-wide `retry: 1` only doubles the wait.
    ...resolvedWidgetQuery,
  })

  // `expand` off `emptyGraph` rather than a hand-built `GraphView`: it is the
  // one place that knows the root arrives in its own field and is not repeated
  // in `entities`, so a merge written here would hand d3-force links whose
  // endpoint is absent -- which throws `node not found` and takes the canvas
  // down rather than dropping an edge.
  const view = useMemo(() => (hood.data ? expand(emptyGraph, hood.data) : emptyGraph), [hood.data])

  if (hood.isPending) return <p className="cmp-ref-note">drawing {name}&rsquo;s neighbourhood…</p>
  if (hood.isError || !hood.data) {
    // A resolved name whose neighbourhood 404s is a real case: an inferred
    // node's id comes from the ontology table and belongs to no stored
    // entity. Prose and no `role="alert"`, like every other failure here --
    // `GraphWidget.test.tsx` checks for the absence.
    return <p className="cmp-ref-note">{name} — no neighbourhood to draw in this project</p>
  }

  return (
    <div className="cmp-graph-box" data-graph-widget>
      <Suspense fallback={<p className="cmp-ref-note">loading the canvas…</p>}>
        {/* `onNodeClick` is a no-op deliberately: a block inside an answer has
            no detail panel to open and nowhere to navigate to. Giving it one
            is a separate change with its own test. */}
        <GraphCanvas view={view} selected={entityId} onNodeClick={() => {}} />
      </Suspense>
    </div>
  )
}
