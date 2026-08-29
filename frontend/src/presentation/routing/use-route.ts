import { useHashLocation } from 'wouter/use-hash-location'

import { parseDeck, parseRoute, parseSeekSeconds, type Route } from './routes.ts'

/** The current route, and how to change it.
 *
 * The browser plumbing — subscribing to `hashchange`, reading the hash without
 * tearing, pushing versus replacing — is `wouter`'s, because it is fiddly,
 * standard, and not this project's problem. What stays here is the part that
 * *is* this project's: turning a hash into one of three typed routes, which
 * `parseRoute` does and which no router could do for us.
 */
export const useRoute = (): Route => {
  const [path] = useHashLocation()
  return parseRoute(path)
}

/** The `?t=` seek off the current hash, or `null` -- a citation's own moment,
 *  read independently of `useRoute` rather than folded into `Route` itself:
 *  every facet but `doc` has no player to seek, and widening the union for
 *  one facet's query parameter would make every other route's reader guard
 *  against a field that can never apply to it. See `parseSeekSeconds`'s own
 *  docstring for what counts as well-formed. */
export const useSeekSeconds = (): number | null => {
  const [path] = useHashLocation()
  return parseSeekSeconds(path)
}

/** The deck open on the current hash, or `null`.
 *
 * Read off the hash rather than held in component state, which is the whole
 * point: a slide is a linkable thing, so the reader's position is in the URL
 * and a reload or a shared link lands on the same slide. See `parseDeck`.
 *
 * The full hash comes back with it, because both closing the deck and moving
 * between slides mean rewriting *this* hash rather than rebuilding one from a
 * route -- see `withDeck`, and see `parseRoute`'s note that a route printed
 * from its parts would drop any other query it carried. */
export const useDeck = (): {
  deck: { path: string; slide: number } | null
  hash: string
} => {
  const [path] = useHashLocation()
  return { deck: parseDeck(path), hash: path }
}

/** Navigation as a plain function, for the handlers that are not components.
 *
 * `replace` is what scrubbing uses: dragging through forty events should not
 * leave forty entries in the back stack, but the position must still be in the
 * URL, because a scrubbed view is a linkable thing. */
export const navigate = (href: string, options: { replace?: boolean } = {}): void => {
  const target = href.startsWith('#') ? href.slice(1) : href
  if (options.replace) {
    window.history.replaceState(null, '', `#${target}`)
    window.dispatchEvent(new HashChangeEvent('hashchange'))
    return
  }
  if (window.location.hash === `#${target}`) {
    // Same hash: the browser fires nothing, but the caller asked to go there,
    // and a retry of a failed load is exactly that request.
    window.dispatchEvent(new HashChangeEvent('hashchange'))
    return
  }
  window.location.hash = target
}
