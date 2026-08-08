import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useId, useState } from 'react'

import { notify } from '@application/notifications/toast-store.ts'
import { errorMessage } from '@application/ports/errors.ts'
import { queryKeys } from '@application/queries/keys.ts'
import { useContainer } from '@app/container-context.tsx'
import type { SeedingRun } from '@domain/research/seeding.ts'
import type { ProjectId } from '@domain/shared/identifier.ts'

import { Button } from '../common/primitives.tsx'
import { useStream } from '../shell/StreamProvider.tsx'

/** How many topics one seeding turn is asked to name -- matches the server's
 *  own default (`NewSeed.max_topics` in `app.py`), so a caller who has no
 *  opinion gets the amount `TopicSeeder`'s own tests exercise. */
const MAX_TOPICS = 8

/** The shape `seedStatus` resolves and the cache under `queryKeys.seed`
 *  therefore holds -- named so the two `setQueryData` folders below (the
 *  mutation's own optimistic write and the live-frame handler) can type
 *  their `previous` without referencing the query's own return, which
 *  `react-hooks/exhaustive-deps` would then treat as a stale dependency. */
type SeedStatus = { readonly current: SeedingRun | null; readonly last: SeedingRun | null }

/** A subject in, a broad first set of topics out.
 *
 * Reads its state through `useQuery` rather than `ExtractionPane`'s zustand
 * store, because there is nothing here to fold: `seedStatus` hands back the
 * one frame a run is currently at (see `SeedingRun`'s doc comment), not a
 * sequence of notes to accumulate over time the way extraction's stages are.
 * A plain query cache entry already is that one frame.
 *
 * Still follows `ExtractionPane`'s reconnect pattern, because the reason for
 * it is the same one: a seeding frame carries no feed position, so
 * `Last-Event-ID` cannot replay it, and a socket that drops mid-run would
 * otherwise leave this panel showing whatever it last saw. Refetching on
 * mount and on every reconnect is the only way back.
 *
 * A live seeding frame writes straight into the query cache the way the
 * mutation's own `onSuccess` does, rather than triggering a refetch --
 * without this, a run's `done`/`failed` state only reached the panel on the
 * next reload, and a failed run looked exactly like a hung one until then.
 *
 * The topics a run opens need no reading here -- `open_topic` already
 * appends to the log, so `TopicList`'s own query invalidates on those frames
 * and the new topics arrive next to this panel without its help.
 */
export const SeedPanel = ({ projectId }: { projectId: ProjectId }) => {
  const { topics } = useContainer()
  const queryClient = useQueryClient()
  const stream = useStream()
  const inputId = useId()
  const [subject, setSubject] = useState('')
  // The running frame `SeedingActivity.start` builds carries no `subject` --
  // see `seeding.py`: it is minted before the model call that would name one.
  // Kept here so "Naming topics for…" can say something while a run this tab
  // itself started is in flight; a run picked up by `catchUp` from another
  // tab still renders without it, which is the truthful state of the data.
  const [askedSubject, setAskedSubject] = useState<string | null>(null)

  const status = useQuery({
    queryKey: queryKeys.seed(projectId),
    queryFn: () => topics.seedStatus(projectId),
  })

  useEffect(
    () =>
      stream.onReconnect(() => {
        void queryClient.invalidateQueries({ queryKey: queryKeys.seed(projectId) })
      }),
    [stream, queryClient, projectId],
  )

  useEffect(
    () =>
      stream.onFrame((frame) => {
        if (frame.kind !== 'seeding' || frame.projectId !== projectId) return
        queryClient.setQueryData(queryKeys.seed(projectId), (previous: SeedStatus | undefined) =>
          frame.run.status === 'running'
            ? { current: frame.run, last: previous?.last ?? null }
            : { current: null, last: frame.run },
        )
      }),
    [stream, queryClient, projectId],
  )

  const seed = useMutation({
    mutationFn: (askedSubject: string) => topics.startSeed(projectId, askedSubject, MAX_TOPICS),
    onSuccess: (run, askedSubject) => {
      // The POST's own 202 body already is the running frame -- writing it
      // straight into the cache shows a run starting the instant it is
      // accepted, rather than waiting on a refetch that a 409 test would
      // otherwise need to distinguish from "nothing happened yet".
      queryClient.setQueryData(queryKeys.seed(projectId), (previous: SeedStatus | undefined) => ({
        current: run,
        last: previous?.last ?? null,
      }))
      setAskedSubject(askedSubject)
      setSubject('')
    },
    // A second concurrent run answers 409, and a caller that swallowed it
    // would leave the control looking like the click did nothing.
    onError: (error) => notify(errorMessage(error), 'bad'),
  })

  const current = status.data?.current ?? null
  const last = status.data?.last ?? null
  const active = seed.isPending || current?.status === 'running'
  const trimmed = subject.trim()
  // Trimmed before the check, not just before the request -- three spaces
  // are not a subject, the same rule `TopicStatusDialog`'s justification
  // enforces for the identical reason.
  const canSubmit = trimmed.length > 0 && !active

  const submit = () => {
    if (!canSubmit) return
    seed.mutate(trimmed)
  }

  return (
    <div className="seed-panel">
      <form
        className="seed-form"
        onSubmit={(event) => {
          event.preventDefault()
          submit()
        }}
      >
        <label htmlFor={inputId}>Subject</label>
        <input
          id={inputId}
          className="input seed-input"
          value={subject}
          onChange={(event) => setSubject(event.target.value)}
          placeholder="spaced repetition and memory consolidation"
          disabled={active}
        />
        <Button type="submit" tone="accent" disabled={!canSubmit}>
          {active ? 'Seeding…' : 'Seed topics'}
        </Button>
      </form>

      {current?.status === 'running' ? (
        <p className="seed-status" role="status">
          {(current.subject ?? askedSubject)
            ? `Naming topics for “${current.subject ?? askedSubject}”…`
            : 'Naming topics…'}
        </p>
      ) : null}

      {last ? <LastRun last={last} /> : null}
    </div>
  )
}

const LastRun = ({ last }: { last: SeedingRun }) => (
  <p className={last.status === 'failed' ? 'seed-status seed-failed' : 'seed-status'}>
    {last.status === 'failed'
      ? `The last seed failed${last.detail ? `: ${last.detail}` : ''}`
      : `Last seed opened topics for “${last.subject ?? 'an earlier subject'}”`}
  </p>
)
