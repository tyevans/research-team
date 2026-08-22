import { contestedEdges, stepsOf, type Curriculum } from '@domain/knowledge/curriculum.ts'

/** The path, as an ordered list with its reasoning beside it.
 *
 * **Not a graph drawing**, and that is the decision worth defending. A
 * force-directed picture of the prerequisite digraph looks impressive and
 * cannot answer the question a reader actually has, which is "why is this
 * second". An ordered list with the reason on each step answers exactly that,
 * and it stays readable at forty areas where a drawing does not.
 *
 * Contested edges are lifted to the top rather than left inline on their
 * steps. They are the one thing about an order a reader should be interrupted
 * for — the order had to break a real mutual dependency to exist — and one
 * buried per step is one nobody reads.
 */
export const PathSteps = ({
  curriculum,
  selected,
  areaHref,
}: {
  curriculum: Curriculum
  selected: string | null
  areaHref: (slug: string) => string
}) => {
  const steps = stepsOf(curriculum)
  const contested = contestedEdges(curriculum)

  if (steps.length === 0) {
    return (
      <p className="m-0 p-4 text-sm text-fg-dim">
        There is no path yet, because there are no learning areas to order.
      </p>
    )
  }

  return (
    <div className="flex flex-col gap-3">
      {contested.length > 0 && (
        <div className="rounded-md border border-line bg-bg-panel p-3">
          <p className="font-medium m-0 text-sm">
            {contested.length === 1
              ? 'One pair of areas depends on itself.'
              : `${contested.length} pairs of areas depend on each other.`}
          </p>
          <p className="mt-1 mb-2 text-xs text-fg-dim">
            The order below is one defensible reading, not the only one. Where two areas cite each
            other, any linear sequence through them is a simplification.
          </p>
          <ul className="m-0 flex list-none flex-col gap-1 p-0">
            {contested.map((edge) => (
              <li key={`${edge.before}->${edge.after}`} className="text-xs text-fg-dim">
                <code>{edge.before}</code> and <code>{edge.after}</code> — {edge.reason}
              </li>
            ))}
          </ul>
        </div>
      )}

      <ol className="m-0 flex list-none flex-col gap-2 p-0">
        {steps.map((step) => (
          <li key={step.area.slug}>
            <a
              href={areaHref(step.area.slug)}
              aria-current={step.area.slug === selected ? 'true' : undefined}
              className={[
                'flex gap-3 rounded-md border border-line p-3 text-fg no-underline',
                'focus-visible:lay-ring-inward hover:bg-bg-hover',
                step.area.slug === selected ? 'border-accent bg-bg-raise' : 'bg-bg-panel',
              ].join(' ')}
            >
              <span
                aria-hidden="true"
                className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-bg-panel-2 text-xs text-fg-dim"
              >
                {step.position}
              </span>
              <span className="min-w-0">
                <span className="font-medium block truncate">{step.area.title}</span>
                <span className="block text-xs text-fg-dim">
                  {step.area.size} entities
                  {/* The reason, verbatim from the server. Prose rather than a
                      score, because a score is something a reader can only
                      accept or reject and this is something they can go and
                      check against the graph. */}
                  {step.reason !== null && <> · comes after the previous area: {step.reason}</>}
                  {step.reason === null && step.position > 1 && (
                    <> · nothing in the graph orders this against the area before it</>
                  )}
                </span>
              </span>
            </a>
          </li>
        ))}
      </ol>
    </div>
  )
}
