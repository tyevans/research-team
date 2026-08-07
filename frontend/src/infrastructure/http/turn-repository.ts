import { z } from 'zod'

import type {
  ApprovalRepository,
  RunningTurn,
  TurnRepository,
} from '@application/ports/repositories.ts'
import type { ActivityEntry } from '@domain/activity/activity.ts'
import type { Approval, ApprovalDecision } from '@domain/approval/approval.ts'
import type { TurnRange } from '@domain/session/turn.ts'
import type { ApprovalId, SessionId } from '@domain/shared/identifier.ts'

import * as dto from './dto.ts'
import { HttpClient, seg } from './http-client.ts'
import { toActivityEntry, toApproval, toTurnRange } from './mappers.ts'

export class HttpTurnRepository implements TurnRepository {
  constructor(private readonly http: HttpClient) {}

  async send(id: SessionId, input: string): Promise<TurnRange | null> {
    return toTurnRange(
      await this.http.post(`/api/sessions/${seg(id)}/turns`, { input }, dto.turnResultDto),
    )
  }

  async cancel(id: SessionId): Promise<{ cancelled: boolean; settled: boolean }> {
    const result = await this.http.post(
      `/api/sessions/${seg(id)}/turns/cancel`,
      {},
      z.object({
        cancelled: z.boolean().default(false),
        // Absent means settled: only an unsettled cancel says so explicitly,
        // and defaulting the other way would claim the log was final when a
        // TurnFailed frame is still on its way.
        settled: z.boolean().default(true),
      }),
    )
    return result
  }

  async current(id: SessionId): Promise<RunningTurn> {
    const result = await this.http.get(
      `/api/sessions/${seg(id)}/turns/current`,
      dto.runningTurnDto,
    )
    return {
      running: result.running,
      turnIndex: result.turn_index,
      startedAt: result.started_at,
      elapsedSeconds: result.elapsed_seconds,
    }
  }

  async activity(
    id: SessionId,
  ): Promise<{ running: readonly ActivityEntry[]; discarded: readonly ActivityEntry[] }> {
    const body = await this.http.get(
      `/api/sessions/${seg(id)}/turns/current/activity`,
      dto.activityDto,
    )
    return {
      running: body.running.map(toActivityEntry),
      discarded: body.discarded.map(toActivityEntry),
    }
  }
}

export class HttpApprovalRepository implements ApprovalRepository {
  constructor(private readonly http: HttpClient) {}

  async pending(id: SessionId): Promise<readonly Approval[]> {
    const rows = await this.http.get(`/api/sessions/${seg(id)}/approvals`, z.array(dto.approvalDto))
    return rows.map(toApproval)
  }

  async decide(
    id: SessionId,
    approvalId: ApprovalId,
    decision: ApprovalDecision,
  ): Promise<void> {
    await this.http.post(
      `/api/sessions/${seg(id)}/approvals/${seg(approvalId)}`,
      { type: decision },
      dto.okDto,
    )
  }
}
