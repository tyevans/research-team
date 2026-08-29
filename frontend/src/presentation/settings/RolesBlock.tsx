import type { Provider } from '@domain/settings/provider.ts'
import {
  ROLES,
  sharedGroups,
  type Profile,
  type ResolvedRole,
  type Role,
} from '@domain/settings/role.ts'

import { EmptyState } from '../common/primitives.tsx'
import { RoleRow } from './RoleRow.tsx'

/** The five roles, and what answers each.
 *
 * Rendered in `ROLES` order rather than in the order the response happens to
 * arrive: that order is research → extraction → curation → embedding → vision,
 * roughly the order a document moves through the system, which is the order
 * somebody setting them up thinks in.
 *
 * The shared-setting warning is stated **twice on purpose** — once here as a
 * banner and once on each affected row. Somebody reading top to bottom should
 * meet the fact before they meet a control it applies to; somebody who jumps
 * straight to the extraction row should still meet it. Duplicated copy is the
 * cheaper mistake than a person discovering it after a commit.
 */
export const RolesBlock = ({
  roles,
  profiles,
  providers,
  onSelect,
  onClear,
  busy,
}: {
  roles: readonly ResolvedRole[]
  profiles: readonly Profile[]
  providers: readonly Provider[]
  onSelect: (role: Role, profile: string) => void
  onClear: (role: Role) => void
  busy: boolean
}) => {
  const groups = sharedGroups(roles)
  const byRole = new Map(roles.map((role) => [role.role, role]))
  const ordered = ROLES.map((role) => byRole.get(role)).filter(
    (role): role is ResolvedRole => role !== undefined,
  )

  if (ordered.length === 0) {
    return (
      <EmptyState
        heading="No roles reported"
        detail="This build did not answer with any model roles, which usually means the profile store is not wired."
      />
    )
  }

  return (
    <section className="flex flex-col gap-2">
      <h2 className="m-0 text-md">Roles</h2>

      {groups.map((group) => (
        <p key={group.join('-')} className="m-0 text-sm text-fg-dim" role="note">
          <strong>{group.join(' and ')}</strong> resolve from the same setting, so changing one
          changes the {group.length === 1 ? 'other' : 'others'}. Give them separate profiles to
          separate them.
        </p>
      ))}

      <div className="flex flex-col">
        {ordered.map((role) => (
          <RoleRow
            key={role.role}
            resolved={role}
            roles={roles}
            profiles={profiles}
            providers={providers}
            onSelect={onSelect}
            onClear={onClear}
            busy={busy}
          />
        ))}
      </div>
    </section>
  )
}
