import type { InteractionLogHealth } from '@domain/interaction/log.ts'

import { plural, relativeTime } from '../formatting/format.ts'

/** Is the instrument working.
 *
 * First on the page because it is what makes the other two questions
 * trustworthy: counts by kind and a per-view dwell table are readings from an
 * instrument, and a reading is worth nothing until somebody has said the
 * instrument is on.
 *
 * **Three states, not two.** `collecting` is a fact about the recorder's
 * environment variable rather than about the data, so "switched off" and
 * "broken" are distinguishable -- an empty log that is collecting is a third
 * answer again, and it is the one that means something is wrong. Rendering
 * only a total would collapse all three into "0".
 *
 * **The failures block renders when there is something in it and never
 * otherwise, and there is deliberately no green counterpart.** A red block
 * that is usually absent is readable: its presence is the whole message. A
 * tick that is always there is furniture, and the eye stops seeing furniture
 * within a day -- which is exactly how a health number comes to be on screen
 * for a whole feature while reading zero, the defect `CLAUDE.md` records under
 * the co-mention channel.
 */
export const HealthStrip = ({
  health,
  /** Injected so the rendered age is a fact a test can assert on rather than
   *  a moving target. Every other caller takes the default. */
  now = new Date(),
}: {
  health: InteractionLogHealth
  now?: Date
}) => (
  <section aria-label="Log health" className="flex flex-wrap items-baseline gap-4 px-3 py-2">
    <Stat
      label="collection"
      value={health.collecting ? 'on' : 'off'}
      // The one place on this page where a word is coloured. `off` is not an
      // error -- somebody set the variable -- but it is the explanation for
      // every empty number to its right, and a reader who misses it will look
      // for a bug instead.
      alarm={!health.collecting}
    />
    <Stat label="events" value={String(health.total)} />
    <Stat
      label="last event"
      // `relativeTime` takes the ISO string the rest of the console passes it;
      // the domain layer parsed this into a `Date` because the age is
      // arithmetic, and this is the one place it goes back.
      value={health.total === 0 ? 'never' : relativeTime(health.lastAt?.toISOString() ?? null, now)}
    />
    <Stat label="installs" value={String(health.installCount)} />
    <Stat label="browser sessions" value={String(health.sessionCount)} />
    {health.failures.length > 0 ? <Failures failures={health.failures} /> : null}
  </section>
)

const Stat = ({ label, value, alarm }: { label: string; value: string; alarm?: boolean }) => (
  <span className="flex items-baseline gap-1">
    <span className="text-xs text-fg-faint">{label}</span>
    <span className={alarm ? 'font-mono text-md text-k-failure' : 'font-mono text-md'}>
      {value}
    </span>
  </span>
)

const Failures = ({ failures }: { failures: InteractionLogHealth['failures'] }) => (
  <div role="alert" className="error-box w-full">
    <strong>{plural(failures.length, 'event')} the projection could not process</strong>
    <ul className="m-0 list-none p-0">
      {failures.map((failure) => (
        <li key={failure.id} className="font-mono text-sm">
          {failure.eventType}: {failure.error}
        </li>
      ))}
    </ul>
  </div>
)
