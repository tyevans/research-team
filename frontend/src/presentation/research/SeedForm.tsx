import { useId } from 'react'
import clsx from 'clsx'

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
  // not a subject, the same rule `TopicManagePane`'s justification enforces
  // for the identical reason.
  const canSubmit = subject.trim().length > 0 && !active

  return (
    <div className="flex flex-col gap-[8px]">
      <form
        className="flex items-center gap-[8px]"
        onSubmit={(event) => {
          event.preventDefault()
          if (canSubmit) onSubmit()
        }}
      >
        {/* The label's dressing was a descendant rule (`.seed-form label`) and
            is written on the element now. That is the only kind of rule this
            rewrite cannot preserve as-is: a descendant selector dresses
            whatever is put inside it later, a utility dresses this label. */}
        <label htmlFor={inputId} className="text-xs text-fg-dim">
          Subject
        </label>
        {/* `input` stays a class: it is the shared field style, declared in
            `composer.css` for every text field in the console, and it is not
            this slice's to dissolve. `flex-1` is what `.seed-input` set — the
            box takes the row's slack so the label and the button keep their
            content widths. */}
        <input
          id={inputId}
          className="input flex-1"
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
        <p className={STATUS_LINE} role="status">
          {(current.subject ?? askedSubject)
            ? `Naming topics for “${current.subject ?? askedSubject}”…`
            : 'Naming topics…'}
        </p>
      ) : null}

      {last ? <LastRun last={last} /> : null}
    </div>
  )
}

/** What `.seed-status` set. `m-0` because this build imports no preflight and
 *  a bare `<p>` keeps the user agent's block margins, which is the gap the
 *  8px column gap is supposed to be. */
const STATUS_LINE = 'm-0 text-xs text-fg-dim'

/** `text-k-failure` and not `text-fg-dim`: `.seed-failed` overrode the dim
 *  grey with `--k-failure`, and the failure tone is the only thing telling a
 *  failed run apart from a finished one at a glance. `--fg-faint` is not an
 *  option in either place — it fails contrast against every surface (task 45).
 *
 * `data-failed` carries the state rather than the colour class doing double
 * duty: `SeedPanel.test.tsx` used to assert `seed-failed`, and a test that
 * asserts a dressing class breaks every time the dressing is restyled.
 */
const LastRun = ({ last }: { last: SeedingRun }) => (
  <p
    data-failed={last.status === 'failed'}
    className={clsx(STATUS_LINE, last.status === 'failed' && 'text-k-failure')}
  >
    {last.status === 'failed'
      ? `The last seed failed${last.detail ? `: ${last.detail}` : ''}`
      : `Last seed opened topics for “${last.subject ?? 'an earlier subject'}”`}
  </p>
)
