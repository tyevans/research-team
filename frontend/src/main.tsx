import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'

import { App } from '@app/App.tsx'
import { ContainerProvider } from '@app/container-context.tsx'
import { createContainer } from '@app/container.ts'
import { notify } from '@application/notifications/toast-store.ts'
import { errorMessage } from '@application/ports/errors.ts'
import { queryKeys } from '@application/queries/keys.ts'

import './styles/index.css'

/** The one place adapters, the query cache and React are wired together.
 *
 * Everything above this file takes its dependencies as arguments; this is where
 * the arguments are chosen. */
const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      // The live feed is what keeps this console current, not polling — a
      // refetch on every window focus would issue a burst of requests for data
      // a frame is about to deliver anyway.
      refetchOnWindowFocus: false,
      staleTime: 5_000,
      retry: 1,
    },
  },
})

/** Re-ask "is anybody signed in", in place. Do not navigate.
 *
 * **This reloaded the page, and that shipped an infinite reload loop.**
 * Measured on 2026-08-29 by pointing a browser at a live Zitadel with
 * `AGENT_AUTH=on`: **816 page loads and 6295 401s**, and the login screen
 * never rendered once.
 *
 * The mechanism is worth writing down, because every gate was green through
 * it. `Authenticated` deliberately renders the console while the status query
 * is in flight — a blank screen on every load of every instance with auth off
 * is not worth paying — so a signed-out first render fires the console's
 * ordinary requests (`/api/sessions`, `/api/tree`, `/api/stream`) and every
 * one of them 401s *before* `/api/auth/status` has answered. The reload then
 * threw away the in-flight status query and started the same race again,
 * forever.
 *
 * The comment that stood here reasoned that a reload "re-asks that question
 * and renders `LoginScreen` if the answer has changed". The answer never
 * changes; it never arrives. That is the same loop `auth.py` refuses for the
 * callback — "a misconfiguration becomes an infinite loop between two
 * endpoints that each think the other is at fault" — rebuilt one layer up, by
 * the same person, in the same change.
 *
 * Invalidating has no navigation in it, so there is no race to lose: the
 * status query refetches, `Authenticated` re-renders, and the wall appears. It
 * is also strictly better for the case the reload was written for — a session
 * expiring while a tab is open now keeps its route and its scroll rather than
 * reloading underneath the reader.
 *
 * `currentUser` goes with it because the account menu is the other thing a 401
 * makes stale: leaving it cached would show a signed-in person's name in the
 * chrome of a console that has just put up a sign-in wall.
 *
 * Nothing here is a *security* control — the server is what refuses the
 * request. This only decides what the reader is shown afterwards, which is why
 * it is safe for it to be best-effort and debounced.
 */
const container = createContainer('', () => {
  void queryClient.invalidateQueries({ queryKey: queryKeys.authStatus() })
  void queryClient.invalidateQueries({ queryKey: queryKeys.currentUser() })
})

// A failure nobody handled is still worth telling somebody about; silently
// swallowing it is how a page ends up looking merely slow. Both channels,
// because a render that throws and a promise that rejects are equally invisible
// to a reader watching a pane that simply stopped updating.
window.addEventListener('unhandledrejection', (event) => {
  notify(`Unexpected error: ${errorMessage(event.reason)}`, 'bad')
})
window.addEventListener('error', (event) => {
  if (event.message) notify(`UI error: ${event.message}`, 'bad')
})

const root = document.getElementById('root')
if (!root) throw new Error('index.html is missing its #root element')

createRoot(root).render(
  <StrictMode>
    <ContainerProvider container={container}>
      <QueryClientProvider client={queryClient}>
        <App />
      </QueryClientProvider>
    </ContainerProvider>
  </StrictMode>,
)
