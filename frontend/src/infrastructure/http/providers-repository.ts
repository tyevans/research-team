import { ApiError } from '@application/ports/errors.ts'
import type { ProvidersRepository } from '@application/ports/repositories.ts'
import type { ScopeRef } from '@domain/settings/layer.ts'
import type { ProbeResult, Provider } from '@domain/settings/provider.ts'
import type { Profile, ResolvedRole, Role } from '@domain/settings/role.ts'
import type { Scope } from '@domain/settings/spec.ts'

import * as dto from './dto.ts'
import { HttpClient, seg } from './http-client.ts'
import { toProbeResult, toProfile, toProvider, toResolvedRole } from './mappers.ts'

/** `settings.py`'s provider and profile routes.
 *
 * The chain-to-query-string rule is `HttpSettingsRepository`'s, verbatim and
 * deliberately duplicated rather than shared: the two repositories are
 * separate ports on purpose, and a shared private helper between them would be
 * the one piece of coupling that makes the split cosmetic. It is four lines.
 */
export class HttpProvidersRepository implements ProvidersRepository {
  constructor(private readonly http: HttpClient) {}

  async catalogue(): Promise<readonly Provider[]> {
    const body = await this.http.get('/api/providers', dto.providersDto)
    return body.providers.map(toProvider)
  }

  async test(
    providerId: string,
    credentials: { apiKey?: string; baseUrl?: string },
  ): Promise<ProbeResult> {
    // Both fields omitted rather than sent as empty strings when absent. An
    // empty `api_key` is not the same request as no `api_key` -- the route
    // treats the second as "test what you can without one", which is how a
    // provider needing no auth is tested at all.
    const body: Record<string, string> = {}
    if (credentials.apiKey) body['api_key'] = credentials.apiKey
    if (credentials.baseUrl) body['base_url'] = credentials.baseUrl
    return toProbeResult(
      await this.http.post(`/api/providers/${seg(providerId)}/test`, body, dto.probeResultDto),
    )
  }

  async profiles(chain: readonly ScopeRef[]): Promise<{
    readonly profiles: readonly Profile[]
    readonly roles: readonly ResolvedRole[]
  }> {
    const params = new URLSearchParams()
    for (const ref of chain) params.set(ref.scope, ref.scopeId)
    const printed = params.toString()
    const body = await this.http.get(
      `/api/profiles${printed ? `?${printed}` : ''}`,
      dto.profilesDto,
    )
    return { profiles: body.profiles.map(toProfile), roles: body.roles.map(toResolvedRole) }
  }

  async saveProfile(
    scope: Scope,
    scopeId: string,
    name: string,
    definition: {
      readonly providerId: string
      readonly model: string
      readonly credentialKey?: string | null
      readonly baseUrl?: string | null
      readonly parameters?: Readonly<Record<string, unknown>>
    },
  ): Promise<void> {
    await this.http.put(
      `/api/profiles/${seg(scope)}/${seg(scopeId)}/${seg(name)}`,
      {
        provider_id: definition.providerId,
        model: definition.model,
        credential_key: definition.credentialKey ?? null,
        base_url: definition.baseUrl ?? null,
        // `{}` rather than omitted: the route defaults it, and sending the
        // field explicitly means a profile saved with no parameters clears
        // any that a previous definition of the same name carried. A `PUT` is
        // a replacement, and a partial body would make it a merge.
        parameters: definition.parameters ?? {},
      },
      dto.profileDto,
    )
  }

  deleteProfile(scope: Scope, scopeId: string, name: string): Promise<boolean> {
    return this.removed(`/api/profiles/${seg(scope)}/${seg(scopeId)}/${seg(name)}`)
  }

  async selectRole(scope: Scope, scopeId: string, role: Role, profile: string): Promise<void> {
    await this.http.put(
      `/api/profiles/${seg(scope)}/${seg(scopeId)}/roles/${seg(role)}`,
      { profile },
      dto.resolvedRoleDto,
    )
  }

  clearRole(scope: Scope, scopeId: string, role: Role): Promise<boolean> {
    return this.removed(`/api/profiles/${seg(scope)}/${seg(scopeId)}/roles/${seg(role)}`)
  }

  /** A `DELETE` whose 404 is an outcome rather than a failure.
   *
   * Shared by the two delete methods here for the reason `HttpSettingsRepository.clear`
   * states: 404 means "there was nothing here", which is an answer to a
   * question the UI asked. A 422 -- an unknown scope, a role that is not one of
   * the five -- still throws, because that one means the request was wrong. */
  private async removed(path: string): Promise<boolean> {
    try {
      await this.http.delete(path, dto.noContentDto)
      return true
    } catch (error) {
      if (error instanceof ApiError && error.isNotFound) return false
      throw error
    }
  }
}
