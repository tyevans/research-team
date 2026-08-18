/** `ActionUndone`, recorded off `useUnignoreMedia`'s `onSuccess` -- the
 *  nearest real "Undo" seam in this console (`IgnoredList.tsx`'s button is
 *  literally labelled that), not one of the eleven the brief names.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderHook, waitFor } from '@testing-library/react'
import type { ReactNode } from 'react'
import { describe, expect, it, vi } from 'vitest'

import type { Container as AppContainer } from '@app/container.ts'
import { ContainerProvider } from '@app/container-context.tsx'
import { InteractionLogContext } from '@app/interaction-log-provider.tsx'
import type { MediaProposalRepository } from '@application/ports/repositories.ts'
import { ProjectId } from '@domain/shared/identifier.ts'

import { useUnignoreMedia } from './use-media-proposals.ts'

const project = ProjectId('11111111-1111-4111-8111-111111111111')

const fakeMediaProposals = (over: Partial<MediaProposalRepository>): MediaProposalRepository =>
  ({ ...over }) as MediaProposalRepository

const wrapperFor = (
  mediaProposals: MediaProposalRepository,
  client: QueryClient,
  record: () => void,
) => {
  const container = { mediaProposals } as unknown as AppContainer
  return ({ children }: { children: ReactNode }) => (
    <ContainerProvider container={container}>
      <QueryClientProvider client={client}>
        <InteractionLogContext.Provider value={{ record } as never}>
          {children}
        </InteractionLogContext.Provider>
      </QueryClientProvider>
    </ContainerProvider>
  )
}

describe('useUnignoreMedia', () => {
  it('records ActionUndone naming the grain that was un-ignored', async () => {
    const record = vi.fn()
    const client = new QueryClient()
    const unignore = vi.fn().mockResolvedValue(undefined)
    const mediaProposals = fakeMediaProposals({ unignore })

    const { result } = renderHook(() => useUnignoreMedia(project), {
      wrapper: wrapperFor(mediaProposals, client, record),
    })
    result.current.mutate({ grain: 'host', key: 'example.com' })

    await waitFor(() => {
      expect(record).toHaveBeenCalledWith('ActionUndone', { action_kind: 'unignore-host' })
    })
  })

  /** The key never reaches the payload, and at `grain: 'asset'` the key is the
   *  asset URL -- content, in a kind not on `TEXT_BEARING_FIELDS`. Written as
   *  a substring search over every recorded payload rather than as an exact
   *  payload match, because the exact match above would still pass if the URL
   *  were reintroduced under a differently-named field.
   */
  it('puts no part of the asset URL into any payload', async () => {
    const record = vi.fn()
    const client = new QueryClient()
    const unignore = vi.fn().mockResolvedValue(undefined)
    const mediaProposals = fakeMediaProposals({ unignore })
    const url = 'https://example.com/secret-dossier/plate-7.jpg'

    const { result } = renderHook(() => useUnignoreMedia(project), {
      wrapper: wrapperFor(mediaProposals, client, record),
    })
    result.current.mutate({ grain: 'asset', key: url })

    await waitFor(() => {
      expect(record).toHaveBeenCalledWith('ActionUndone', { action_kind: 'unignore-asset' })
    })
    expect(JSON.stringify(record.mock.calls)).not.toContain('secret-dossier')
  })
})
