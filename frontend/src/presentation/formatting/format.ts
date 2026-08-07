import {
  differenceInDays,
  differenceInHours,
  differenceInMinutes,
  differenceInSeconds,
  isValid,
  parseISO,
} from 'date-fns'

/** Display formatting. Not domain — these choices are about a reader's eye, and
 *  they change when the layout does.
 *
 * The relative-time and duration cases delegate to `date-fns` rather than to
 * the hand-rolled ladder of second thresholds they replace: that ladder had to
 * be read carefully to see it was right, and it was one locale away from being
 * wrong.
 */

const parse = (iso: string | null | undefined): Date | null => {
  if (!iso) return null
  const date = parseISO(iso)
  return isValid(date) ? date : null
}

/** `14:03:22` — the timeline's own column, where alignment matters more than
 *  locale niceties, so it is built rather than localised. */
export const clockTime = (iso: string | null | undefined): string => {
  const date = parse(iso)
  if (!date) return '--:--:--'
  const pad = (value: number) => String(value).padStart(2, '0')
  return `${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`
}

/** The full moment, for a tooltip. Localised, because nothing is aligned to it. */
export const fullTime = (iso: string | null | undefined): string => {
  const date = parse(iso)
  return date ? date.toLocaleString() : String(iso ?? 'unknown time')
}

/** "just now", "51m ago", "3h ago", "2d ago".
 *
 * Abbreviated deliberately: this sits in a dense monospace column beside two
 * other stats, and "51 minutes ago" pushes the row wide enough to wrap. The
 * arithmetic is `date-fns`' — calendar days are not 86400 seconds across a DST
 * boundary, which is the part worth not hand-rolling — and only the vocabulary
 * is ours. */
export const relativeTime = (iso: string | null | undefined, now = new Date()): string => {
  const date = parse(iso)
  if (!date) return 'unknown'
  if (differenceInSeconds(now, date) < 45) return 'just now'
  const minutes = differenceInMinutes(now, date)
  if (minutes < 90) return `${minutes}m ago`
  const hours = differenceInHours(now, date)
  if (hours < 48) return `${hours}h ago`
  return `${differenceInDays(now, date)}d ago`
}

/** How long something has been running, in the one unit that reads fastest at
 *  that scale. Seconds up to a minute and a half, minutes above it. */
export const elapsed = (sinceMs: number | null, now = Date.now()): string => {
  if (!sinceMs) return ''
  const seconds = Math.max(0, Math.round((now - sinceMs) / 1000))
  return seconds < 90 ? `${seconds}s` : `${Math.round(seconds / 60)}m`
}

export const elapsedSince = (
  iso: string | null,
  fallbackSeconds: number | null,
  now = Date.now(),
): string | null => {
  const date = parse(iso)
  // `started_at` is preferred: it keeps counting up as the turn runs, where
  // `elapsed_seconds` is a snapshot taken when we asked.
  const seconds = date ? (now - date.getTime()) / 1000 : fallbackSeconds
  if (seconds === null) return null
  const whole = Math.max(0, Math.round(seconds))
  return whole < 90 ? `${whole}s` : `${Math.round(whole / 60)}m`
}

export const bytes = (n: number | null | undefined): string => {
  if (typeof n !== 'number' || !Number.isFinite(n)) return '-'
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`
  return `${(n / 1048576).toFixed(1)} MB`
}

export const plural = (n: number | null | undefined, one: string, many?: string): string => {
  const value = typeof n === 'number' ? n : 0
  return `${value} ${value === 1 ? one : (many ?? `${one}s`)}`
}
