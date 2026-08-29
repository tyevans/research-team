/** What a setting *is*, as `GET /api/settings/schema` declares it.
 *
 * Every label, bound, choice and group on the settings page is read from here
 * and none of it is typed into the frontend. That is `settings.py`'s own
 * argument, restated at this end of the wire: a settings UI that hand-writes
 * the same forty knobs is a second description of them, and it drifts on the
 * commit that adds the forty-first.
 *
 * So there is deliberately no list of keys in this directory, no enum of
 * groups, and no map from key to control. A control is chosen from `type`, a
 * bound comes from `minimum`/`maximum`, and a group is whatever the registry
 * called it.
 */

/** The scopes a setting can be written at, and the page can be opened at.
 *
 * A string union rather than an enum: it arrives from the wire and the three
 * spellings are the API's, so a second vocabulary would be a place for the two
 * to disagree. `environment` and `default` are *not* here — they are layers a
 * value can come from and not scopes anything can be written to, which is the
 * distinction `layer.ts` exists to keep. */
export const SCOPES = ['project', 'user', 'tenant'] as const
export type Scope = (typeof SCOPES)[number]

export const isScope = (value: string): value is Scope =>
  (SCOPES as readonly string[]).includes(value)

/** The five control shapes the schema can ask for. Closed, because the
 *  contract says it is closed — `string`, `integer`, `number`, `boolean`,
 *  `enum` — and an unrecognised sixth should be a decode failure naming the
 *  field rather than an input that silently renders as text. */
export type SettingType = 'string' | 'integer' | 'number' | 'boolean' | 'enum'

export interface SettingSpec {
  readonly key: string
  readonly envVar: string
  readonly type: SettingType
  readonly label: string
  readonly description: string
  readonly group: string
  readonly secret: boolean
  /** `null` for every secret, always, and that is the contract rather than an
   *  accident of this deployment. It is why the fallback line under a row
   *  cannot be computed from here — see `SettingsRepository.resolved`. */
  readonly default: string | number | boolean | null
  /** Non-empty exactly when `type` is `enum`. */
  readonly choices: readonly string[]
  readonly minimum: number | null
  readonly maximum: number | null
  /** Prose for help text, not a rule. The write route does not enforce it, so
   *  neither does the page: presenting it as validation would make the console
   *  assert something the server does not. */
  readonly requiredWhen: string | null
  readonly scopes: readonly Scope[]
}

export interface SettingGroup {
  readonly name: string
  readonly settings: readonly SettingSpec[]
}

/** Which setting answers a role. Read by S4's roles block; carried here from
 *  S1 because it arrives in the same response and dropping it at the mapper
 *  would be a field to re-add rather than a field to use. */
export interface RoleBinding {
  readonly role: string
  readonly settingKey: string
}

export interface SettingsSchema {
  /** In registry order, which the contract states is the order the form should
   *  render. The frontend sorts nothing. */
  readonly groups: readonly SettingGroup[]
  readonly scopes: readonly Scope[]
  readonly roles: readonly RoleBinding[]
}

/** The groups a given scope may see, with the settings that scope may set, and
 *  no empty group.
 *
 * Fourteen of the thirty-nine settings are tenant-only today and they are not
 * scattered — three whole groups are tenant-only — so this filter is most of
 * what keeps a project settings page from being a wall of knobs holding a
 * pgvector DSN. The counts are the registry's and nothing here asserts them.
 *
 * Empty groups are dropped rather than rendered folded: a heading with nothing
 * under it reads as "this is empty for you", which is a different and wrong
 * answer to "this does not apply at this scope". */
export const groupsForScope = (schema: SettingsSchema, scope: Scope): readonly SettingGroup[] =>
  schema.groups
    .map((group) => ({
      name: group.name,
      settings: group.settings.filter((spec) => spec.scopes.includes(scope)),
    }))
    .filter((group) => group.settings.length > 0)

/** Does this spec match what somebody typed into the search box?
 *
 * `envVar` is the load-bearing field and the reason this is a function rather
 * than a `label.includes`. Operators arrive at this page from
 * `AGENT_EXTRACTION_CHUNK_SIZE` in a compose file, and a search that cannot
 * find that sends them back to the shell. Key and description are matched too
 * because they cost nothing once the function exists. */
export const specMatches = (spec: SettingSpec, search: string): boolean => {
  const needle = search.trim().toLowerCase()
  if (needle === '') return true
  return (
    spec.label.toLowerCase().includes(needle) ||
    spec.key.toLowerCase().includes(needle) ||
    spec.envVar.toLowerCase().includes(needle) ||
    spec.description.toLowerCase().includes(needle)
  )
}
