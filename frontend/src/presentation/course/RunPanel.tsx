import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'

import { notify } from '@application/notifications/toast-store.ts'
import { errorMessage } from '@application/ports/errors.ts'
import { queryKeys } from '@application/queries/keys.ts'
import { useContainer } from '@app/container-context.tsx'
import { ResearchDisabledError } from '@infrastructure/http/project-repository.ts'
import {
  ENDING_NOT_SEEN,
  endingFor,
  isLive,
  parseRoundCap,
  type ResearchRun,
  type RunProgress,
} from '@domain/research/run.ts'
import type { ProjectId } from '@domain/shared/identifier.ts'

import { Button, Chip } from '../common/primitives.tsx'
import { sessionHref } from '../routing/routes.ts'

const POLL_MS = 2_000

/** A run works this project's topic queue without anybody typing: one round is
 *  one topic and one turn.
 *
 * This panel's job is to make two things impossible to confuse — a run that is
 * going, and a run that has stopped — and to keep "stopped" from reading as
 * "finished". A run cannot decide it is done; every ending is a fold of its own
 * stream or of the queue, and only one of them means the work ran out.
 */
export const RunPanel = ({ projectId }: { projectId: ProjectId }) => {
  const { research } = useContainer()
  const queryClient = useQueryClient()
  const [cap, setCap] = useState('')
  // Whether this panel has ever seen a live run, which is what turns a later
  // "nothing running" into "it ended and this page missed the reason" rather
  // than the ordinary empty state. Declared before any early return: hooks run
  // in a fixed order or they run wrong.
  /** Whether this panel has ever seen the run live.
   *
   * State rather than a ref, and set during render rather than in an effect.
   * React supports exactly this — adjusting state when the props it derives
   * from change — and it is the only version that is safe under a discarded
   * render: a ref written during render keeps its value when the render is
   * thrown away, so a run this panel never actually showed as live could still
   * be reported as having ended. */
  const [seenLive, setSeenLive] = useState(false)

  const run = useQuery({
    queryKey: queryKeys.run(projectId),
    queryFn: () => research.current(projectId),
    // Polling only while something is in flight. A stopped run does not change,
    // and polling a feature that is switched off is noise on somebody's log.
    refetchInterval: (query) => (isLive(query.state.data ?? null) ? POLL_MS : false),
    retry: false,
  })

  const invalidate = () => queryClient.invalidateQueries({ queryKey: queryKeys.run(projectId) })

  const start = useMutation({
    mutationFn: () => {
      const parsed = parseRoundCap(cap)
      if (parsed.kind === 'invalid') throw new Error(parsed.reason)
      return research.start(projectId, parsed.kind === 'capped' ? parsed.rounds : null)
    },
    onSuccess: (started) => queryClient.setQueryData(queryKeys.run(projectId), started),
    onError: (error) => notify(errorMessage(error), 'bad'),
    onSettled: invalidate,
  })

  const cancel = useMutation({
    mutationFn: () => research.cancel(projectId),
    onSuccess: (cancelled) => {
      // Still running when this returns: cancelling asks the round in flight to
      // finish, because abandoning it would leave a half-written turn. So the
      // poll stays on and the panel keeps saying "running" until it is not.
      if (cancelled) notify('Asked the run to stop after this round.')
    },
    onError: (error) => notify(errorMessage(error), 'bad'),
    onSettled: invalidate,
  })

  if (run.error instanceof ResearchDisabledError) return <ResearchDisabledNotice />

  const current = run.data ?? null
  // A run this panel was watching that has left the live route: it ended, and
  // this page did not see with what reason. Saying that is the honest reading;
  // clearing back to "no run" would quietly retract an ending nobody read.
  if (isLive(current) && !seenLive) setSeenLive(true)
  const gone = seenLive && current === null && run.isFetched

  const live = isLive(current) && !gone

  return (
    <RunView
      run={current}
      gone={gone}
      live={live}
      cap={cap}
      onCap={setCap}
      starting={start.isPending}
      stopping={cancel.isPending}
      onStart={() => start.mutate()}
      onStop={() => cancel.mutate()}
    />
  )
}

/** The route is not exposed on this instance.

    Its own component because it is not a state of the panel -- there is no
    run, no controls and nothing to poll -- and because it is the one thing
    here worth reading on the gallery page without a server that refuses. */
export const ResearchDisabledNotice = () => (
  <div className="run-off">
    <strong>Autonomous research is off on this instance. </strong>
    Start the server with AGENT_AUTO_RESEARCH=1 to expose it. It is off by default because nothing
    authenticates this port, and this is the one route that would spend an hour of model time for
    whoever called it.
  </div>
)

/** The panel, given a run rather than fetching one.
 *
 * `live` and `gone` are props rather than derived here, and that is the point
 * of the split: both are facts about the *history* of the polling -- "this
 * page watched it run" and "it has since left the live route" -- which only
 * the container can know. Passing them in is what makes "ended, and this page
 * missed the reason" a state a story can show, where before it needed a fake
 * repository that answered a run and then `null`.
 */
export const RunView = ({
  run: current,
  gone,
  live,
  cap,
  onCap,
  starting,
  stopping,
  onStart,
  onStop,
}: {
  run: ResearchRun | null
  /** A run this page watched has left the live route without a reason. */
  gone: boolean
  /** Going now: the controls offer stopping rather than starting. */
  live: boolean
  cap: string
  onCap: (value: string) => void
  starting: boolean
  stopping: boolean
  onStart: () => void
  onStop: () => void
}) => {
  const capInput = (
    <input
      type="number"
      min="1"
      className="input run-rounds"
      placeholder="max rounds (optional)"
      value={cap}
      onChange={(event) => onCap(event.target.value)}
    />
  )

  return (
    <>
      <div className="run-head">
        <h3 className="run-title">Autonomous research</h3>
        {!current && !gone ? (
          <Chip>no run</Chip>
        ) : gone ? (
          <Chip tone="run-short">ended</Chip>
        ) : (
          <StatusChip progress={current!.progress} />
        )}
        {current?.progress?.readOnly ? (
          <Chip
            tone="readonly"
            title={
              'This run is under a policy that floors fetch at ask, so it works from material ' +
              'already in hand rather than deadlocking on an approval nobody is there to answer.'
            }
          >
            read-only
          </Chip>
        ) : null}
        <span className="run-spacer" />
        {/* The rounds are turns on that session, so it is where everything the
            agent actually said is readable. Counters here are only the shape. */}
        {current ? (
          <a
            className="btn btn-sm"
            href={sessionHref(current.sessionId)}
            title="The run’s rounds are turns on this session"
          >
            Open the run’s session
          </a>
        ) : null}
      </div>

      {!current && !gone ? (
        <>
          <p className="sub run-sub">
            A run works this project’s topic queue on its own: one round is one topic and one turn.
            Leave the cap empty to run under the domain’s own budget.
          </p>
          <div className="run-actions">
            {capInput}
            <Button tone="accent" disabled={starting} onClick={onStart}>
              {starting ? 'Starting…' : 'Start a run'}
            </Button>
          </div>
        </>
      ) : (
        <>
          {current ? <Counters run={current} live={live} /> : null}
          {live ? (
            <div className="run-actions">
              <Button
                tone="quiet"
                disabled={stopping}
                title="Asks the run to stop after the round it is in; it is not killed"
                onClick={onStop}
              >
                {stopping ? 'Asking it to stop…' : 'Stop after this round'}
              </Button>
            </div>
          ) : (
            <Ending
              progress={current?.progress ?? null}
              gone={gone}
              capInput={capInput}
              starting={starting}
              onStart={onStart}
            />
          )}
        </>
      )}
    </>
  )
}

const StatusChip = ({ progress }: { progress: RunProgress | null }) => {
  // No progress at all is the 202 body: a run that has begun and not been
  // folded. It has started, so that is what it says.
  if (!progress || progress.status === 'new') return <Chip tone="current">starting</Chip>
  if (progress.status === 'running') return <Chip tone="current">running</Chip>
  if (progress.status === 'stopped') {
    return <Chip tone={`run-${endingFor(progress.stopReason).tone}`}>stopped</Chip>
  }
  return <Chip tone="current">starting</Chip>
}

const Counters = ({ run, live }: { run: ResearchRun; live: boolean }) => {
  const progress = run.progress
  const cap = progress?.budget.maxRounds ? String(progress.budget.maxRounds) : '∞'

  return (
    <div className="run-body">
      <div className="run-cells">
        <Cell
          label="rounds"
          value={`${progress?.rounds ?? 0} / ${cap}`}
          title="Rounds worked, against the cap this run started under"
        />
        <Cell label="turns" value={String(progress?.turns ?? 0)} title="One turn per round" />
        {/* Counted by folding the topic before and after the turn, not by
            reading the reply — a round that describes a breakthrough and
            records nothing is an empty round. */}
        <Cell
          label="findings"
          value={String(progress?.findings ?? 0)}
          title="Appended to topic streams, folded rather than claimed"
        />
        <Cell
          label="quiet rounds"
          value={`${progress?.quietRounds ?? 0}${
            progress?.budget.quietRounds ? ` / ${progress.budget.quietRounds}` : ''
          }`}
          title="Consecutive rounds that recorded nothing; enough of them stop the run"
        />
        <Cell
          label="failures"
          value={String(progress?.failures ?? 0)}
          title="Consecutive failed turns; enough of them stop the run"
        />
      </div>
      <div className="run-working">
        {progress?.workingOn ? (
          <>
            <span className="muted">working on </span>
            <span className="run-topic">{progress.workingOn}</span>
          </>
        ) : (
          <span className="muted">
            {live ? 'between rounds — no topic claimed right now' : 'no topic in flight'}
          </span>
        )}
      </div>
    </div>
  )
}

const Cell = ({ label, value, title }: { label: string; value: string; title: string }) => (
  <div className="run-cell" title={title}>
    <span className="run-cell-value">{value}</span>
    <span className="run-cell-label">{label}</span>
  </div>
)

/** How a run ended, in words rather than as an enum value.
 *
 * The tone is the load-bearing part: a reader who skims a green box takes away
 * "done", and only one of these endings has earned that. */
const Ending = ({
  progress,
  gone,
  capInput,
  starting,
  onStart,
}: {
  progress: RunProgress | null
  gone: boolean
  capInput: React.ReactNode
  starting: boolean
  onStart: () => void
}) => {
  const ending = gone && !progress?.stopReason ? ENDING_NOT_SEEN : endingFor(progress?.stopReason)

  return (
    <div className={`run-ending run-ending-${ending.tone}`}>
      <div className="run-ending-head">
        <Chip tone={`run-${ending.tone}`}>{ending.label}</Chip>
        <span>{ending.headline}</span>
      </div>
      <p className="run-ending-text">{ending.text}</p>
      <div className="run-actions">
        {capInput}
        <Button disabled={starting} onClick={onStart}>
          {starting ? 'Starting…' : 'Start another run'}
        </Button>
      </div>
    </div>
  )
}
