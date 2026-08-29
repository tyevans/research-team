import { EmptyState } from '@presentation/common/primitives.tsx'

/** The whole console, when there is nobody signed in and there has to be.
 *
 * Rendered *instead of* the shell rather than over it, and that is the point:
 * every route behind this needs `/api/*`, and with the gate on every one of
 * those answers 401. A modal over a page of error boxes would be the same
 * information delivered twice, once uselessly.
 *
 * **No form.** There is no username field here and there must not be: Zitadel
 * hosts sign-in and registration, this project stores no passwords, and a
 * field that posted credentials anywhere in this application would be the one
 * thing the whole OIDC arrangement exists to avoid. Both controls are anchors
 * to `/auth/login`, because an OIDC authorization request is a *navigation* --
 * fetching it follows the redirect inside XHR, where no login form can be
 * shown.
 *
 * **Anchors wearing `.btn`**, which is the pattern `RunPanel` and
 * `WorkerDrawer` already use for a link into a session, rather than a class of
 * its own. No new rule is needed for a link, and a `<button>` with an
 * `onClick` that assigns `location.href` would be a control that middle-click
 * and "open in new tab" both silently ignore.
 */
export const LoginScreen = ({
  loginHref,
  signupHref,
  configured,
}: {
  loginHref: string
  signupHref: string
  /** Whether an identity provider is configured at all. `false` with auth
   *  required is a misconfigured instance, and saying so is the only useful
   *  thing this screen can do -- a sign-in button would navigate to a 503,
   *  which reads as the identity provider being down rather than absent. */
  configured: boolean
}) => (
  <div className="lay-shell" data-scroll="page">
    <main className="lay-surface" data-region="surface">
      <div className="max-w-md mx-auto flex min-h-[70vh] flex-col justify-center gap-6 px-6">
        <div className="flex items-center gap-2">
          <span className="brand-mark" />
          <span className="brand-name">research&#8209;team</span>
        </div>

        {configured ? (
          <>
            <p className="text-sm text-fg-dim">
              This instance requires a sign-in. Accounts live in the identity provider, not here.
            </p>
            {/* `<a>`, not `<Button>`: `Button` renders a `<button>`, and this
                has to be a link for the reasons above. `.btn` gives it the
                same shape. */}
            <div className="flex flex-col gap-3">
              <a className="btn btn-accent" href={loginHref}>
                Sign in
              </a>
              <a className="btn btn-quiet" href={signupHref}>
                Create an account
              </a>
            </div>
          </>
        ) : (
          <EmptyState
            heading="No identity provider is configured"
            detail={
              <>
                This build requires a sign-in but has no issuer to sign in against. Set{' '}
                <code>AGENT_OIDC_CLIENT_ID</code> and <code>AGENT_OIDC_ISSUER</code>, or set{' '}
                <code>AGENT_AUTH=off</code>. See <code>docs/how-to/running-zitadel-locally.md</code>
                .
              </>
            }
          />
        )}
      </div>
    </main>
  </div>
)
