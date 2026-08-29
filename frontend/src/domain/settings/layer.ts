import type { Scope } from './spec.ts'

/** Where a value came from, and what "clearing it" would reveal.
 *
 * **The page never infers provenance.** Every row of `GET
 * /api/settings/resolved` carries `layer` and `scope_id`, so a label derived
 * from a second walk over the same data would be a second answer that can
 * disagree with the first. Nothing in this module recomputes resolution; it
 * only names the vocabulary and answers questions *about* an answer the server
 * already gave.
 */

/** Resolution order, top to bottom. The first layer holding a value wins.
 *
 * `environment` and `default` are layers and not scopes: a value can come from
 * either and nothing can be written to either. `spec.ts`'s `SCOPES` is the
 * other three, and the two lists are deliberately separate rather than one
 * list with a flag — a form that offered to write to `default` would be
 * offering a request the API has no route for. */
export const RESOLUTION_ORDER = ['project', 'user', 'tenant', 'environment', 'default'] as const
export type Layer = (typeof RESOLUTION_ORDER)[number]

/** What the server says about a stored secret, in place of its value.
 *
 * There is no field here that could hold a credential, and that is the shape
 * doing the work rather than a rule somebody remembers: `value` is `null` for
 * every secret whether or not one is stored, and this object appears instead.
 * `lastFour` is `null` for a secret shorter than eight characters. */
export interface MaskedSecret {
  readonly present: boolean
  readonly lastFour: string | null
  /** The server's own words — `not set`, `set (…1234)`. Rendered verbatim
   *  rather than rebuilt from `present` and `lastFour`, so the console and the
   *  API cannot come to describe the same secret differently. */
  readonly display: string
}

export interface ResolvedSetting {
  readonly key: string
  /** Typed as the schema declares: a `boolean` setting arrives as `true`, an
   *  `integer` as a number. `null` for every secret. */
  readonly value: string | number | boolean | null
  readonly layer: Layer
  /** `null` unless a *scope* supplied the value — so it is null for
   *  `environment` and `default`, always. */
  readonly scopeId: string | null
  readonly secret: boolean
  readonly masked: MaskedSecret | null
}

export interface ScopeRef {
  readonly scope: Scope
  readonly scopeId: string
}

export interface ResolvedSettings {
  readonly scopeChain: readonly ScopeRef[]
  readonly settings: readonly ResolvedSetting[]
}

/** Did *this* scope set this value?
 *
 * The one question the row's whole treatment hangs off: the accent bar, the
 * `Clear` button and the fallback line all appear together exactly when this
 * is true. Both halves are compared, not just the layer — a project page
 * looking at a resolution that named a different project id would be reading
 * somebody else's override, which cannot happen through the UI but is a cheap
 * thing not to assume. */
export const isOverriddenAt = (resolved: ResolvedSetting, scope: Scope, scopeId: string): boolean =>
  resolved.layer === scope && resolved.scopeId === scopeId

/** The layers a page editing `scope` actually walks, starting at that scope.
 *
 * A tenant page names only a tenant in its requests, so its resolution can be
 * answered by `tenant`, `environment` or `default` and by nothing else --
 * `project` and `user` are not in the chain and are not consulted. A project
 * page walks all five.
 *
 * This is the whole of "the chain below is different", and it is a *value*
 * rather than a component per scope: one `slice` of `RESOLUTION_ORDER`, which
 * is why the three scopes stay one page. The alternative -- rendering all five
 * layers everywhere and greying the ones that did not answer -- says
 * "consulted and empty" about layers that were never consulted, which is a
 * different and false claim, and the one a reader of a tenant page would be
 * misled by. */
export const chainFrom = (scope: Scope): readonly Layer[] =>
  RESOLUTION_ORDER.slice(RESOLUTION_ORDER.indexOf(scope))

/** The layers that can still answer once this scope stops answering -- the
 *  tail of `chainFrom`. What a `Clear` on this page falls into. */
export const layersBelow = (scope: Scope): readonly Layer[] => chainFrom(scope).slice(1)

/** A resolution indexed by key, for the constant-time lookups the page does
 *  twice per row — once for the value and once for what it would fall back to. */
export const byKey = (resolved: ResolvedSettings): ReadonlyMap<string, ResolvedSetting> =>
  new Map(resolved.settings.map((setting) => [setting.key, setting]))

/** How a resolved value reads in a control, or in the fallback line.
 *
 * A secret never reaches here with a value to print — `value` is `null` by
 * contract — so its `masked.display` is what a caller shows instead, and that
 * decision is the caller's rather than buried in a formatter that would have
 * to be trusted not to leak. This function answers only for the non-secret
 * case and returns `''` for a missing value, which is what an empty input
 * holds. */
export const displayValue = (resolved: ResolvedSetting | undefined): string => {
  if (!resolved || resolved.value === null) return ''
  if (typeof resolved.value === 'boolean') return resolved.value ? 'on' : 'off'
  return String(resolved.value)
}
