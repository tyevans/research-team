import { z } from 'zod'

import type { AuthRepository, AuthStatus, Principal } from '@application/ports/repositories.ts'

import type { HttpClient } from './http-client.ts'

/** `/api/auth/status`, which a signed-out browser is allowed to ask.
 *
 * The one endpoint in this console that is deliberately outside the server's
 * auth gate. Everything else answers 401 without a session, which is the right
 * answer to "give me the data" and the wrong answer to "should I be showing a
 * login screen" — a console that had to receive a 401 before it could ask the
 * question would render the app, fail every request, and then redirect.
 */
const statusSchema = z.object({
  auth_required: z.boolean(),
  authenticated: z.boolean(),
  /** Whether an identity provider is configured at all. Distinct from
   *  `auth_required`: a build with `AGENT_AUTH=off` and a working Zitadel can
   *  still sign you in, and a build with auth required and no issuer is a
   *  misconfiguration the login screen has to be able to name rather than
   *  offering a button that 503s. */
  configured: z.boolean(),
  subject: z.string().nullable(),
})

const meSchema = z.object({
  subject: z.string(),
  tenant_id: z.string(),
  email: z.string(),
  display_name: z.string(),
  avatar_url: z.string(),
  first_seen_at: z.string(),
  last_seen_at: z.string(),
  /** Whether the read model had a row, or the server fell back to the
   *  cookie's own fields. Carried rather than hidden because the fallback is
   *  the honest answer during the window between a sign-in's append and the
   *  projection catching up — and because a `mirrored: false` that persists is
   *  a projection that is not running, which is exactly the silent failure
   *  CLAUDE.md's Events section is about. */
  mirrored: z.boolean(),
})

export class HttpAuthRepository implements AuthRepository {
  constructor(private readonly http: HttpClient) {}

  async status(): Promise<AuthStatus> {
    const body = await this.http.get('/api/auth/status', statusSchema)
    return {
      authRequired: body.auth_required,
      authenticated: body.authenticated,
      configured: body.configured,
    }
  }

  async me(): Promise<Principal> {
    const body = await this.http.get('/api/me', meSchema)
    return {
      subject: body.subject,
      tenantId: body.tenant_id,
      email: body.email,
      displayName: body.display_name,
      avatarUrl: body.avatar_url,
      firstSeenAt: body.first_seen_at,
      lastSeenAt: body.last_seen_at,
      mirrored: body.mirrored,
    }
  }

  /** Where to send the browser to sign in.
   *
   * A URL rather than a `fetch`, and that is not a shortcut: the OIDC
   * authorization request is a *navigation*. Fetching `/auth/login` would
   * follow the redirect to the identity provider inside XHR, where the login
   * form cannot be shown and where the cookie the callback sets belongs to a
   * request nobody sees.
   *
   * `next` carries the current location so a person lands back where they
   * were. The server discards anything that is not a same-origin path — see
   * `_safe_next` — so this cannot become an open redirect however it is
   * called.
   */
  loginHref(next: string, options: { signup?: boolean } = {}): string {
    const params = new URLSearchParams({ next })
    if (options.signup) params.set('signup', 'true')
    return this.http.url(`/auth/login?${params.toString()}`)
  }

  logoutHref(): string {
    return this.http.url('/auth/logout')
  }
}
