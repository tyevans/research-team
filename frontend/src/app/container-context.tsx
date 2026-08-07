import { createContext, useContext, type ReactNode } from 'react'

import type { Container } from './container.ts'

/** The container, reachable from any component without being imported by one.
 *
 * Components ask for the port they need (`useContainer().projects`) rather than
 * importing an adapter, which is what keeps every one of them renderable in a
 * test against fakes. */
const ContainerContext = createContext<Container | null>(null)

export const ContainerProvider = ({
  container,
  children,
}: {
  container: Container
  children: ReactNode
}) => <ContainerContext.Provider value={container}>{children}</ContainerContext.Provider>

export const useContainer = (): Container => {
  const container = useContext(ContainerContext)
  if (!container) {
    throw new Error('useContainer must be used inside a <ContainerProvider>')
  }
  return container
}
