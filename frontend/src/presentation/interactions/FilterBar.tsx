import { useId } from 'react'

import { Button } from '../common/primitives.tsx'
import {
  INTERACTION_KINDS,
  NO_INTERACTION_FILTERS,
  type InteractionFilters,
  type InteractionKind,
} from '../routing/routes.ts'

/** Which slice of the log is on screen, and the only way to change it.
 *
 * **It holds no state.** Every control reads from `filters` and every change
 * goes out through `onChange`, which the view turns into a navigation. That is
 * not a stylistic preference about lifting state: the filters are in the URL
 * (`interactionsHref`), and a bar with its own copy would let the address bar
 * and the controls disagree -- at which point a reader who sends somebody the
 * link sends them a different reading of the log than the one they were
 * looking at. A filtered log is linkable or it is a paragraph of instructions.
 *
 * **The kind list comes from the vocabulary, never from the data.** This is
 * the same rule the health route's `kinds` dict follows and it is the reason
 * this page exists: a kind that has never been emitted must be selectable, or
 * the filter cannot express "show me the thing I think is broken", which is
 * the first question anybody brings here. A list built from what the table
 * happens to hold makes "never emitted" and "does not exist" identical.
 *
 * The view list cannot follow that rule and does not pretend to -- a view name
 * is a free string minted by the router, with no closed vocabulary anywhere to
 * enumerate. So it is built from what has been seen, plus whatever the current
 * filter names: without that second half, filtering to a view and then
 * narrowing the window until that view has no rows would leave a checkbox
 * nobody could untick.
 */
export const FilterBar = ({
  filters,
  seenViews,
  onChange,
}: {
  filters: InteractionFilters
  /** Views present in the current summary. Not authoritative; see above. */
  seenViews: readonly string[]
  onChange: (next: InteractionFilters) => void
}) => {
  const views = [...new Set([...seenViews, ...filters.views])].sort()
  const filtered =
    filters.kinds.length > 0 ||
    filters.views.length > 0 ||
    filters.projectId !== null ||
    filters.installId !== null ||
    filters.browserSessionId !== null ||
    filters.since !== null ||
    filters.until !== null

  return (
    <section aria-label="Filters" className="flex flex-col gap-2 px-3 py-2">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-xs text-fg-faint">window</span>
        {WINDOWS.map((window) => (
          <Button
            key={window.label}
            small
            tone="quiet"
            onClick={() => onChange({ ...filters, since: sinceFor(window.ms), until: null })}
          >
            {window.label}
          </Button>
        ))}
        <Text
          label="from"
          value={filters.since}
          onCommit={(since) => onChange({ ...filters, since })}
        />
        <Text
          label="to"
          value={filters.until}
          onCommit={(until) => onChange({ ...filters, until })}
        />
        {filtered ? (
          <Button small onClick={() => onChange(NO_INTERACTION_FILTERS)}>
            Clear filters
          </Button>
        ) : null}
      </div>

      <Checkboxes
        legend="kinds"
        options={INTERACTION_KINDS}
        chosen={filters.kinds}
        onToggle={(kind) =>
          onChange({ ...filters, kinds: toggle(filters.kinds, kind as InteractionKind) })
        }
      />

      {views.length > 0 ? (
        <Checkboxes
          legend="views"
          options={views}
          chosen={filters.views}
          onToggle={(view) => onChange({ ...filters, views: toggle(filters.views, view) })}
        />
      ) : null}

      <div className="flex flex-wrap items-center gap-3">
        <Text
          label="project"
          value={filters.projectId}
          onCommit={(projectId) => onChange({ ...filters, projectId })}
        />
        <Text
          label="install"
          value={filters.installId}
          onCommit={(installId) => onChange({ ...filters, installId })}
        />
      </div>
    </section>
  )
}

/** The presets, as offsets rather than as named ranges.
 *
 * Each writes an absolute `since` at the moment it is pressed, which is what
 * makes the result linkable -- `?since=last-hour` sent to somebody tomorrow is
 * a different hour, and the whole grammar's promise is that a link is the
 * reading you were looking at.
 *
 * The cost, and it is the reason no preset renders as selected: a window
 * written as an instant cannot be recognised again a minute later, so there is
 * no honest way to draw "last hour" as the current choice. The from/to boxes
 * beside them show the truth, and they are the state. `all` clears both, which
 * *is* recognisable -- it is simply the absence of a filter, and the Clear
 * button already says so.
 */
const HOUR = 3_600_000
const WINDOWS = [
  { label: 'last hour', ms: HOUR },
  { label: 'last day', ms: 24 * HOUR },
  { label: 'last week', ms: 7 * 24 * HOUR },
  { label: 'all', ms: null },
] as const

const sinceFor = (ms: number | null): string | null =>
  ms === null ? null : new Date(Date.now() - ms).toISOString()

const toggle = <T extends string>(chosen: readonly T[], value: T): readonly T[] =>
  chosen.includes(value) ? chosen.filter((one) => one !== value) : [...chosen, value]

const Checkboxes = ({
  legend,
  options,
  chosen,
  onToggle,
}: {
  legend: string
  options: readonly string[]
  chosen: readonly string[]
  onToggle: (value: string) => void
}) => (
  // `border-0` with no width utility beside it, which is the one shape
  // `CLAUDE.md`'s two border entries both permit: this build imports no
  // Tailwind preflight, so a `<fieldset>` keeps the user agent's own 2px
  // groove, and `border-0` is here to remove it rather than to zero the three
  // sides of a directional border. Nothing draws an edge in this bar.
  <fieldset className="m-0 flex flex-wrap items-center gap-2 border-0 p-0">
    <legend className="float-left text-xs text-fg-faint">{legend}</legend>
    {options.map((option) => (
      <label key={option} className="flex items-center gap-1 font-mono text-xs">
        <input
          type="checkbox"
          checked={chosen.includes(option)}
          onChange={() => onToggle(option)}
        />
        {option}
      </label>
    ))}
  </fieldset>
)

/** A box whose value is the route's, committed on Enter or on leaving it.
 *
 * Not on every keystroke: each commit is a navigation and a refetch, so typing
 * a UUID would be thirty-six history entries and thirty-six requests. `key` on
 * the route's own value rather than a controlled input -- the box is
 * uncontrolled while it is being typed in, and remounts when the route changes
 * underneath it, which is what makes the Clear button empty it.
 */
const Text = ({
  label,
  value,
  onCommit,
}: {
  label: string
  value: string | null
  onCommit: (next: string | null) => void
}) => {
  const id = useId()
  return (
    <span className="flex items-center gap-1">
      <label className="text-xs text-fg-faint" htmlFor={id}>
        {label}
      </label>
      <input
        id={id}
        key={value ?? ''}
        defaultValue={value ?? ''}
        className="input font-mono text-xs"
        size={12}
        onBlur={(event) => commit(event.currentTarget.value, value, onCommit)}
        onKeyDown={(event) => {
          if (event.key === 'Enter') commit(event.currentTarget.value, value, onCommit)
        }}
      />
    </span>
  )
}

const commit = (
  raw: string,
  current: string | null,
  onCommit: (next: string | null) => void,
): void => {
  const next = raw.trim() === '' ? null : raw.trim()
  // Nothing to do when a blur follows a focus that changed nothing, which is
  // most blurs. Without this every tab through the bar is a navigation.
  if (next !== current) onCommit(next)
}
