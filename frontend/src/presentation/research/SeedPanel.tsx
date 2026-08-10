import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'

import { notify } from '@application/notifications/toast-store.ts'
import { errorMessage } from '@application/ports/errors.ts'
import { queryKeys } from '@application/queries/keys.ts'
import { useContainer } from '@app/container-context.tsx'
import type { SeedingRun } from '@domain/research/seeding.ts'
import type { ProjectId } from '@domain/shared/identifier.ts'

import { useStream } from '../shell/StreamProvider.tsx'
import { SeedForm } from './SeedForm.tsx'

/** How many topics one seeding turn is asked to name -- matches the server's
 *  own default (`NewSeed.max_topics` in `app.py`), so a caller who has no
 *  opinion gets the amount `TopicSeeder`'s own tests exercise. */
const MAX_TOPICS = 8

/** The shape `seedStatus` resolves and the cache under `queryKeys.seed`
 *  therefore holds -- named so the two `setQueryData` folders below (the
 *  mutation's own optimistic write and the live-frame handler) can type their
 *  `previous` without referencing the query's own return, which
 *  `react-hooks/exhaustive-deps` would then treat as a stale dependency. */
type SeedStatus = { readonly current: SeedingRun | null; readonly last: SeedingRun | null }

/** Seeding's container: the query, the mutation and the live frames.
 *
 * Reads its state through `useQuery` rather than `ExtractionPane`'s zustand
 * store, because there is nothing here to fold: `seedStatus` hands back the
 * one frame a run is currently at (see `SeedingRun`'s doc comment), not a
 * sequence of notes to accumulate over time the way extraction's stages are. A
 * plain query cache entry already is that one frame.
 *
 * Still follows `ExtractionPane`'s reconnect pattern, because the reason for
 * it is the same one: a seeding frame carries no feed position, so
 * `Last-Event-ID` cannot replay it, and a socket that drops mid-run would
 * otherwise leave this panel showing whatever it last saw. Refetching on mount
 * and on every reconnect is the only way back.
 *
 * A live seeding frame writes straight into the query cache the way the
 * mutation's own `onSuccess` does, rather than triggering a refetch -- without
 * this, a run's `done`/`failed` state only reached the panel on the next
 * reload, and a failed run looked exactly like a hung one until then.
 *
 * The topics a run opens need no reading here -- `open_topic` already appends
 * to the log, so the topic queue's own query invalidates on those frames and
 * the new topics arrive next to this panel without its help.
 *
 * No loading or error branch, deliberately, and this is the one container in
 * the slice without one: until `seedStatus` resolves there is no run to report
 * and the form is already the right thing to show. A spinner over a text box
 * that is about to appear unchanged is worse than the text box.
 */
export const SeedPanel = ({ projectId }: { projectId: ProjectId }) => {
  const { topics } = useContainer()
  const queryClient = useQueryClient()
  const stream = useStream()
  const [subject, setSubject] = useState('')
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
    mutationFn: (asked: string) => topics.startSeed(projectId, asked, MAX_TOPICS),
    onSuccess: (run, asked) => {
      // The POST's own 202 body already is the running frame -- writing it
      // straight into the cache shows a run starting the instant it is
      // accepted, rather than waiting on a refetch that a 409 test would
      // otherwise need to distinguish from "nothing happened yet".
      queryClient.setQueryData(queryKeys.seed(projectId), (previous: SeedStatus | undefined) => ({
        current: run,
        last: previous?.last ?? null,
      }))
      setAskedSubject(asked)
      setSubject('')
    },
    // A second concurrent run answers 409, and a caller that swallowed it
    // would leave the control looking like the click did nothing.
    onError: (error) => {
      notify(errorMessage(error), 'bad')
    },
  })

  const current = status.data?.current ?? null

  return (
    <SeedForm
      subject={subject}
      current={current}
      last={status.data?.last ?? null}
      askedSubject={askedSubject}
      active={seed.isPending || current?.status === 'running'}
      onSubjectChange={setSubject}
      onSubmit={() => {
        seed.mutate(subject.trim())
      }}
    />
  )
}
