import { useQuery } from '@tanstack/react-query'

import { useContainer } from '@app/container-context.tsx'
import { queryKeys } from '@application/queries/keys.ts'
import { BrowserSessionId } from '@domain/shared/identifier.ts'

import { Button, ErrorBox, Loading } from '../common/primitives.tsx'
import {
  NO_INTERACTION_FILTERS,
  interactionsHref,
  type InteractionFilters,
} from '../routing/routes.ts'
import { navigate, useRoute } from '../routing/use-route.ts'
import { FilterBar } from './FilterBar.tsx'
import { HealthStrip } from './HealthStrip.tsx'
import { InteractionFeed } from './InteractionFeed.tsx'
import { SummaryPanel } from './SummaryPanel.tsx'

/** The interaction log's reader.
 *
 * Four regions top to bottom -- health, filters, summary, feed -- in the order
 * a person asks the questions: is the instrument working, which slice am I
 * looking at, what does it add up to, and what actually happened. The order is
 * the spec's and the reason is that a reading is worth nothing until the
 * instrument has been vouched for.
 *
 * **The route is the state.** Filters come from `useRoute()` and every change
 * goes back out through `navigate`, so there is no component state on this
 * page except one disclosure per feed row. That is what makes a filtered log
 * something a person can send.
 *
 * **The drill-down is not a fifth region; it is the feed under one filter.**
 * `browserSessionId` in the route swaps `/events` for `/sessions/{id}`, which
 * answers the whole visit in order and unpaged. Two components would be two
 * places to fix a row's rendering, and the rows are the same rows.
 *
 * **Every query renders its own error.** `retry: false` and a visible
 * `ErrorBox`, not a silent empty state: this is the one surface in the console
 * whose purpose is that a broken instrument stops looking like an idle user,
 * and a failed fetch drawn as "no events" would be that exact failure at the
 * top of the page built to catch it.
 */
export const InteractionsView = () => {
  const route = useRoute()
  // Total rather than asserted: `App.tsx` renders this only for the
  // `interactions` route, but a component that reads a field off a union it
  // did not check is one refactor from a crash, and the unfiltered log is the
  // honest answer to "no filters were given".
  const filters: InteractionFilters =
    route.name === 'interactions' ? route.filters : NO_INTERACTION_FILTERS

  const { interactionLog } = useContainer()
  const drillingInto = filters.browserSessionId

  const health = useQuery({
    queryKey: queryKeys.interactions.health(),
    queryFn: () => interactionLog.health(),
    retry: false,
    // The feed is not a live tail -- a websocket for a debugging surface is a
    // second transport to maintain -- so the page catches up on an interval.
    // Ten seconds rather than one: nothing here is being watched in real time,
    // and a request per second forever is a cost paid by whoever leaves the
    // tab open.
    refetchInterval: REFETCH_MS,
  })

  const summary = useQuery({
    queryKey: queryKeys.interactions.summary(filters),
    queryFn: () => interactionLog.summary(filters),
    retry: false,
    refetchInterval: REFETCH_MS,
  })

  const feed = useQuery({
    queryKey: queryKeys.interactions.events(filters),
    queryFn: () => interactionLog.events(filters),
    retry: false,
    refetchInterval: REFETCH_MS,
    enabled: drillingInto === null,
  })

  const stream = useQuery({
    queryKey: queryKeys.interactions.session(BrowserSessionId(drillingInto ?? '')),
    queryFn: () => interactionLog.session(BrowserSessionId(drillingInto ?? '')),
    retry: false,
    refetchInterval: REFETCH_MS,
    enabled: drillingInto !== null,
  })

  const change = (next: InteractionFilters) => navigate(interactionsHref(next))

  return (
    <div className="lay-pane-body flex flex-col gap-2">
      <h1 className="m-0 px-3 pt-3 text-xl">Interaction log</h1>

      {health.isPending ? <Loading what="log health" /> : null}
      {health.isError ? (
        <ErrorBox
          heading="The log's health could not be read."
          message={messageOf(health.error)}
          onRetry={() => void health.refetch()}
        />
      ) : null}
      {health.data ? <HealthStrip health={health.data} /> : null}

      <FilterBar
        filters={filters}
        seenViews={summary.data?.byView.map((row) => row.view) ?? []}
        onChange={change}
      />

      {summary.isError ? (
        <ErrorBox
          heading="The summary could not be read."
          message={messageOf(summary.error)}
          onRetry={() => void summary.refetch()}
        />
      ) : null}
      {summary.data ? <SummaryPanel summary={summary.data} filters={filters} /> : null}

      {drillingInto === null ? (
        <section aria-label="Events" className="flex flex-col gap-1">
          <h2 className="m-0 px-3 text-sm text-fg-dim">
            {/* `total` is the count under the filter, never the page length --
                a reader who cannot tell 200-of-200 from 200-of-9000 cannot
                tell a filter that found everything from one that hit the
                cap. */}
            Feed
            {feed.data ? (
              <span className="font-mono text-xs text-fg-faint">
                {' '}
                {feed.data.events.length} of {feed.data.total}, newest first
              </span>
            ) : null}
          </h2>
          {feed.isPending ? <Loading what="events" /> : null}
          {feed.isError ? (
            <ErrorBox
              heading="The events could not be read."
              message={messageOf(feed.error)}
              onRetry={() => void feed.refetch()}
            />
          ) : null}
          {feed.data ? (
            <InteractionFeed events={feed.data.events} order="newest" filters={filters} />
          ) : null}
        </section>
      ) : (
        <section aria-label="Browser session" className="flex flex-col gap-1">
          <div className="flex flex-wrap items-baseline gap-2 px-3">
            <h2 className="m-0 text-sm text-fg-dim">
              Browser session <span className="font-mono">{drillingInto}</span>
            </h2>
            <span className="text-xs text-fg-faint">oldest first, with the gap between events</span>
            <Button
              small
              tone="quiet"
              onClick={() => change({ ...filters, browserSessionId: null })}
            >
              Back to all events
            </Button>
          </div>
          {stream.isPending ? <Loading what="this session" /> : null}
          {stream.isError ? (
            <ErrorBox
              heading="That browser session could not be read."
              message={messageOf(stream.error)}
              onRetry={() => void stream.refetch()}
            />
          ) : null}
          {stream.data ? (
            <InteractionFeed events={stream.data} order="ascending" filters={filters} />
          ) : null}
        </section>
      )}
    </div>
  )
}

const REFETCH_MS = 10_000

/** An error the reader can act on, or a sentence saying there isn't one.
 *
 * `String(error)` would render `[object Object]` for a rejection that is not
 * an `Error`, which is the least useful thing this page could say. */
const messageOf = (error: unknown): string =>
  error instanceof Error ? error.message : 'The request failed with no message.'
