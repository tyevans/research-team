/** The provider catalogue, and what a connection test says back.
 *
 * Fifteen entries, static, no credential of any kind. As with `spec.ts`, none
 * of this is typed into the frontend: a sixteenth provider is a backend change
 * and no frontend change at all.
 */

/** What a provider *offers*, not what a particular model does.
 *
 * The contract is explicit that a catalogue cannot know whether a given model
 * has vision, so a picker reads this as "is an embedding role worth offering
 * here at all" rather than as a promise about the model somebody types in. The
 * tooltip on the chips says exactly that, because a capability chip beside a
 * model name invites the stronger reading. */
export type Capability = 'chat' | 'embeddings' | 'tools' | 'vision'

export type AuthKind = 'bearer' | 'header_key' | 'query_key' | 'signed' | 'none'

export interface Credential {
  readonly name: string
  readonly label: string
  /** Secrecy is per credential, not per provider. Azure's `resource` and
   *  `deployment` and Bedrock's `region` are declared not-secret and are stored
   *  and shown in the clear -- masking a region would make the settings page
   *  unreadable for the two providers that need the most from it. */
  readonly secret: boolean
  readonly required: boolean
  /** The static settings key this credential maps onto, when it maps onto one.
   *  `null` means it lives in the dynamic `provider_key.*` namespace. */
  readonly settingKey: string | null
}

export interface Provider {
  readonly id: string
  readonly displayName: string
  readonly baseUrl: string
  readonly auth: AuthKind
  readonly openaiCompatible: boolean
  readonly capabilities: readonly Capability[]
  readonly credentials: readonly Credential[]
  readonly notes: string
}

/** The five outcomes of a connection test.
 *
 * Five and not two, because "it didn't work" over a wrong key and over a
 * firewall send a person to completely different places -- one is a paste, the
 * other is a network. Each gets its own sentence in `TestOutcome`. */
export type ProbeOutcome = 'ok' | 'unauthorized' | 'unreachable' | 'unsupported' | 'error'

export interface ProbeResult {
  readonly providerId: string
  readonly outcome: ProbeOutcome
  readonly ok: boolean
  readonly detail: string
  /** Up to twenty-five model names. **This is the argument for giving the test
   *  a real button**: it is the step that turns an empty model picker into a
   *  list, rather than a validation nicety. Empty where the provider cannot
   *  enumerate -- Bedrock, Azure, anything `unsupported` -- and the picker
   *  falls back to free text with the outcome's `detail` as the reason. */
  readonly models: readonly string[]
  readonly latencyMs: number | null
}

/** `{placeholder}` markers in a base url, in the order they appear.
 *
 * Azure and Bedrock only -- `{resource}`, `{deployment}`, `{region}`. A form
 * has to fill them in before a test means anything, and an unfilled url
 * answers `unsupported` anyway, which is the honest second line of defence
 * rather than the only one.
 *
 * Parsed rather than declared because the contract states the markers live in
 * `base_url` and nowhere else; a second list of which providers have which
 * placeholders would be a copy that drifts the first time one changes. */
export const placeholdersIn = (baseUrl: string): readonly string[] => {
  const found = baseUrl.match(/\{([a-z_]+)\}/gi) ?? []
  // De-duplicated but order-preserving: a url naming `{region}` twice wants one
  // field, and the order is the reading order of the url, which is the order
  // somebody filling it in expects.
  return [...new Set(found.map((marker) => marker.slice(1, -1)))]
}

/** A base url with its placeholders filled. Any marker with no value is left
 *  standing, so a half-filled url is visibly half-filled rather than becoming
 *  a plausible-looking wrong address. */
export const fillPlaceholders = (
  baseUrl: string,
  values: Readonly<Record<string, string>>,
): string =>
  baseUrl.replace(/\{([a-z_]+)\}/gi, (marker, name: string) => {
    const value = values[name]
    return value === undefined || value === '' ? marker : value
  })

/** Is every placeholder filled? What `Test` is enabled on. */
export const isFilled = (baseUrl: string, values: Readonly<Record<string, string>>): boolean =>
  placeholdersIn(baseUrl).every((name) => (values[name] ?? '') !== '')

/** Can this provider answer this role at all?
 *
 * Capability gating, and it is deliberately one-directional: a provider with
 * no `embeddings` does not appear for the embedding role, and a provider that
 * *has* it is offered without any claim that the model somebody picks will. */
export const canServe = (provider: Provider, role: Role): boolean => {
  if (role === 'embedding') return provider.capabilities.includes('embeddings')
  if (role === 'vision') return provider.capabilities.includes('vision')
  return provider.capabilities.includes('chat')
}

/** The five roles, in the order the block renders them. Imported from `role.ts`
 *  rather than redeclared -- see there for why the order is not alphabetical. */
export type { Role } from './role.ts'
import type { Role } from './role.ts'
