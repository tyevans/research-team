import type { ReactNode } from 'react'

import type { InteractionSummary } from '@domain/interaction/log.ts'

import {
  interactionsHref,
  type InteractionFilters,
  type InteractionKind,
} from '../routing/routes.ts'
import { durationMs } from './duration.ts'

/** What the filtered window adds up to, with every number a way into it.
 *
 * **Each count is a link that applies itself as a filter to the feed below,
 * and that is the whole affordance.** A chart would say the same thing and
 * leave a reader with nowhere to go; a number that narrows the feed turns "418
 * empty results" into the eleven rows that explain it, in one click. The spec
 * calls this worth more than any chart and it is the reason this pane is a
 * list of links rather than a list of figures.
 *
 * **Not every number can be a link, and the ones that cannot are plain text
 * on purpose.** `/events` filters by kind, view, project, install, session and
 * time, and by nothing else -- so `approvals.expanded` and each row of
 * `friction.empty_by_where` have no filter that expresses them. Rendering them
 * as links to the nearest expressible thing would be worse than rendering them
 * flat: a reader who clicks "61 in search" and gets every empty result in the
 * window has been told a lie about what they asked for. They link to their
 * kind where they have one, and say so.
 *
 * Medians throughout, and `—` where there is nothing to take a median of. Zero
 * is a real dwell and a real latency; the em-dash is the absence, and the two
 * must not share a spelling. See `duration.ts`.
 */
export const SummaryPanel = ({
  summary,
  filters,
}: {
  summary: InteractionSummary
  filters: InteractionFilters
}) => {
  /** A link that keeps the current window and replaces the axes it names.
   *
   * Replaces rather than adds: clicking `ViewExited` from a feed already
   * filtered to `SearchPerformed` means "now show me these", not "show me
   * both". Time, project and install survive, because those are the window
   * a reader set up before they started exploring inside it. */
  const narrow = (over: Partial<InteractionFilters>): string =>
    interactionsHref({ ...filters, kinds: [], views: [], ...over })

  return (
    <section aria-label="Summary" className="flex flex-col gap-4 px-3 py-2">
      <Block heading="By kind">
        <ul className="m-0 flex list-none flex-wrap gap-x-4 gap-y-1 p-0">
          {summary.byKind.map((count) => (
            <li key={count.kind} className="font-mono text-xs">
              <a href={narrow({ kinds: [count.kind as InteractionKind] })}>
                {count.kind} <Figure>{count.count}</Figure>
              </a>
            </li>
          ))}
        </ul>
      </Block>

      <Block heading="By view">
        {summary.byView.length === 0 ? (
          <p className="m-0 text-sm text-fg-faint">No views in this window.</p>
        ) : (
          <table className="w-full text-left font-mono text-xs">
            <thead className="text-fg-faint">
              <tr>
                <th scope="col">view</th>
                <th scope="col">entries</th>
                <th scope="col">exits</th>
                <th scope="col">dwell median</th>
                <th scope="col">dwell p90</th>
                <th scope="col">hidden median</th>
              </tr>
            </thead>
            <tbody>
              {summary.byView.map((row) => (
                <tr key={row.view}>
                  <th scope="row" className="font-normal">
                    <a href={narrow({ views: [row.view] })}>{row.view}</a>
                  </th>
                  <td>
                    <a href={narrow({ views: [row.view], kinds: ['ViewEntered'] })}>
                      <Figure>{row.entries}</Figure>
                    </a>
                  </td>
                  {/* Beside `entries` rather than folded into it: the
                      difference is the count of views left by a route the
                      page-hide flush did not catch, and a single number
                      would hide it. */}
                  <td>
                    <a href={narrow({ views: [row.view], kinds: ['ViewExited'] })}>
                      <Figure>{row.exits}</Figure>
                    </a>
                  </td>
                  <td>{durationMs(row.dwellMsMedian)}</td>
                  <td>{durationMs(row.dwellMsP90)}</td>
                  <td>{durationMs(row.hiddenMsMedian)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Block>

      <Block heading="Friction">
        <ul className="m-0 flex list-none flex-wrap gap-x-4 gap-y-1 p-0">
          <li className="font-mono text-xs">
            <a href={narrow({ kinds: ['ActionUndone'] })}>
              undone <Figure>{summary.friction.undone}</Figure>
            </a>
          </li>
          <li className="font-mono text-xs">
            <a href={narrow({ kinds: ['ActionRetried'] })}>
              retried <Figure>{summary.friction.retried}</Figure>
            </a>
          </li>
          <li className="font-mono text-xs">
            <a href={narrow({ kinds: ['EmptyResultEncountered'] })}>
              empty results <Figure>{summary.friction.emptyResults}</Figure>
            </a>
          </li>
          <li className="font-mono text-xs">
            <a href={narrow({ kinds: ['SearchPerformed'] })}>
              repeat searches <Figure>{summary.friction.repeatSearches}</Figure>
            </a>
          </li>
        </ul>
        {/* A pointer to a stream worth reading, never a measurement -- the
            server counts a search within a normalised edit distance of the one
            before it, and the threshold is a tuned constant. Said on screen
            rather than only in a docstring, because the number is next to four
            that are exact. */}
        <p className="m-0 text-xs text-fg-faint">
          Repeat searches are a heuristic: a search close to the one before it in the same browser
          session.
        </p>
        {summary.friction.emptyByWhere.length > 0 ? (
          <p className="m-0 font-mono text-xs text-fg-dim">
            empty in{' '}
            {summary.friction.emptyByWhere
              .map((place) => `${place.where} (${place.count})`)
              .join(', ')}
          </p>
        ) : null}
      </Block>

      <Block heading="Approvals">
        <ul className="m-0 flex list-none flex-wrap gap-x-4 gap-y-1 p-0">
          <li className="font-mono text-xs">
            <a href={narrow({ kinds: ['ApprovalDecided'] })}>
              decided <Figure>{summary.approvals.total}</Figure>
            </a>
          </li>
          {summary.approvals.byDecision.map((decision) => (
            <li key={decision.decision} className="font-mono text-xs">
              <a href={narrow({ kinds: ['ApprovalDecided'] })}>
                {decision.decision} <Figure>{decision.count}</Figure>
              </a>
            </li>
          ))}
          {/* Plain text: no filter expresses `expanded_details`, and a link to
              every approval would answer a question nobody asked. */}
          <li className="font-mono text-xs text-fg-dim">
            details opened <Figure>{summary.approvals.expanded}</Figure>
          </li>
        </ul>
        <p className="m-0 font-mono text-xs text-fg-dim">
          median latency {durationMs(summary.approvals.medianLatencyMs)} — with details{' '}
          {durationMs(summary.approvals.medianLatencyMsExpanded)}, without{' '}
          {durationMs(summary.approvals.medianLatencyMsPlain)}
        </p>
        {/* `expanded` counts readers who opened Edit or Respond, so a careful
            reader who deliberates and then presses plain Approve records
            false. The server's own docstring says the name overstates it; the
            caveat is repeated here rather than the number renamed, because
            every plausible rename has the same ambiguity one word further
            out. */}
        <p className="m-0 text-xs text-fg-faint">
          “Details opened” is a floor on deliberation, not a count of who read carefully: it counts
          readers who opened Edit or Respond.
        </p>
      </Block>
    </section>
  )
}

const Block = ({ heading, children }: { heading: string; children: ReactNode }) => (
  <div className="flex flex-col gap-1">
    <h3 className="m-0 text-sm text-fg-dim">{heading}</h3>
    {children}
  </div>
)

/** The number itself, marked up so a test can ask for it and a reader's eye
 *  can find it in a run of monospace words. */
const Figure = ({ children }: { children: number }) => (
  <strong className="text-fg">{children}</strong>
)
