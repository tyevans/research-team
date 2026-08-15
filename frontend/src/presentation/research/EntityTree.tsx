import type { EntityGroup } from '@domain/knowledge/entity-tree.ts'

import { Disclosure } from '../common/primitives.tsx'
import { colorForType, KIND_TOKENS } from './entity-colors.ts'

/** An entity row: the same full-width bare button the graph's edge rows and
 *  the search results are, and deliberately the same vocabulary rather than a
 *  third one -- a left gutter that lights up on hover and focus is how this
 *  console says "this one" everywhere else.
 *
 * `border-0` comes first and is not optional: `border-solid` sets the style on
 * all four sides, and with only `border-l-2` giving a width the other three
 * would fall back to the browser's `medium` (~3px), because this build imports
 * no preflight. A rule meant for one edge would draw a box, and no gate
 * catches it.
 *
 * `lay-ring-inward` rather than the `focus-visible:outline-offset-[-2px]`
 * utility, which is inert: `tokens.css`'s global `:focus-visible` is unlayered
 * and beats anything in `@layer utilities` whatever its specificity. The class
 * is in `layout.css` and carries that measurement.
 *
 * `[font:inherit]` because the `font` shorthand has no utility and a `<button>`
 * that does not inherit it renders in the user agent's 13.33px sans. */
const ROW = [
  'flex w-full cursor-pointer items-baseline justify-between gap-2',
  'border-0 border-l-2 border-solid border-l-transparent rounded-md',
  'bg-transparent px-[8px] py-[5px] text-left text-sm text-inherit [font:inherit]',
  'hover:bg-bg-hover hover:border-l-accent',
  'focus-visible:bg-bg-hover focus-visible:border-l-accent',
  'aria-[current=true]:border-l-accent aria-[current=true]:bg-bg-hover',
  'lay-ring-inward',
].join(' ')

/** The project's entities under their types, foldable.
 *
 * Presentational: it holds no open-set of its own and fetches nothing, so
 * every state it can be in is one render away in a test. The pane above it
 * owns openness, because a fold that reset itself whenever extraction landed
 * would be unusable during the one activity that changes this list.
 *
 * **Not `role="tree"`.** ARIA's tree pattern obliges arrow-key navigation,
 * typeahead and a roving tabindex; claiming the role without them tells a
 * screen reader the keyboard does something it does not. Nested lists with
 * disclosure buttons promise only what they deliver.
 *
 * The swatch is `colorForType` against the same `KIND_TOKENS` palette the
 * canvas and the legend use, so a reader who has learnt the graph's colours is
 * not learning a second scheme for the same types.
 */
export const EntityTree = ({
  groups,
  open,
  selected,
  onToggle,
  onSelect,
}: {
  groups: readonly EntityGroup[]
  open: ReadonlySet<string>
  selected: string | null
  onToggle: (entityType: string) => void
  onSelect: (id: string) => void
}) => (
  <ul className="m-0 flex list-none flex-col gap-[2px] p-[4px]">
    {groups.map((group) => (
      <li key={group.entityType}>
        <Disclosure
          open={open.has(group.entityType)}
          onToggle={() => onToggle(group.entityType)}
          label={
            <>
              <span
                aria-hidden="true"
                className="size-[8px] shrink-0 rounded-full"
                style={{ background: `var(${colorForType(group.entityType, KIND_TOKENS)})` }}
              />
              <span className="min-w-0 overflow-hidden text-ellipsis whitespace-nowrap">
                {group.entityType}
              </span>
              {/* The count is what makes a closed group informative. Without
                  it a collapsed tree says only which types exist, which the
                  legend already says. */}
              <span className="ml-auto shrink-0 text-fg-dim">{group.entities.length}</span>
            </>
          }
        >
          <ul className="m-0 flex list-none flex-col gap-[1px] p-0 pl-[14px]">
            {group.entities.map((entity) => (
              <li key={entity.id}>
                <button
                  type="button"
                  className={ROW}
                  aria-current={entity.id === selected}
                  onClick={() => onSelect(entity.id)}
                >
                  <span className="min-w-0 overflow-hidden text-ellipsis whitespace-nowrap">
                    {entity.name}
                  </span>
                  {entity.temporal ? (
                    <span className="shrink-0 font-mono text-xs text-fg-dim">
                      {entity.temporal}
                    </span>
                  ) : null}
                </button>
              </li>
            ))}
          </ul>
        </Disclosure>
      </li>
    ))}
  </ul>
)
