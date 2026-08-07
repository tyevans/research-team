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
const container = createContainer()

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
// swallowing it is how a page ends up looking merely slow.
window.addEventListener('unhandledrejection', (event) => {
  notify(`Unexpected error: ${errorMessage(event.reason)}`, 'bad')
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
