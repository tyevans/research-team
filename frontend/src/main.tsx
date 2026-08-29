import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'

import { App } from '@app/App.tsx'
import { ContainerProvider } from '@app/container-context.tsx'
import { createContainer } from '@app/container.ts'
import { notify } from '@application/notifications/toast-store.ts'
import { errorMessage } from '@application/ports/errors.ts'

import './styles/index.css'

/** The one place adapters, the query cache and React are wired together.
 *
 * Everything above this file takes its dependencies as arguments; this is where
 * the arguments are chosen. */
/** Reload, rather than navigate to a login route.
 *
 * There is no client-side login route: the sign-in decision is made from
 * `/api/auth/status` on the first render, so a full reload re-asks that
 * question and renders `LoginScreen` if the answer has changed. A client-side
 * redirect would need a second copy of that logic, and the two would disagree
 * the first time either moved.
 *
 * This fires when a session expires *while a tab is open*, which is the only
 * case the first render cannot cover. `HttpClient` latches it, so a page whose
 * ten in-flight requests all 401 together reloads once.
 *
 * `location.reload()` and not `location.assign('/')`: reloading keeps the
 * hash, so a person is returned to the page they were reading rather than to
 * the landing page -- and `/auth/login` carries `next` from there, so the
 * round trip through the identity provider ends where it started.
 */
const container = createContainer('', () => {
  window.location.reload()
})

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
