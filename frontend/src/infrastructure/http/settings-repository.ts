import { ApiError } from '@application/ports/errors.ts'
import type { SettingsRepository } from '@application/ports/repositories.ts'
import type { ResolvedSettings, ScopeRef } from '@domain/settings/layer.ts'
import type { ProbeResult, Provider, Scope, SettingsSchema } from '@domain/settings/spec.ts'

import * as dto from './dto.ts'
import { HttpClient, seg } from './http-client.ts'
import { toProbeResult, toProvider, toResolvedSettings, toSettingsSchema } from './mappers.ts'

/** `settings.py`'s four routes.
 *
 * The one place with any behaviour of its own is `clear`, and it is behaviour
 * this adapter must have rather than push upward: the route answers **404 when
 * there was no override**, deliberately, and a caller that let that escape as
 * an `ApiError` would show "clearing failed" for a case where nothing failed.
 * Turning it into `false` here is the whole reason S2 can tell "cleared" from
 * "there was nothing to clear" — which is the distinction the 404 exists to
 * preserve.
 */
export class HttpSettingsRepository implements SettingsRepository {
  constructor(private readonly http: HttpClient) {}

  async schema(): Promise<SettingsSchema> {
    return toSettingsSchema(await this.http.get('/api/settings/schema', dto.settingsSchemaDto))
  }

  async resolved(chain: readonly ScopeRef[]): Promise<ResolvedSettings> {
    // Built with `URLSearchParams` rather than `query()` from `http-client`,
    // because the chain is a list of refs rather than a record and the same
    // scope cannot appear twice. An empty chain prints a bare path — which is
    // a real request, not a degenerate one: it is exactly the "what would this
    // fall back to" call a project page makes with its own scope omitted.
    const params = new URLSearchParams()
    for (const ref of chain) params.set(ref.scope, ref.scopeId)
    const printed = params.toString()
    const body = await this.http.get(
      `/api/settings/resolved${printed ? `?${printed}` : ''}`,
      dto.resolvedSettingsDto,
    )
    return toResolvedSettings(body)
  }

  async providers(): Promise<readonly Provider[]> {
    const body = await this.http.get('/api/providers', dto.providersDto)
    return body.providers.map(toProvider)
  }

  async testProvider(
    providerId: string,
    credentials: { apiKey: string | null; baseUrl: string | null },
  ): Promise<ProbeResult> {
    // `api_key` and `base_url` are sent as `null` rather than omitted when
    // empty, which is what the route's own `ProbeRequest` defaults them to:
    // `null` there means "use the catalogue's", and an empty string would
    // mean "dial the empty endpoint" -- a distinction the form has to be able
    // to express, because "test the provider's own default" is a real thing
    // to ask for on a project that has overridden nothing.
    const body = await this.http.post(
      `/api/providers/${seg(providerId)}/test`,
      { api_key: credentials.apiKey, base_url: credentials.baseUrl },
      dto.probeResultDto,
    )
    return toProbeResult(body)
  }

  async put(scope: Scope, scopeId: string, key: string, value: string): Promise<void> {
    // The response is decoded and discarded. It carries `stored: true` and the
    // echo of what was written, none of which the page needs -- but decoding
    // it means a backend that changed the shape of a successful write is a
    // `ContractError` here rather than a silent success, which is the same
    // trade every other call on this client makes.
    await this.http.put(
      `/api/settings/${seg(scope)}/${seg(scopeId)}/${seg(key)}`,
      { value },
      dto.settingWriteDto,
    )
  }

  async clear(scope: Scope, scopeId: string, key: string): Promise<boolean> {
    try {
      await this.http.delete(
        `/api/settings/${seg(scope)}/${seg(scopeId)}/${seg(key)}`,
        dto.noContentDto,
      )
      return true
    } catch (error) {
      // Narrowly 404 and nothing else. A 422 (unknown key, unknown scope) is a
      // real failure and still throws -- which matters, because 404 and 422
      // both mean "that key did nothing" from a distance, and only one of them
      // means the key was spelled wrong.
      if (error instanceof ApiError && error.isNotFound) return false
      throw error
    }
  }
}
