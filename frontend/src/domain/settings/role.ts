import type { Layer } from './layer.ts'

/** The five things a model gets asked to do, and what answers each.
 *
 * The order is the order the block renders and it is not alphabetical: it is
 * research, extraction, curation, embedding, vision — roughly the order a
 * document moves through the system, which is the order somebody setting them
 * up thinks in. Alphabetical would put embedding before extraction and split
 * the two chat roles that share a setting.
 */
export const ROLES = ['research', 'extraction', 'curation', 'embedding', 'vision'] as const
export type Role = (typeof ROLES)[number]

/** A named model configuration a role can point at.
 *
 * `parameters` is an open record because it is provider-specific —
 * `temperature`, `top_p`, Anthropic's `thinking`, vLLM's
 * `chat_template_kwargs` — and a catalogue cannot enumerate what fifteen
 * providers accept. It is stored and handed back whole; nothing in the console
 * interprets it, which is why it is `unknown` rather than a shape. */
export interface Profile {
  readonly scope: string
  readonly scopeId: string
  readonly name: string
  readonly providerId: string
  readonly model: string
  /** The secret setting holding this provider's key — a `provider_key.*` in
   *  the dynamic namespace, or one of the four static ones. `null` where the
   *  provider needs none. */
  readonly credentialKey: string | null
  readonly baseUrl: string | null
  readonly parameters: Readonly<Record<string, unknown>>
}

export interface ResolvedRole {
  readonly role: Role
  /** What this role will actually call. */
  readonly model: string
  readonly layer: Layer
  readonly scopeId: string | null
  /** The setting this role resolves through. Rendered in mono under the row,
   *  because it is the bridge that keeps profiles additive and it is what makes
   *  the roles block and the `Models` group below it obviously the same data
   *  rather than two competing truths. */
  readonly settingKey: string
  readonly profile: string | null
  /** The selected profile names something no scope in the chain defines.
   *
   * **Reported, never silently fallen back from.** A role quietly repointed at
   * the default model is the exact failure this feature exists to prevent —
   * the person believes they are running a local model and are billing an API,
   * or the reverse, and nothing on screen disagrees with them. */
  readonly dangling: boolean
}

/** Roles that resolve through the same setting as this one.
 *
 * **`research` and `extraction` both resolve from `model` today**, so choosing
 * a cheap local model for extraction silently repoints the research agent.
 * That is the worst kind of settings bug — the user changed one thing and two
 * things moved — so the rows are drawn joined and the change is shown on both
 * before it is committed.
 *
 * Derived from the resolved roles rather than hardcoded as a pair: the sharing
 * is a fact about `ROLE_MODEL_KEYS` on the backend, and a frontend that wrote
 * `['research', 'extraction']` down would keep saying it after the backend
 * split them. */
export const sharing = (roles: readonly ResolvedRole[], role: Role): readonly Role[] => {
  const key = roles.find((candidate) => candidate.role === role)?.settingKey
  if (key === undefined) return []
  return roles
    .filter((candidate) => candidate.settingKey === key && candidate.role !== role)
    .map((candidate) => candidate.role)
}

/** Every group of roles that share a setting, each with more than one member.
 *
 * For the block's own banner, so the warning is stated once at the top as well
 * as on each affected row — somebody who reads the page top to bottom should
 * meet the fact before they meet a control it applies to. */
export const sharedGroups = (roles: readonly ResolvedRole[]): readonly (readonly Role[])[] => {
  const byKey = new Map<string, Role[]>()
  for (const role of roles) {
    const group = byKey.get(role.settingKey) ?? []
    group.push(role.role)
    byKey.set(role.settingKey, group)
  }
  return [...byKey.values()].filter((group) => group.length > 1)
}
