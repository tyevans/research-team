import { canServe, type Provider } from '@domain/settings/provider.ts'
import { sharing, type Profile, type ResolvedRole, type Role } from '@domain/settings/role.ts'

import { Button } from '../common/primitives.tsx'
import { useCanEdit } from './permissions.ts'

/** One role, and the profile answering it.
 *
 * **Two things must be visible here, and both are consequences of
 * `ROLE_MODEL_KEYS` rather than decisions of this component.**
 *
 * First, the row says **which setting it writes**, in mono. That is the bridge
 * that keeps profiles additive: it is what makes the roles block and the
 * `Models` group further down the page obviously the same data rather than two
 * competing truths about which model runs.
 *
 * Second, when another role resolves from the same setting, the row says so
 * *and names it*. `research` and `extraction` share `model` today, so choosing
 * a cheap local model for extraction silently repoints the research agent —
 * the worst kind of settings bug, where the user changed one thing and two
 * things moved. The sharing is derived from the resolved roles rather than
 * written down here, so a backend that splits them stops this warning without
 * anybody remembering to.
 */
export const RoleRow = ({
  resolved,
  roles,
  profiles,
  providers,
  onSelect,
  onClear,
  busy,
}: {
  resolved: ResolvedRole
  /** All five, so `sharing` can find the ones on the same setting. */
  roles: readonly ResolvedRole[]
  profiles: readonly Profile[]
  providers: readonly Provider[]
  onSelect: (role: Role, profile: string) => void
  onClear: (role: Role) => void
  busy: boolean
}) => {
  const canEdit = useCanEdit()
  const editable = canEdit(resolved.settingKey)
  const shared = sharing(roles, resolved.role)

  const byId = new Map(providers.map((provider) => [provider.id, provider]))
  /** Profiles whose provider can answer this role at all. A provider without
   *  `embeddings` does not appear for the embedding role — capability gating,
   *  read as "is this worth offering here", not as a promise about the model.
   *  A profile naming a provider this build's catalogue does not know is kept
   *  rather than filtered: it is selectable today and hiding it would make a
   *  working selection unexplainable. */
  const offerable = profiles.filter((profile) => {
    const provider = byId.get(profile.providerId)
    return provider === undefined || canServe(provider, resolved.role)
  })

  return (
    <div className="flex flex-col gap-1 border-b border-line py-2 last:border-b-0">
      <div className="flex flex-wrap items-center gap-3">
        <span className="min-w-24 text-sm text-fg">{resolved.role}</span>

        {editable ? (
          <select
            className="input"
            aria-label={`Profile for the ${resolved.role} role`}
            value={resolved.profile ?? ''}
            disabled={busy}
            onChange={(event) => {
              const next = event.target.value
              if (next === '') onClear(resolved.role)
              else onSelect(resolved.role, next)
            }}
          >
            {/* "the setting's own value" rather than a blank: with no profile
                selected the role still resolves, through the setting named
                below. An empty option labelled nothing would read as "no model",
                which is never true. */}
            <option value="">(the {resolved.settingKey} setting)</option>
            {offerable.map((profile) => (
              <option key={profile.name} value={profile.name}>
                {profile.name} — {profile.model}
              </option>
            ))}
          </select>
        ) : (
          <span className="font-mono text-sm text-fg-dim">{resolved.profile ?? '—'}</span>
        )}

        <span className="font-mono text-sm text-fg">{resolved.model || '—'}</span>

        {resolved.profile !== null && editable ? (
          <Button small tone="quiet" disabled={busy} onClick={() => onClear(resolved.role)}>
            Clear
          </Button>
        ) : null}
      </div>

      {/* The setting this role writes, always. Small and mono, not hidden
          behind a hover: it is the thing that lets somebody match this row to
          the group below it. */}
      <code className="font-mono text-xs text-fg-faint">
        resolves through {resolved.settingKey} ({resolved.layer})
      </code>

      {shared.length > 0 ? (
        <p className="m-0 text-xs text-fg-dim">
          Shares <code className="font-mono">{resolved.settingKey}</code> with{' '}
          {shared.join(' and ')} — changing this changes{' '}
          {shared.length === 1 ? 'that role' : 'those roles'} too.
        </p>
      ) : null}

      {resolved.dangling ? (
        // Reported, never silently fallen back from. A role quietly repointed
        // at the default model is the exact failure profiles exist to prevent:
        // the person believes they are running a local model and are billing an
        // API, or the reverse, and nothing on screen disagrees with them.
        <p className="m-0 text-xs text-k-failure" role="alert">
          Selected profile <code className="font-mono">{resolved.profile}</code> is not defined at
          any scope in this chain. This role is not using it — pick one that exists, or define it
          here.
        </p>
      ) : null}
    </div>
  )
}
