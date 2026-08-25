import { describe, expect, it } from 'vitest'

import { NO_FILTERS, type InteractionFilters } from '@domain/interaction/filters.ts'

import { NO_INTERACTION_FILTERS } from './routes.ts'

/** The one duplicated shape in this feature, and the test that stops it
 *  drifting.
 *
 * `filters.ts` explains why there are two: the port lives in `application/`
 * and eslint forbids that layer from importing `@presentation/*`, so the
 * route's type cannot be the one the port names. The cost is a copy, and a
 * copy is a place for a seventh field to be added to one and not the other --
 * which would typecheck at every call site (the route's value would still be
 * assignable to the domain's narrower shape) and would silently drop that
 * field from every query string the repository builds.
 *
 * Both halves are needed. The assignment is compile-time and catches a
 * *renamed* or retyped field; the key comparison is run-time and catches an
 * *added* one, which the assignment alone would let through in exactly the
 * direction that loses data.
 *
 * This test fails, rather than passing vacuously, the moment either module
 * gains a field the other lacks -- proved by adding one to each in turn before
 * trusting it.
 *
 * It lives here rather than beside `filters.ts` because it must import both
 * halves, and `eslint.config.js` forbids anything under `domain/` from naming
 * `@presentation/*` -- test files included, which is the right call: an
 * exception for tests would let the import creep back in under a filename.
 */
describe('the log filter shared with the route grammar', () => {
  it('accepts a parsed route filter without a cast', () => {
    const fromRoute: InteractionFilters = NO_INTERACTION_FILTERS
    expect(fromRoute).toEqual(NO_FILTERS)
  })

  it('carries exactly the fields the route carries', () => {
    // Not `toEqual` on the objects -- that is the assertion above. This is
    // about the *keys*, because a field added to one module with the same
    // empty value would pass a value comparison and still never reach the
    // server.
    const routeKeys = Object.keys(NO_INTERACTION_FILTERS).sort()
    expect(Object.keys(NO_FILTERS).sort()).toEqual(routeKeys)
  })
})
