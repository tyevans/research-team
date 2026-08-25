/** A course's cluster membership, grouped for scanning rather than for reading.
 *
 * A pure fold beside `entity-tree.ts`, and deliberately not that module: the
 * two sort the same-looking data by different keys for different questions,
 * and one function with a mode flag would be an abstraction over a
 * coincidence of shape. `groupByType` answers "find the entity I am looking
 * for" and sorts everything by name; this answers "what is this cluster made
 * of, and why does the course exist", where the answer is the biggest type
 * and its most central members.
 */

import type { AreaMember } from './curriculum.ts'

/** One type's members of a cluster. There is no empty group, for
 *  `EntityGroup`'s reason: a heading that opens onto nothing is what a filter
 *  applied after grouping leaves behind. */
export interface MemberGroup {
  readonly entityType: string
  readonly members: readonly AreaMember[]
}

/** Group a cluster's members by type, optionally narrowed to a substring of
 *  their names.
 *
 * **Filtering happens before grouping**, and that ordering is the contract --
 * `groupByType`'s, held to for the same reason: done the other way a type
 * with no matching member keeps its heading and its count disagrees with what
 * opening it shows.
 *
 * Groups are ordered by size, largest first, ties broken by `localeCompare`.
 * That is the one place this deliberately parts from `groupByType`'s
 * alphabetical order: the entity tree is an index, where alphabetical is how
 * you look something up, and this list is evidence, where the largest type is
 * the claim the reader came to check. The tie-break is not cosmetic -- two
 * types of equal size are otherwise left in `Map` insertion order, which is
 * whatever order the server happened to send, so the list would reshuffle
 * between two responses that say the same thing.
 *
 * Within a group, members are ordered by `centrality`, highest first, ties
 * broken by name. `centrality` arrives on every `AreaMember` and, before this
 * fold, was read by nothing in the console at all -- the wire has carried it
 * since the area projection shipped. Comparing it *within one area* is what
 * its own docstring permits; nothing here compares it across areas.
 *
 * `localeCompare` rather than `<` in both tie-breaks, for `groupByType`'s
 * reason: a code-point sort puts `Ångström` after `Zeta`, which is wrong in
 * the only sense that matters for a list a person scans.
 */
export const groupMembers = (
  members: readonly AreaMember[],
  filter?: string,
): readonly MemberGroup[] => {
  const needle = (filter ?? '').trim().toLowerCase()
  const matching =
    needle === '' ? members : members.filter((m) => m.name.toLowerCase().includes(needle))

  const byType = new Map<string, AreaMember[]>()
  for (const member of matching) {
    const existing = byType.get(member.entityType)
    if (existing) existing.push(member)
    else byType.set(member.entityType, [member])
  }

  return [...byType.entries()]
    .sort(([leftType, left], [rightType, right]) =>
      right.length !== left.length ? right.length - left.length : leftType.localeCompare(rightType),
    )
    .map(([entityType, group]) => ({
      entityType,
      members: [...group].sort((left, right) =>
        right.centrality !== left.centrality
          ? right.centrality - left.centrality
          : left.name.localeCompare(right.name),
      ),
    }))
}

/** How many members a filter keeps.
 *
 * Derived from `groupMembers` rather than re-filtering, because the number a
 * reader is told ("12 of 66 match") has to be the number of rows the same
 * render puts on the screen. A second `filter()` here would be a second place
 * for the matching rule to be defined, and the two would agree until one of
 * them was changed.
 */
export const countMatching = (members: readonly AreaMember[], filter?: string): number =>
  groupMembers(members, filter).reduce((total, group) => total + group.members.length, 0)
