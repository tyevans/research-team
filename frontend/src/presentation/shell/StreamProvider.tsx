import {
  createContext,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from 'react'

import type { ConnectionState, FeedFrame } from '@application/ports/event-stream.ts'
import { useContainer } from '@app/container-context.tsx'

type FrameListener = (frame: FeedFrame) => void
type ReconnectListener = (resumable: boolean) => void

interface StreamApi {
  readonly connection: ConnectionState
  onFrame(listener: FrameListener): () => void
  onReconnect(listener: ReconnectListener): () => void
}

const StreamContext = createContext<StreamApi | null>(null)

/** One connection for the whole application, fanned out to whoever is
 *  listening.
 *
 * One rather than one per view because the feed is global: a frame for another
 * session still matters to the tree, and opening a second `EventSource` per
 * route would double the server's fan-out for no gain. Views subscribe and
 * filter, which is what they were doing anyway.
 */
export const StreamProvider = ({ children }: { children: ReactNode }) => {
  const { stream } = useContainer()
  const [connection, setConnection] = useState<ConnectionState>('connecting')
  const frameListeners = useRef(new Set<FrameListener>())
  const reconnectListeners = useRef(new Set<ReconnectListener>())

  useEffect(() => {
    stream.connect({
      onFrame: (frame) => {
        for (const listener of frameListeners.current) listener(frame)
      },
      onConnectionState: setConnection,
      onReconnect: (resumable) => {
        for (const listener of reconnectListeners.current) listener(resumable)
      },
    })
    return () => stream.disconnect()
  }, [stream])

  const api = useMemo<StreamApi>(
    () => ({
      connection,
      onFrame(listener) {
        frameListeners.current.add(listener)
        return () => frameListeners.current.delete(listener)
      },
      onReconnect(listener) {
        reconnectListeners.current.add(listener)
        return () => reconnectListeners.current.delete(listener)
      },
    }),
    [connection],
  )

  return <StreamContext.Provider value={api}>{children}</StreamContext.Provider>
}

export const useStream = (): StreamApi => {
  const api = useContext(StreamContext)
  if (!api) throw new Error('useStream must be used inside a <StreamProvider>')
  return api
}
