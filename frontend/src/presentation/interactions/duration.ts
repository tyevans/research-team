/** Durations a reader can read, and the absence a median can genuinely be.
 *
 * Its own module rather than an entry in `presentation/formatting/format.ts`
 * because the rules here are this pane's: `elapsed` there answers "how long
 * has this been running" and rounds to whole seconds, which is right for a
 * turn that has been going for four minutes and wrong for a dwell of 340ms --
 * it prints `0s`, and `0s` on a friction surface reads as a view nobody
 * stayed on rather than as one they left immediately.
 *
 * Everything the explorer measures arrives in milliseconds (`dwell_ms`,
 * `hidden_ms`, `latency_ms`), so this takes milliseconds and nothing else.
 */

/** What a median with nothing to take a median of looks like.
 *
 * An em-dash rather than `0`, and this is the whole reason the function below
 * distinguishes `null` from a number at all: a view with entries and no exits
 * has no dwell, and rendering that as `0.0s` is a claim that people left it
 * instantly. The spec calls the null a real state; this is that state having a
 * spelling. */
export const ABSENT = '—'

/** `2.3s`, `1m 12s`, `2h 5m`, and `—` for a value that is not there.
 *
 * One decimal below a minute because that is the band the log's numbers live
 * in -- a dwell, a hidden slice and an approval latency are all usually a few
 * seconds, and the tenth is the difference between click-through and
 * deliberation. Whole seconds above a minute, because nobody reads the tenth
 * of `1m 12.4s`.
 *
 * Negative input is clamped rather than rejected: `dwell_ms` comes from
 * `performance.now()` and cannot go backwards, but `hidden_ms` and a
 * hand-written payload can, and a rendered `-0.4s` would be a puzzle where a
 * `0.0s` is merely uninteresting.
 */
export const durationMs = (ms: number | null | undefined): string => {
  if (typeof ms !== 'number' || !Number.isFinite(ms)) return ABSENT
  const value = Math.max(0, ms)
  // 59_950 rather than 60_000: `(59_980 / 1000).toFixed(1)` is `"60.0"`, and
  // `60.0s` beside `1m 0s` is one duration with two spellings.
  if (value < 59_950) return `${(value / 1000).toFixed(1)}s`
  const seconds = Math.round(value / 1000)
  if (seconds < 3600) {
    const minutes = Math.floor(seconds / 60)
    const rest = seconds % 60
    return rest === 0 ? `${minutes}m` : `${minutes}m ${rest}s`
  }
  const hours = Math.floor(seconds / 3600)
  const minutes = Math.round((seconds % 3600) / 60)
  return minutes === 0 ? `${hours}h` : `${hours}h ${minutes}m`
}
