/** Which slice of the interaction log a reader is looking at.
 *
 * **This is the same shape as `InteractionFilters` in
 * `@presentation/routing/routes.ts`, deliberately declared twice, and that is
 * a seam somebody should close.** The port that reads the log lives in
 * `application/`, and `eslint.config.js` forbids the application layer from
 * importing `@presentation/*` -- correctly, because a use case that knows
 * about the URL grammar is a use case tied to the browser. So the filter
 * cannot be imported from the route module, and the honest place for a query
 * shape is the domain.
 *
 * The two are structurally identical, so a parsed route's filters pass into
 * every method here with no cast and no mapper. The close is one line in
 * `routes.ts` -- import this and re-export it under the old name -- and it
 * belongs to whoever owns that file. Until then, `filtersAgree` in the test
 * beside this file fails if the two drift.
 *
 * Every field is in the URL, which is the routing grammar's own rule: a
 * linkable state is a bookmark, and "the four empty searches on the catalog
 * last Tuesday" is a link or it is a paragraph of instructions.
 *
 * `since` and `until` are the raw strings the URL carried, not `Date`s. They
 * go straight back out as query parameters, so parsing and reformatting here
 * would be a second date format for nobody's benefit -- unlike the instants on
 * a row that came *back*, which get subtracted and are `Date`s for that
 * reason (`log.ts`).
 *
 * Arrays rather than sets, because a `Set` is not structurally comparable and
 * every test over this is `toEqual`. Order is the order the URL carried.
 */
export interface InteractionFilters {
  readonly kinds: readonly string[]
  readonly views: readonly string[]
  readonly projectId: string | null
  readonly installId: string | null
  readonly browserSessionId: string | null
  readonly since: string | null
  readonly until: string | null
}

/** The unfiltered log. */
export const NO_FILTERS: InteractionFilters = {
  kinds: [],
  views: [],
  projectId: null,
  installId: null,
  browserSessionId: null,
  since: null,
  until: null,
}
