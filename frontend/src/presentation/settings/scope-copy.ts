import type { Scope } from '@domain/settings/spec.ts'

/** What each scope's page calls itself.
 *
 * One record of three entries rather than three components. The design's whole
 * claim about this page is that a scope is a *value*, not a variant: the same
 * rows, the same controls, the same secret field, over a different chain. The
 * three things that genuinely differ are which settings render (`spec.scopes`,
 * already a filter), how deep the chain below is (derived from
 * `RESOLUTION_ORDER`), and these sentences.
 *
 * **Only `project` is reachable today.** `parseRoute` admits the other two so
 * S5 is a routing change rather than a second page, and the copy is written
 * now for the same reason the component is parametrised now — writing it later
 * is when the two pages start to diverge.
 *
 * The tenant blurb is not the project one with a word swapped, and that is the
 * point of writing all three: at tenant scope these values are the deployment
 * default that every project inherits, which is a different claim about what
 * pressing something here does.
 */
export const SCOPE_COPY: Record<Scope, { heading: string; blurb: string }> = {
  project: {
    heading: 'Project settings',
    blurb:
      'What this project uses. A value with no override here comes from the user, the tenant, the environment, or the built-in default — the chip on each row says which.',
  },
  user: {
    heading: 'Your settings',
    blurb:
      'What you use, in every project that does not override it. A value set here beats the tenant and the environment and loses to a project.',
  },
  tenant: {
    heading: 'Deployment settings',
    blurb:
      'The defaults every project and every person inherits, including the ones a project cannot set for itself. Only the environment and the built-in defaults sit below this.',
  },
}
