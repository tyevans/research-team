import type { AttemptsApi } from '@application/lesson/use-attempts.ts'
import { useEntityReference } from '@application/lesson/use-entity-reference.ts'
import type { ComponentBlock } from '@domain/lesson/document.ts'
import { readCompare } from '@domain/lesson/widgets.ts'
import type { ProjectId } from '@domain/shared/identifier.ts'

import { ResolvedFrame } from './ResolvedFrame.tsx'
import { Prose } from './widgets.tsx'

/** A side-by-side table whose column heads are resolved against the graph.
 *
 * **Columns are author-declared, and that is a constraint discovered rather
 * than chosen.** The natural design fills the table from per-type properties,
 * and `GET /ontology` does not have them -- a class's members are
 * `{name, ordinal}` strings with no attribute schema anywhere. There is
 * nothing to derive columns from, so the model writes them.
 *
 * What resolution adds over a plain markdown table is therefore narrow and
 * worth stating: every column head is a real entity in this project or is
 * visibly not one. A head that misses does not take the table down -- the
 * rows are the author's prose, and they are still the answer.
 *
 * `attempts` is in the signature and unused, as in every resolved widget:
 * `RENDERERS` is a lookup over one uniform signature, and a resolved
 * component has no answer key to grade.
 */
export const CompareWidget = ({
  block,
  projectId,
}: {
  block: ComponentBlock
  attempts: AttemptsApi
  projectId?: ProjectId
}) => {
  const compare = readCompare(block)

  return (
    <div className="cmp-body">
      <table className="cmp-compare">
        <thead>
          <tr>
            {/* The corner cell. Empty and `scope`-less on purpose: it heads
                neither a row nor a column, and giving it a scope would put a
                blank string into the accessibility tree as a header. */}
            <th />
            {compare.entities.map((name) => (
              <th key={name} scope="col">
                <Head projectId={projectId} name={name} />
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {compare.rows.map((row) => (
            <tr key={row.label}>
              <th scope="row">{row.label}</th>
              {/* Mapped over `entities`, never over `cells`: a short row must
                  pad on the right, and mapping over cells would shift a
                  single value under the first column and silently drop a
                  column from the table. */}
              {compare.entities.map((name, column) => (
                <td key={name}>
                  <Prose text={row.cells[column] ?? ''} />
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

/** One column head, resolved.
 *
 * Its own component because `useEntityReference` is called once per head and
 * a hook cannot be called in a loop from the parent. That is the whole reason
 * this is not a helper function.
 */
const Head = ({ projectId, name }: { projectId: ProjectId | undefined; name: string }) => {
  const resolved = useEntityReference(projectId, { entity: name, entityId: null })

  return (
    // `ResolvedFrame` carries the pick internally now, and there is nothing
    // this widget would do differently with a pinned id -- it shows the name
    // and the type either way. Its `missing` and `unavailable` states are
    // prose, which is what keeps a mixed table a table: this widget mounts
    // several of these at once, so an error panel per head would turn one
    // unextracted name into a grid of boxes.
    <ResolvedFrame reference={resolved} name={name}>
      {(entity) => (
        <>
          <span className="cmp-ref-name">{entity.name}</span>
          {entity.entityType ? (
            <span className="cmp-ref-pick-type">{entity.entityType}</span>
          ) : null}
        </>
      )}
    </ResolvedFrame>
  )
}
