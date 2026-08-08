import type { AutonomyRepository } from '@application/ports/repositories.ts'
import type { AutonomyChange, AutonomyPolicyView } from '@domain/autonomy/autonomy.ts'
import type { SessionId } from '@domain/shared/identifier.ts'

import * as dto from './dto.ts'
import { HttpClient, seg } from './http-client.ts'
import { toAutonomy, toAutonomyChange } from './mappers.ts'

/** The autonomy routes.
 *
 * Note what this class does *not* do: it does not catch the 400 from
 * `setLevel`. The server's `ValueError` message names the offending value
 * (`unknown autonomy level: 'sometimes'`), `HttpClient` already lifts it out
 * of `detail`, and translating it here into something friendlier would replace
 * the only text that says which value was wrong.
 *
 * Nor does it default an absent policy to "everything auto". All three routes
 * 404 when no policy is wired, and that rejection propagates: "this build
 * cannot tell you" is a different claim from "nothing is gated", and only one
 * of them is safe to render as a set of switches.
 */
export class HttpAutonomyRepository implements AutonomyRepository {
  constructor(private readonly http: HttpClient) {}

  async read(): Promise<AutonomyPolicyView> {
    // No session in the path: this is a read of instance state, and there is
    // no per-session answer to give.
    return toAutonomy(await this.http.get('/api/autonomy', dto.autonomyDto))
  }

  async setLevel(id: SessionId, tool: string, level: string): Promise<AutonomyPolicyView> {
    return toAutonomy(
      await this.http.post(`/api/sessions/${seg(id)}/autonomy`, { tool, level }, dto.autonomyDto),
    )
  }

  async allowAll(id: SessionId, includeStageGates: boolean): Promise<AutonomyChange> {
    return toAutonomyChange(
      await this.http.post(
        `/api/sessions/${seg(id)}/autonomy/allow-all`,
        { include_stage_gates: includeStageGates },
        dto.autonomyChangeDto,
      ),
    )
  }
}
