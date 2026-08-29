import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import type { Provider } from '@domain/settings/provider.ts'
import type { Profile, ResolvedRole } from '@domain/settings/role.ts'

import { RolesBlock } from './RolesBlock.tsx'
import { CanEditProvider } from './permissions.ts'

/** The roles block: what answers each role, and the two facts that must be
 *  visible because they are consequences of `ROLE_MODEL_KEYS`.
 */

const provider = (over: Partial<Provider> = {}): Provider => ({
  id: 'openai',
  displayName: 'OpenAI',
  baseUrl: 'https://api.openai.com/v1/',
  auth: 'bearer',
  openaiCompatible: true,
  capabilities: ['chat', 'embeddings', 'tools', 'vision'],
  credentials: [],
  notes: '',
  ...over,
})

const role = (over: Partial<ResolvedRole>): ResolvedRole => ({
  role: 'research',
  model: 'qwen',
  layer: 'default',
  scopeId: null,
  settingKey: 'model',
  profile: null,
  dangling: false,
  ...over,
})

const ROLES: ResolvedRole[] = [
  role({ role: 'research', settingKey: 'model' }),
  role({ role: 'extraction', settingKey: 'model' }),
  role({ role: 'curation', settingKey: 'curation_model' }),
  role({ role: 'embedding', settingKey: 'embedding_model' }),
  role({ role: 'vision', settingKey: 'vision_model' }),
]

const profile = (over: Partial<Profile> = {}): Profile => ({
  scope: 'project',
  scopeId: 'p1',
  name: 'cheap-local',
  providerId: 'ollama',
  model: 'qwen',
  credentialKey: null,
  baseUrl: null,
  parameters: {},
  ...over,
})

const draw = (
  props: Partial<Parameters<typeof RolesBlock>[0]> = {},
  canEdit: (key: string) => boolean = () => true,
) =>
  render(
    <CanEditProvider value={canEdit}>
      <RolesBlock
        roles={ROLES}
        profiles={[]}
        providers={[provider()]}
        onSelect={vi.fn()}
        onClear={vi.fn()}
        busy={false}
        {...props}
      />
    </CanEditProvider>,
  )

describe('roles that share a setting', () => {
  it('warns once at the top and again on each affected row', () => {
    draw()
    // Twice on purpose: somebody reading top to bottom should meet the fact
    // before they meet a control it applies to, and somebody who jumps
    // straight to the extraction row should still meet it.
    expect(screen.getByRole('note').textContent).toContain('research and extraction')
    expect(screen.getAllByText(/Shares/)).toHaveLength(2)
  })

  it('names what else moves, rather than saying "this is shared"', () => {
    draw()
    // "changing this changes that role too" is actionable; "shared" is not.
    // The user changed one thing and two things moved is the bug this prevents.
    expect(screen.getAllByText(/changing this changes/)).toHaveLength(2)
  })

  it('says nothing when the backend gives every role its own setting', () => {
    // The reason the pairing is derived rather than written down: a hardcoded
    // ['research','extraction'] would keep warning after a split, and the stale
    // warning would be indistinguishable from a real one.
    const split = ROLES.map((entry) =>
      entry.role === 'extraction' ? role({ ...entry, settingKey: 'extraction_model' }) : entry,
    )
    draw({ roles: split })
    expect(screen.queryByRole('note')).toBeNull()
    expect(screen.queryByText(/Shares/)).toBeNull()
  })
})

describe('what each row says about itself', () => {
  it('names the setting it resolves through, on every row', () => {
    draw()
    // The bridge that keeps profiles additive -- it is what lets somebody match
    // a role row to the `Models` group further down the page rather than
    // treating them as two competing truths.
    expect(screen.getAllByText(/resolves through/)).toHaveLength(5)
  })

  it('renders the five in pipeline order, not alphabetically', () => {
    draw()
    const labels = screen.getAllByText(/^(research|extraction|curation|embedding|vision)$/)
    expect(labels.map((node) => node.textContent)).toEqual([
      'research',
      'extraction',
      'curation',
      'embedding',
      'vision',
    ])
  })
})

describe('a selection nothing defines', () => {
  it('is reported, not silently fallen back from', () => {
    draw({
      roles: [role({ role: 'research', profile: 'deleted', dangling: true, model: 'fallback' })],
    })
    const alert = screen.getByRole('alert')
    // The person believes they are running a local model and are billing an
    // API, or the reverse, and nothing else on screen would disagree with them.
    expect(alert.textContent).toContain('deleted')
    expect(alert.textContent).toContain('not defined at any scope')
  })
})

describe('capability gating', () => {
  it('hides a profile whose provider cannot embed from the embedding role', async () => {
    const user = userEvent.setup()
    draw({
      profiles: [
        profile({ name: 'chat-only', providerId: 'chatty' }),
        profile({ name: 'embedder', providerId: 'openai' }),
      ],
      providers: [
        provider({ id: 'chatty', capabilities: ['chat'] }),
        provider({ id: 'openai', capabilities: ['chat', 'embeddings'] }),
      ],
    })

    const picker = screen.getByLabelText('Profile for the embedding role')
    const options = [...picker.querySelectorAll('option')].map((option) => option.textContent)
    expect(options.join(' ')).toContain('embedder')
    // Read as "is a provider worth offering for this role at all" rather than
    // as a promise about the model somebody picks -- the catalogue cannot know
    // whether a given model embeds.
    expect(options.join(' ')).not.toContain('chat-only')

    // And the chat roles still see both.
    const research = screen.getByLabelText('Profile for the research role')
    expect([...research.querySelectorAll('option')].map((o) => o.textContent).join(' ')).toContain(
      'chat-only',
    )
    void user
  })

  it('keeps a profile naming a provider this build has never heard of', () => {
    // Selectable today; hiding it would make a working selection
    // unexplainable, which is worse than showing one we cannot vouch for.
    draw({ profiles: [profile({ name: 'mystery', providerId: 'not-in-catalogue' })] })
    const picker = screen.getByLabelText('Profile for the research role')
    expect(picker.textContent).toContain('mystery')
  })
})

describe('a caller who may not change a role', () => {
  it('shows the selection and offers no control', () => {
    // The permissive-default trap: with `canEdit` unread this renders five
    // pickers, so the assertion moves the moment the seam stops being consulted.
    draw({ roles: [role({ profile: 'cheap-local' })] }, () => false)
    expect(screen.queryByLabelText('Profile for the research role')).toBeNull()
    expect(screen.queryByRole('combobox')).toBeNull()
    expect(screen.getByText('cheap-local')).toBeTruthy()
  })

  it('is asked about the setting the role writes, not about the role', () => {
    // A `canEdit` ignoring its argument passes the test above. This one
    // refuses one setting and permits the others, which is what a capability
    // actually does.
    draw({}, (key) => key !== 'model')
    expect(screen.queryByLabelText('Profile for the research role')).toBeNull()
    expect(screen.queryByLabelText('Profile for the extraction role')).toBeNull()
    expect(screen.getByLabelText('Profile for the curation role')).toBeTruthy()
  })
})
