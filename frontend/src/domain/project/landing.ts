import type { ForkNode, SessionSummary } from '../session/session.ts'

/** Fork lineage: turning a flat list of sessions into the forest it describes.
 *
 * **What used to be here and is not.** This module also held `rollups`,
 * `currentSession`, `recencyOf`, `matches` and the `ProjectRollup` type — the
 * whole of how the landing page arranged projects around their sessions. The
 * index does not show sessions any more, so all five had exactly one caller
 * and that caller is deleted; `domain/project/board.ts` is what arranges the
 * index now, out of server-computed counts rather than out of the session
 * list. They are deleted rather than left, because a pure function with no
 * caller still typechecks, still passes its own tests, and reads to the next
 * person as part of the model.
 *
 * What survives is the part that was never about the index: `SessionTree` and
 * the session views rebuild a fork forest, and a fork's parent may belong to
 * another project or to none, which is the one genuinely subtle thing in this
 * file.
 */

/** Every session, flattened out of the forest `/api/tree` answers.
 *
 * The nesting is rebuilt per project below, because a fork's parent may belong
 * to another project (or to none), and lineage that crossed a project boundary
 * would put a session inside a project it is not in. */
export const flatten = (nodes: readonly ForkNode[]): readonly SessionSummary[] =>
  nodes.flatMap((node) => [node as SessionSummary, ...flatten(node.children)])

/** A flat session list rendered as a tree of roots.
 *
 * Used when `/api/tree` answers empty but sessions plainly exist — the
 * projection has drifted, and a flat list is a truthful degradation where "no
 * sessions" is a lie. That choice is the whole content of this function, and it
 * is a claim about sessions rather than about a response: every session is a
 * root, because with the tree gone there is no lineage to be had and inventing
 * one would be worse than admitting to none.
 *
 * Beside `flatten` rather than in `infrastructure/http/mappers.ts`, where it
 * lived, because it never touched a wire type — it takes `SessionSummary` and
 * returns `ForkNode`, both of them domain — so its old address made a
 * presentation hook import the HTTP adapter to reach a decision the domain
 * owns. Deliberately *not* folded into `forest` below: that one rebuilds real
 * lineage and is what to call when the data is trustworthy; this one is the
 * degradation, and a caller should have to name which it means. */
export const summariesAsForest = (summaries: readonly SessionSummary[]): readonly ForkNode[] =>
  summaries.map((summary) => ({ ...summary, children: [] }))

/** Arrange sessions into the forest their fork lineage describes.
 *
 * The browser's copy of `build_fork_tree`, and it exists for the same reason
 * that one does: a session whose parent is absent from the input is a root
 * rather than a session that disappears. Here "absent" is the common case —
 * every partition is one project's sessions, so a fork made from a session in
 * a different project is a root of this one.
 */
export const forest = (summaries: readonly SessionSummary[]): readonly ForkNode[] => {
  const known = new Set(summaries.map((summary) => summary.id))
  const children = new Map<string, SessionSummary[]>()
  const roots: SessionSummary[] = []

  for (const summary of summaries) {
    const parent = summary.forkedFrom
    if (parent !== null && parent !== summary.id && known.has(parent)) {
      const siblings = children.get(parent)
      if (siblings) siblings.push(summary)
      else children.set(parent, [summary])
    } else {
      roots.push(summary)
    }
  }

  const node = (summary: SessionSummary): ForkNode => ({
    ...summary,
    // Children ascending: a fork tree read downwards is a story in the order it
    // happened. Only the roots are newest-first, because that list is scanned
    // rather than read.
    children: (children.get(summary.id) ?? [])
      .slice()
      .sort((a, b) => byStartAscending(a, b))
      .map(node),
  })

  return roots.sort((a, b) => byStartAscending(b, a)).map(node)
}

const byStartAscending = (a: SessionSummary, b: SessionSummary): number =>
  String(a.startedAt ?? '').localeCompare(String(b.startedAt ?? ''))
