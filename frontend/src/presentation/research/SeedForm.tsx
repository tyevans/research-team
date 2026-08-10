import { useId } from 'react'

import type { SeedingRun } from '@domain/research/seeding.ts'

import { Button } from '../common/primitives.tsx'

/** A subject in, a broad first set of topics out — as markup over props.
 *
 * `subject` is controlled by the caller rather than held here, which looks
 * like ceremony and is not: the mutation clears it on success, so the field
 * and the request have to agree about who owns it. A component holding its own
 * draft and a hook clearing it on success is two owners, and the visible
 * failure is a subject that reappears in the box after a run starts.
 */
export const SeedForm = ({
  subject,
  current,
  last,
  askedSubject,
  active,
  onSubjectChange,
  onSubmit,
}: {
  subject: string
  /** The run in flight, if any. */
  current: SeedingRun | null
  /** The most recent finished run, kept so a failure stays on screen. */
  last: SeedingRun | null
  /** What *this tab* asked for. The running frame `SeedingActivity.start`
   *  builds carries no `subject` -- see `seeding.py`: it is minted before the
   *  model call that would name one. A run picked up from another tab has
   *  neither, which is the truthful state of the data and renders as
   *  "Naming topics…". */
  askedSubject: string | null
  active: boolean
  onSubjectChange: (subject: string) => void
  onSubmit: () => void
}) => {
  const inputId = useId()
  // Trimmed before the check, not just before the request -- three spaces are
  // not a subject, the same rule `TopicStatusDialog`'s justification enforces
  // for the identical reason.
  const canSubmit = subject.trim().length > 0 && !active

  return (
    <div className="seed-panel">
      <form
        className="seed-form"
        onSubmit={(event) => {
          event.preventDefault()
          if (canSubmit) onSubmit()
        }}
      >
        <label htmlFor={inputId}>Subject</label>
        <input
          id={inputId}
          className="input seed-input"
          value={subject}
          onChange={(event) => onSubjectChange(event.target.value)}
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
