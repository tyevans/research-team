/** The provider pair and the band fixture the two `TimelineWidget` suites
 *  share.
 *
 * A module rather than a copy in each file, unlike `GraphWidget`'s pair: the
 * browser suite here renders the *real* `TimelineCanvas`, which returns `null`
 * when no band has a usable span (`TimelineCanvas.tsx:120`). A fixture that
 * drifted into unusable dates in one file would make that suite measure an
 * empty box and pass for the wrong reason, with the jsdom file still green
 * because its canvas is mocked. One `band()` is what stops the two disagreeing
 * about what a drawable timeline looks like.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import { vi } from 'vitest'

import type { Container as AppContainer } from '@app/container.ts'
import { ContainerProvider } from '@app/container-context.tsx'
import { ProjectId } from '@domain/shared/identifier.ts'

export const PROJECT = ProjectId('11111111-1111-4111-8111-111111111111')

/** One drawable band. Real ISO bounds, and distinct ones per call, because
 *  `spanOf` returns null for a set with no parseable dates and the canvas then
 *  renders nothing at all. */
export const band = (id: string, start = '0300-01-01', end = '0400-01-01') => ({
  id,
  name: `Entity ${id}`,
  entityType: 'Person',
  extent: 'AD 300–400',
  start,
  end,
  precision: 'year',
  uncertainty: '',
})

/** `timelines`, plural, is the key the container really exposes
 *  (`container.ts`). The `as unknown as AppContainer` cast below makes a wrong
 *  key typecheck cleanly and resolve to nothing at runtime, so the symptom
 *  would be a widget stuck in `isPending` forever rather than a type error --
 *  which is why the key is named here once instead of in each test. */
export const harness = (timeline: ReturnType<typeof vi.fn>, retry: number | boolean = false) => {
  const container = { timelines: { timeline } } as unknown as AppContainer
  // `retry` is a parameter rather than a constant so one test can stand the
  // client up the way `main.tsx:27` really does (`retry: 1`) and check that
  // the widget's own policy overrides it. Every other test wants the quiet
  // default, because a retry there is only a slower failure.
  const client = new QueryClient({ defaultOptions: { queries: { retry } } })
  return ({ children }: { children: ReactNode }) => (
    <ContainerProvider container={container}>
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    </ContainerProvider>
  )
}
