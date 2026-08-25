import { useState } from 'react'

import { countMatching, groupMembers } from '@domain/knowledge/course-members.ts'
import type { AreaMember } from '@domain/knowledge/curriculum.ts'
import type { ProjectId } from '@domain/shared/identifier.ts'

import { Disclosure } from '../common/primitives.tsx'
import { projectHref } from '../routing/routes.ts'

/** Above this many members, the fold offers a filter box.
 *
 * 12 is **chosen, not measured**: it is roughly where a wrapped list stops
 * being one glance and starts being a thing you scan. Below it a search box is
 * one more control for a keyboard user to tab past on the way to the names,
 * and it can only ever remove rows that were already all visible.
 */
const FILTER_ABOVE = 12

/** A member's row. Wrapping inline items rather than one row each, and that is
 *  the whole compaction: sixty-six one-line rows are a page, sixty-six
 *  wrapped names are a paragraph-sized block. It is affordable here and was
 *  not before, because grouping by type moved the type off every row -- the
 *  group heading says it once.
 *
 * `lay-ring-inward` rather than a `focus-visible:outline-offset-*` utility.
 * See CLAUDE.md: `tokens.css`'s global `:focus-visible` is unlayered, so it
 * beats anything Tailwind emits into `@layer utilities` whatever the
 * specificity, and the utility would be inert while looking applied. */
const NAME = 'focus-visible:lay-ring-inward text-fg no-underline hover:underline'

/** The cluster's membership: collapsed to one line, opened on demand.
 *
 * This used to be a flat `<ul>` of every member below the authored course
 * text, with the type repeated on all sixty-six rows. On a real course it was
 * longer than the course. The list is not reading material -- it is the
 * evidence for why this course exists, consulted rather than read -- so the
 * default is a count and the detail is one keystroke away.
 *
 * Three decisions and what each cost:
 *
 * - **Collapsed by default.** A reader who wants the membership pays one
 *   click; a reader who does not pays nothing. Rejected: showing the first N
 *   with a "show all". It answers a question nobody asked (which N?) and the
 *   truncation point is arbitrary in a way a fold is not.
 * - **Grouped by type.** The type was already on every row, so grouping
 *   removes text rather than adding it, and the group counts are the shape of
 *   the cluster -- the thing a reader checking "why is this a course" is
 *   actually after. Groups open by default once the outer fold is open:
 *   opening it is an explicit "show me", and a screen of closed headings
 *   would answer it with a second screen of buttons.
 * - **A filter above `FILTER_ABOVE`.** `type="search"` with an `aria-label`,
 *   matching `EntityTreePane`'s box word for word, and filtering before
 *   grouping so a type whose members all fail the filter loses its heading
 *   too (`groupMembers` holds that contract).
 *
 * Presentational and fetch-free: every state is one render away in a test.
 *
 * The `<section>` is a labelled region rather than carrying the `<h3>` it
 * replaced, and that is a real loss -- a screen-reader user navigating this
 * page by heading no longer stops here. The alternative was a heading
 * wrapping the toggle, which cannot use `Disclosure` (a `<button>` takes
 * phrasing content, and `<h3>` is not) and would have meant a second
 * disclosure implementation on the page for the sake of one element.
 */
export const CourseMembers = ({
  projectId,
  members,
}: {
  projectId: ProjectId
  members: readonly AreaMember[]
}) => {
  const [open, setOpen] = useState(false)
  const [term, setTerm] = useState('')
  // Which type groups the reader has folded away. Empty means every group is
  // open, so a group that appears when a filter is cleared is open too --
  // where a set of *open* types would have to be re-seeded whenever the
  // filter changed the set of types, and a group nobody had ever seen would
  // arrive closed.
  const [collapsed, setCollapsed] = useState<ReadonlySet<string>>(new Set())

  if (members.length === 0) {
    return (
      <section className="crs-course-members">
        <p className="m-0 text-xs text-fg-faint">No entities in this cluster.</p>
      </section>
    )
  }

  const filtering = members.length > FILTER_ABOVE
  const active = filtering ? term : ''
  const groups = groupMembers(members, active)
  const matched = countMatching(members, active)

  const toggleGroup = (entityType: string) =>
    setCollapsed((current) => {
      const next = new Set(current)
      if (next.has(entityType)) next.delete(entityType)
      else next.add(entityType)
      return next
    })

  return (
    <section className="crs-course-members" aria-label="Cluster membership">
      <Disclosure
        open={open}
        onToggle={() => setOpen(!open)}
        label={`${members.length} entities in this cluster`}
      >
        <div className="flex flex-col gap-2 pt-1">
          {filtering && (
            <input
              type="search"
              className="input min-w-0"
              placeholder="Filter these entities"
              aria-label="Filter these entities"
              value={term}
              onChange={(event) => setTerm(event.target.value)}
            />
          )}

          {/* `role="status"` and not a bare `<p>`: the filter changes the list
              silently for anyone who cannot see it shrink, and the count is
              the only thing that says the typing did something. Rendered only
              while a filter is active, so an untouched fold does not announce
              a number that is just `members.length` again. */}
          {active.trim() !== '' && (
            <p role="status" className="m-0 text-xs text-fg-dim">
              {matched} of {members.length} match
            </p>
          )}

          {groups.length === 0 ? (
            <p className="m-0 text-xs text-fg-faint">Nothing matched. Try a shorter term.</p>
          ) : (
            <ul className="m-0 flex list-none flex-col gap-1 p-0">
              {groups.map((group) => (
                <li key={group.entityType}>
                  <Disclosure
                    open={!collapsed.has(group.entityType)}
                    onToggle={() => toggleGroup(group.entityType)}
                    label={
                      <>
                        {/* The count is what makes a folded group informative,
                            `EntityTree`'s reason: without it a closed list
                            says only which types exist.

                            The separator between the two spans is a real text
                            node and has to be. Accessible-name computation
                            concatenates text nodes and knows nothing about
                            the flex gap, so without it the button is named
                            "person2" -- measured, the test asserting
                            "person 2" failed exactly that way. A space *inside*
                            the count's span does not work and was tried: name
                            computation trims each node, so the leading space is
                            dropped and the button is named "person2" again.
                            `EntityTree` has the same defect and is left alone
                            here, being another surface.

                            Prettier reflows the `{' '}` onto the end of the
                            line above, where it reads like trailing whitespace.
                            It is not; deleting it renames the button. */}
                        <span className="min-w-0 overflow-hidden text-ellipsis whitespace-nowrap">
                          {group.entityType}
                        </span>{' '}
                        <span className="ml-auto shrink-0 text-fg-dim">{group.members.length}</span>
                      </>
                    }
                  >
                    <ul className="m-0 flex list-none flex-wrap gap-x-3 gap-y-[2px] p-0 pl-[14px] text-xs">
                      {group.members.map((member) => (
                        <li key={member.entityId} className="flex items-baseline gap-1">
                          <a
                            href={projectHref(projectId, {
                              facet: 'entity',
                              id: member.entityId,
                            })}
                            className={NAME}
                          >
                            {member.name}
                          </a>
                          {member.temporal !== null && (
                            <span className="font-mono text-fg-faint">{member.temporal}</span>
                          )}
                        </li>
                      ))}
                    </ul>
                  </Disclosure>
                </li>
              ))}
            </ul>
          )}
        </div>
      </Disclosure>
    </section>
  )
}
