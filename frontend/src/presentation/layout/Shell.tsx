import type { ReactNode } from 'react'

import { OverlayHost } from './OverlayHost.tsx'

/** The three regions of a page, and the only component allowed to render them.
 *
 * A role here is a claim about **scope**, not about position, which is what
 * makes it decidable at review time:
 *
 * - **`chrome`** — present on every route, holding what is not a property of
 *   the page you happen to be on. `App.tsx` already states exactly this test,
 *   for the agent dock: "'what is running' is not a property of the page you
 *   happen to be on -- which is the whole reason it exists". The same test
 *   admits the connection badge, the drift badge and the breadcrumb, and
 *   excludes everything else, which is the useful half of the rule.
 * - **`surface`** — the route's content. It owns the viewport and does not
 *   scroll; its regions scroll individually. This is already the console's
 *   contract, and `research.css` records what it buys: "inside a scrolling
 *   page every pane needs a fixed pixel height, and fixed heights are what
 *   made this page a stack of small boxes with the largest artifact in the
 *   smallest one."
 * - **`overlay`** — one host, always mounted, described in `OverlayHost.tsx`.
 *
 * `Shell` knows nothing about overlays beyond mounting the host, and that is
 * deliberate: making a modal disable the page is the *host's* job, done to
 * whatever it wraps, so the guarantee holds for any tree rather than only for
 * a `Shell`. `OverlayHost.tsx` argues that choice where it is made.
 *
 * The surface's no-scroll contract is currently suspended below 820px by
 * `responsive.css` setting `body { overflow: auto }` — a global overridden by
 * a media query, so nothing reading `Shell` would know it happens. Here it is
 * a declared mode: `scroll` says which of the two contracts this shell is
 * under, and the stylesheet switches on the attribute rather than on the
 * element. `auto` picks by breakpoint, which is today's behaviour with a name.
 */
export const Shell = ({
  chrome,
  children,
  scroll = 'auto',
}: {
  /** Rendered above the surface, on every route.
   *
   *  A slot rather than `children` with a convention, so that a shell missing
   *  its chrome is a call site you can see rather than a page that silently
   *  renders without a breadcrumb. */
  chrome?: ReactNode
  children: ReactNode
  /** `viewport` — the surface fills the screen and never scrolls; its regions
   *  scroll. `page` — the surface is one scrolling column, which is the only
   *  thing that works when there is not room for regions side by side.
   *  `auto` — `page` below `--bp-narrow`, `viewport` above. */
  scroll?: 'viewport' | 'page' | 'auto'
}) => (
  <OverlayHost>
    <div className="lay-shell" data-scroll={scroll}>
      {chrome === undefined ? null : (
        <header className="lay-chrome" data-region="chrome">
          {chrome}
        </header>
      )}
      {/* `main`, and exactly one per page: the surface is the route's content
          by definition, so it is the document's main landmark by definition
          too. Nothing else in the shell may be one. */}
      <main className="lay-surface" data-region="surface">
        {children}
      </main>
    </div>
  </OverlayHost>
)
