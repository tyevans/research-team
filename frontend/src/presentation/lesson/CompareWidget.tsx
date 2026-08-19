import type { AttemptsApi } from '@application/lesson/use-attempts.ts'
import { useEntityReference } from '@application/lesson/use-entity-reference.ts'
import type { ComponentBlock } from '@domain/lesson/document.ts'
import { readCompare } from '@domain/lesson/widgets.ts'
import type { ProjectId } from '@domain/shared/identifier.ts'

import { ResolvedFrame, ResolvedName } from './ResolvedFrame.tsx'
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
    // `missing` and `unavailable` are prose, which is what keeps a mixed table
    // a table: this widget mounts several frames at once, so an error panel
    // per head would turn one unextracted name into a grid of boxes.
    //
    // `ambiguous` is the exception and is kept deliberately. It draws a
    // paragraph and up to eight buttons *inside a `<th>`*, so a header row of
    // three ambiguous names is three stacked pickers -- genuinely ugly, and
    // the reason a comment is needed here at all. It is kept because a head
    // with no picker can never be disambiguated, and an unresolvable head can
    // never be linked; linking is the whole of what this widget adds over a
    // markdown table, so suppressing the picker to tidy the header would
    // trade the feature for the cosmetics. `CompareWidget.test.tsx` pins what
    // an ambiguous header actually does, including that picking turns the
    // head into a link -- red against any later attempt to suppress it
    // quietly.
    <ResolvedFrame reference={resolved} name={name}>
      {(entity) => (
        <>
          <ResolvedName projectId={projectId} entity={entity} />
          {entity.entityType ? (
            <span className="cmp-ref-pick-type">{entity.entityType}</span>
          ) : null}
        </>
      )}
    </ResolvedFrame>
  )
}
