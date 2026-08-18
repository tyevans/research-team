/** The shape of the shared query policy, pinned as a whole.
 *
 * `retry: false` was already pinned behaviourally by `TimelineWidget.test.tsx`
 * -- a widget that retried would issue a second request there. The other three
 * fields were pinned by nothing at all: `staleTime`, `refetchOnMount` and
 * `refetchOnWindowFocus` are what stop a scrolled-back transcript re-running
 * `GET /timeline`'s double pass over the tenant's entity set on every remount,
 * and deleting any of them changes no test and no rendered output. That is the
 * failure this file exists for -- a silent regression in a cost, not in a
 * result.
 *
 * One assertion on the object rather than four widget tests: the constant is
 * the thing under test, and a per-widget copy would be four names for one
 * claim. It is a change-detector by construction, which is the point -- the
 * fields it guards have no observable behaviour to assert instead.
 */
import { expect, it } from 'vitest'

import { resolvedWidgetQuery } from './resolved-widget.ts'

it('keeps every resolved widget off retry, off refetch, and fresh for five minutes', () => {
  expect(resolvedWidgetQuery).toEqual({
    retry: false,
    staleTime: 5 * 60_000,
    refetchOnMount: false,
    refetchOnWindowFocus: false,
  })
})
