import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { Meta, StoryObj } from '@storybook/react-vite'
import { useState, type ReactNode } from 'react'

import type { Container } from '@app/container.ts'
import { ContainerProvider } from '@app/container-context.tsx'
import type { AutonomyPolicyView } from '@domain/autonomy/autonomy.ts'
import { SessionId } from '@domain/shared/identifier.ts'

import { AutonomyLock } from './AutonomyLock.tsx'
import { AutonomyPanel } from './AutonomyPanel.tsx'

/** The instance-wide policy, and the lock that opens it.
 *
 * Three claims here are prose in the components and had no picture:
 *
 * - **The scope warning must be the loudest line.** A person flipping a switch
 *   that looks local while changing every session on the instance is the
 *   specific failure the panel is shaped around, and whether the warning wins
 *   against eight rows of controls is a thing only an eye settles.
 * - **A tool the server gated and gave no level to says so**, rather than
 *   showing "ask" and inventing a safety claim nobody made. `Unlevelled` is
 *   that row beside ordinary ones, which is the only way to see that it reads
 *   as different.
 * - **The lock is a glyph**, and a glyph in a bar of words is exactly where an
 *   unlabelled icon stops being identifiable. `Lock` is it in place next to
 *   the same button dressing the chrome's other controls use.
 *
 * The container is faked rather than built: the panel reads one policy through
 * one query, and building a real container would be building the application
 * to draw eight radios. Each story owns its own `QueryClient` so a write in one
 * cannot be read by another.
 */
const meta: Meta = {
  title: 'shell/Autonomy',
  parameters: { layout: 'padded' },
}

export default meta

type Story = StoryObj

const SESSION = SessionId('22222222-2222-2222-2222-222222222222')

const policy = (
  levels: Record<string, string>,
  gated = Object.keys(levels),
): AutonomyPolicyView => ({
  levels: new Map(Object.entries(levels)),
  gated,
})

/** Holds the policy it is given and accepts writes against it, so the radios
 *  in a story actually move. A repository that answered the starting policy
 *  forever would undo every click one refetch later. */
const holder = (start: AutonomyPolicyView): Container => {
  let current = start
  return {
    autonomy: {
      read: () => Promise.resolve(current),
      setLevel: (_id: SessionId, tool: string, level: string) => {
        current = { ...current, levels: new Map(current.levels).set(tool, level) }
        return Promise.resolve(current)
      },
      allowAll: () => Promise.resolve({ changed: new Map(), policy: current }),
    },
  } as unknown as Container
}

const Frame = ({ start, children }: { start: AutonomyPolicyView; children: ReactNode }) => {
  // A lazy initialiser rather than a value built during render: the container
  // holds the policy the radios write to, and rebuilding it on a re-render
  // would drop every click. It is also the only way to keep the mutation out
  // of render, which `react-hooks/immutability` rightly refuses.
  const [container] = useState(() => holder(start))
  const [client] = useState(
    () => new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } }),
  )

  return (
    <QueryClientProvider client={client}>
      <ContainerProvider container={container}>{children}</ContainerProvider>
    </QueryClientProvider>
  )
}

export const Panel: Story = {
  render: () => (
    <Frame start={policy({ fetch: 'ask', run_command: 'ask', write_file: 'auto', web: 'deny' })}>
      <AutonomyPanel sessionId={SESSION} />
    </Frame>
  ),
}

/** No session to record a write against, which is every route but a project's.
 *  The controls are disabled and the reason is said — a disabled lock would
 *  have been the alternative, and it explains nothing. */
export const ReadOnly: Story = {
  render: () => (
    <Frame start={policy({ fetch: 'ask', run_command: 'auto' })}>
      <AutonomyPanel sessionId={null} />
    </Frame>
  ),
}

/** The server named a tool as gated and gave it no level. */
export const Unlevelled: Story = {
  render: () => (
    <Frame start={policy({ fetch: 'ask' }, ['fetch', 'zip_files'])}>
      <AutonomyPanel sessionId={SESSION} />
    </Frame>
  ),
}

/** The lock as the chrome wears it, beside the button dressing it shares with
 *  the log link. Click it: the dialog is the panel above, in a `Drawer`. */
export const Lock: Story = {
  render: () => (
    <Frame start={policy({ fetch: 'ask', run_command: 'auto' })}>
      <div className="flex items-center gap-2">
        <a className="btn btn-ghost btn-sm" href="#/i">
          log
        </a>
        <AutonomyLock route={{ name: 'home' }} />
      </div>
    </Frame>
  ),
}
