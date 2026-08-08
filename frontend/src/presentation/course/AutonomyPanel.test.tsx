import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { ReactElement, ReactNode } from 'react'
import { expect, it, vi } from 'vitest'

import type { Container as AppContainer } from '@app/container.ts'
import { ContainerProvider } from '@app/container-context.tsx'
import { ApiError } from '@application/ports/errors.ts'
import type { AutonomyRepository } from '@application/ports/repositories.ts'
import type { AutonomyPolicyView } from '@domain/autonomy/autonomy.ts'
import { SessionId } from '@domain/shared/identifier.ts'

import { AutonomyAllowAll } from './AutonomyAllowAll.tsx'
import { AutonomyPanel } from './AutonomyPanel.tsx'

const SESSION = SessionId('22222222-2222-2222-2222-222222222222')

/** A policy whose tool list is *not* this build's idea of one.
 *
 * `zip_files` is invented. If any assertion below depended on the real
 * `GATED_TOOLS`, this fixture would fail it — which is the point: the panel
 * must render whatever `gated` says, so a tool gated on the server tomorrow
 * gets a switch without a frontend change.
 */
const policyWith = (levels: Record<string, string>): AutonomyPolicyView => ({
  levels: new Map(Object.entries(levels)),
  gated: Object.keys(levels),
  stageGates: ['advance_stage'],
})

const BASE = policyWith({ zip_files: 'ask', fetch: 'ask', advance_stage: 'ask' })

/** Same harness as `Workers.test.tsx`: a fake container behind the providers
 *  the real app wraps every view in. The `QueryClient` is returned so a test
 *  can share one across two renders and prove the two surfaces read one cache
 *  entry rather than two. */
const renderWith = (ui: ReactElement, parts: Partial<AppContainer>, shared?: QueryClient) => {
  const container = parts as unknown as AppContainer
  const client =
    shared ?? new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } })
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>
      <ContainerProvider container={container}>{children}</ContainerProvider>
    </QueryClientProvider>
  )
  return { ...render(ui, { wrapper }), client }
}

/** A repository that remembers, because the hook invalidates after every write.
 *
 * `useAutonomy` seeds the cache with a write's response *and* invalidates it,
 * which is deliberate — another tab may have moved something between this
 * view's last read and this write. A fake whose `read` always answered the
 * starting policy would therefore undo every write one refetch later, and the
 * tests would be asserting against a server that contradicts itself. Holding
 * one mutable policy is both simpler and closer to the real thing.
 *
 * The spies are returned beside `repo` rather than read back off it, so an
 * assertion never has to reference a port method as a value — `unbound-method`
 * rightly objects to that, since a method plucked off an interface-typed object
 * has lost its receiver.
 */
const fakeAutonomy = (start: AutonomyPolicyView = BASE, over: Partial<AutonomyRepository> = {}) => {
  let current = start

  const read = vi
    .fn<AutonomyRepository['read']>()
    .mockImplementation(() => Promise.resolve(current))

  const setLevel = vi
    .fn<AutonomyRepository['setLevel']>()
    .mockImplementation((_id, tool, level) => {
      current = { ...current, levels: new Map(current.levels).set(tool, level) }
      return Promise.resolve(current)
    })

  const allowAll = vi
    .fn<AutonomyRepository['allowAll']>()
    .mockImplementation((_id, includeGates) => {
      const changed = new Map<string, string>()
      for (const tool of current.gated) {
        if (!includeGates && current.stageGates.includes(tool)) continue
        if (current.levels.get(tool) !== 'auto') changed.set(tool, 'auto')
      }
      const levels = new Map(current.levels)
      for (const tool of changed.keys()) levels.set(tool, 'auto')
      current = { ...current, levels }
      return Promise.resolve({ changed, policy: current })
    })

  const repo: AutonomyRepository = { read, setLevel, allowAll, ...over }
  return { repo, read, setLevel, allowAll }
}

it('renders one control per tool the server listed, not per tool this build knows', async () => {
  const autonomy = fakeAutonomy()
  renderWith(<AutonomyPanel sessionId={SESSION} />, { autonomy: autonomy.repo })

  // `zip_files` exists nowhere in this frontend. A hardcoded list would miss it.
  expect(await screen.findByText('zip_files')).toBeInTheDocument()
  expect(screen.getByText('fetch')).toBeInTheDocument()
  expect(screen.getByText('advance_stage')).toBeInTheDocument()
  expect(screen.getAllByRole('radio', { name: 'auto' })).toHaveLength(3)
})

it('sends the tool and level to the session-scoped route and shows what came back', async () => {
  const autonomy = fakeAutonomy()
  renderWith(<AutonomyPanel sessionId={SESSION} />, { autonomy: autonomy.repo })

  const group = (await screen.findByText('zip_files')).closest('fieldset')
  const auto = [...(group?.querySelectorAll<HTMLInputElement>('input[type=radio]') ?? [])].find(
    (input) => input.value === 'auto',
  )
  await userEvent.click(auto!)

  expect(autonomy.setLevel).toHaveBeenCalledWith(SESSION, 'zip_files', 'auto')
  // Reflected from the response, not from optimistic local state: the server is
  // the authority, and another tab may have moved something else meanwhile.
  await waitFor(() => expect(auto!.checked).toBe(true))
})

it('renders the server’s own rejection message verbatim', async () => {
  const setLevel = vi
    .fn<AutonomyRepository['setLevel']>()
    .mockRejectedValue(new ApiError("unknown autonomy level: 'sometimes'", 400))
  renderWith(<AutonomyPanel sessionId={SESSION} />, {
    autonomy: fakeAutonomy(BASE, { setLevel }).repo,
  })

  const group = (await screen.findByText('fetch')).closest('fieldset')
  const deny = [...(group?.querySelectorAll<HTMLInputElement>('input[type=radio]') ?? [])].find(
    (input) => input.value === 'deny',
  )
  await userEvent.click(deny!)

  // Verbatim, because only the server's text names the offending value.
  expect(await screen.findByRole('alert')).toHaveTextContent("unknown autonomy level: 'sometimes'")
})

it('says the build has no policy rather than showing an empty set of switches', async () => {
  const read = vi
    .fn<AutonomyRepository['read']>()
    .mockRejectedValue(new ApiError('the autonomy policy is not wired up', 404))
  renderWith(<AutonomyPanel sessionId={SESSION} />, { autonomy: fakeAutonomy(BASE, { read }).repo })

  expect(await screen.findByText(/does not expose an autonomy policy/i)).toBeInTheDocument()
  expect(screen.queryByRole('radio')).not.toBeInTheDocument()
})

it('renders read-only with a reason when no session can carry the audit record', async () => {
  const setLevel = vi.fn<AutonomyRepository['setLevel']>()
  renderWith(<AutonomyPanel sessionId={null} />, {
    autonomy: fakeAutonomy(BASE, { setLevel }).repo,
  })

  expect(await screen.findByText(/nothing to record a change against/i)).toBeInTheDocument()
  expect(screen.getAllByRole('radio', { name: 'auto' })[0]).toBeDisabled()
  expect(setLevel).not.toHaveBeenCalled()
})

it('warns on both surfaces that the policy is instance-wide', async () => {
  // Both, and in the same words — see `autonomy-copy.ts`. Two controls over
  // one instance-wide policy that describe its scope differently teach the
  // reader that one of them is lying, and they cannot tell which.
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } })
  const autonomy = fakeAutonomy()

  renderWith(<AutonomyPanel sessionId={SESSION} />, { autonomy: autonomy.repo }, client)
  renderWith(<AutonomyAllowAll sessionId={SESSION} />, { autonomy: autonomy.repo }, client)

  await waitFor(() =>
    expect(screen.getAllByText(/every session on this instance/i)).toHaveLength(2),
  )
})

it('leaves the review gate asking after allow-all, and says that is deliberate', async () => {
  // The load-bearing case for the drawer control. `advance_stage` stays at
  // `ask` by design, so the UI must explain it rather than look half-broken.
  const autonomy = fakeAutonomy()
  renderWith(<AutonomyAllowAll sessionId={SESSION} />, { autonomy: autonomy.repo })

  await userEvent.click(
    await screen.findByRole('button', { name: /allow everything except the review gate/i }),
  )

  expect(autonomy.allowAll).toHaveBeenCalledWith(SESSION, false)
  // Reports `changed` (two), not the whole map (three) — otherwise the UI
  // claims changes nobody made.
  const result = await screen.findByRole('status')
  expect(result).toHaveTextContent('Changed 2 tool(s)')
  expect(result).toHaveTextContent('advance_stage')
  expect(result).toHaveTextContent(/workflow review gate/i)
})

it('autos the review gate only through the separate control', async () => {
  const autonomy = fakeAutonomy(policyWith({ fetch: 'auto', advance_stage: 'ask' }))
  renderWith(<AutonomyAllowAll sessionId={SESSION} />, { autonomy: autonomy.repo })

  await userEvent.click(await screen.findByRole('button', { name: /also allow the review gate/i }))

  expect(autonomy.allowAll).toHaveBeenCalledWith(SESSION, true)
  const result = await screen.findByRole('status')
  await waitFor(() => expect(result).toHaveTextContent('Changed 1 tool(s): advance_stage'))
  // Nothing is held back any more, so the exclusion sentence must not appear —
  // it would be describing a state that no longer exists. Asserted on the
  // result line rather than the document, because the second button's own
  // tooltip legitimately names the review gate.
  expect(result).not.toHaveTextContent(/left asking on purpose/i)
})

it('shows the same state on both surfaces after a write', async () => {
  // The consistency guarantee. Both go through one query key, so the drawer's
  // allow-all is visible in the course panel without the panel refetching on
  // its own — a second key would leave the panel showing pre-write levels.
  const autonomy = fakeAutonomy(policyWith({ fetch: 'ask', advance_stage: 'ask' }))
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } })

  renderWith(<AutonomyPanel sessionId={SESSION} />, { autonomy: autonomy.repo }, client)
  const { unmount } = renderWith(
    <AutonomyAllowAll sessionId={SESSION} />,
    { autonomy: autonomy.repo },
    client,
  )

  const fetchRadios = () => {
    const group = screen.getByText('fetch').closest('fieldset')
    return [...(group?.querySelectorAll<HTMLInputElement>('input[type=radio]') ?? [])]
  }
  await waitFor(() => expect(fetchRadios()).not.toHaveLength(0))
  expect(fetchRadios().find((input) => input.value === 'ask')?.checked).toBe(true)

  await userEvent.click(
    screen.getByRole('button', { name: /allow everything except the review gate/i }),
  )

  // The panel, which issued no request of its own, now shows `fetch` as auto.
  await waitFor(() =>
    expect(fetchRadios().find((input) => input.value === 'auto')?.checked).toBe(true),
  )
  unmount()
})

it('offers a level the server reported that this build does not know', async () => {
  // Otherwise selecting an unfamiliar level would be one-way: the current
  // setting would show as nothing selected, with no radio to return to.
  const autonomy = fakeAutonomy(policyWith({ fetch: 'sometimes', advance_stage: 'ask' }))
  renderWith(<AutonomyPanel sessionId={SESSION} />, { autonomy: autonomy.repo })

  expect(await screen.findByRole('radio', { name: 'sometimes' })).toBeChecked()
  expect(screen.getByText(/unfamiliar level/i)).toBeInTheDocument()
})

it('starts closed, and says how the gated tools are set without being opened', async () => {
  const autonomy = fakeAutonomy(policyWith({ fetch: 'ask', advance_stage: 'ask', run: 'auto' }))
  renderWith(<AutonomyPanel sessionId={SESSION} />, { autonomy: autonomy.repo })

  expect(await screen.findByText('2 ask')).toBeInTheDocument()
  expect(screen.getByText('1 auto')).toBeInTheDocument()

  // Closed by default: this policy is instance-wide and rarely touched, and
  // open it pushed the course itself below the fold.
  const disclosure = document.querySelector('details.autonomy-disclosure')
  expect(disclosure).not.toBeNull()
  expect((disclosure as HTMLDetailsElement).open).toBe(false)
})

it('opens onto the controls when its summary is activated', async () => {
  const autonomy = fakeAutonomy(policyWith({ fetch: 'ask' }))
  renderWith(<AutonomyPanel sessionId={SESSION} />, { autonomy: autonomy.repo })

  await screen.findByText('1 ask')
  const disclosure = document.querySelector('details.autonomy-disclosure') as HTMLDetailsElement
  await userEvent.click(screen.getByText(/what the agent may do without asking/i))

  expect(disclosure.open).toBe(true)
})
