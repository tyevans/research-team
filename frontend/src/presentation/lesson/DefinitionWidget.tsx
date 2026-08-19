import type { AttemptsApi } from '@application/lesson/use-attempts.ts'
import { useEntityReference } from '@application/lesson/use-entity-reference.ts'
import type { GraphNode } from '@domain/knowledge/graph.ts'
import type { ComponentBlock } from '@domain/lesson/document.ts'
import { readDefinitionRef } from '@domain/lesson/widgets.ts'
import type { ProjectId } from '@domain/shared/identifier.ts'

import { DefinitionCitations } from '../research/DefinitionCitations.tsx'
import { useDefinition } from '../research/use-definition.ts'
import { QuietReference, ResolvedFrame } from './ResolvedFrame.tsx'
import { Prose } from './widgets.tsx'

/** This project's own grounded account of an entity, beside the prose that
 *  named it.
 *
 * `attempts` is in the signature and unused. Every renderer in `RENDERERS`
 * takes it, and a resolved component is not gradeable -- nothing here posts,
 * and there is no answer key to withhold. Narrowing the record's type per
 * entry to drop it would buy one unused parameter and cost the uniform
 * signature that makes `RENDERERS` a lookup rather than a switch.
 */
export const DefinitionWidget = ({
  block,
  projectId,
}: {
  block: ComponentBlock
  attempts: AttemptsApi
  projectId?: ProjectId
}) => {
  const reference = readDefinitionRef(block)
  const resolved = useEntityReference(projectId, reference)

  // The reader's pick out of the ambiguity picker lives in `ResolvedFrame`
  // now, not here -- see its docstring. Held here it survived a later search
  // result that no longer offered it, and it would have been copied into this
  // widget's four siblings before anyone noticed.
  return (
    <div className="cmp-body">
      <ResolvedFrame reference={resolved} name={reference.entity}>
        {/* Narrowed here rather than cast inside `Defined`, so TypeScript
            carries the guarantee instead of a comment. Narrowing at the call
            site keeps `ResolvedFrame`'s signature untouched, which matters
            because four more widgets copy this shape.

            The no-project arm draws the quiet reference, not `null`. It is
            unreachable -- `useEntityReference` answers `unavailable` whenever
            there is no project, for a pinned `entity_id` as well as for a
            name -- but it was `null` while that was only true of names, and a
            hand-edited lesson file with an id in it rendered a blank widget,
            which spec §1 forbids. The arm now costs nothing to be wrong
            about. */}
        {(entity) =>
          projectId ? (
            <Defined projectId={projectId} entity={entity} />
          ) : (
            <QuietReference name={entity.name} />
          )
        }
      </ResolvedFrame>
    </div>
  )
}

/** Split out so `useDefinition` is mounted only once there is an id to give
 *  it. A hook cannot be called conditionally, so the alternative is calling
 *  it with a null id and an `enabled` flag on every non-resolved state --
 *  which works and which reads as though a fetch might happen when it cannot.
 *
 * `projectId` is non-optional and the call site narrows to it rather than
 * casting -- see the render prop above for why that arm is unreachable.
 */
const Defined = ({ projectId, entity }: { projectId: ProjectId; entity: GraphNode }) => {
  const definition = useDefinition(projectId, entity.id)

  if (definition.isPending) return <p className="cmp-ref-note">looking that up…</p>
  // A failed *definition* is not a failed resolution: the entity is known to
  // be in the graph, so saying "not in this project's graph" here would be
  // false. Quiet prose, matching every other failure in this feature -- no
  // `role="alert"`, which `DefinitionWidget.test.tsx` checks for.
  if (definition.isError || !definition.data) {
    return <p className="cmp-ref-note">{entity.name} — could not be defined just now</p>
  }

  const { text, citations } = definition.data
  // `text: null` is a 200, not a 404, and means "this entity exists and the
  // project has nothing to ground a definition in" -- the opposite claim from
  // `missing`. See the route's own docstring (`app.py`'s
  // `read_graph_definition`) for why it is not a 404, and the spec's section 4
  // for why it is not folded into `missing`.
  if (text === null) {
    return (
      <p className="cmp-ref-note">
        <span className="cmp-ref-name">{entity.name}</span> — no definition yet; nothing in this
        project&rsquo;s corpus grounds one.
      </p>
    )
  }

  return (
    <>
      {/* No `cmp-definition-text` class: it would have no rule in
          `components.css`, and a class in the attribute with nothing in the
          bundle is indistinguishable from one that works -- the same failure
          `ResolvedFrame` declines `cmp-ref-missing` for. */}
      <Prose text={text} />
      <DefinitionCitations
        projectId={projectId}
        citations={citations}
        className="cmp-definition-citations"
      />
    </>
  )
}
