/**
 * Composable mapping combinators for the anti-corruption layer.
 *
 * These helpers standardize nullable/optional handling, branded identifier wrapping,
 * enum fallbacks, date conversions, and collection transformations across HTTP mappers.
 */

/**
 * Maps a nullable or optional value using `fn`, returning `null` when the input is null or undefined.
 */
export const optionalMap = <T, R>(
  val: T | null | undefined,
  fn: (value: T) => R,
): R | null => (val == null ? null : fn(val))

/**
 * Wraps a string in a branded identifier constructor, or returns `null` if the
 * string is null, undefined, or empty.
 */
export const brandOrNull = <T extends string, B>(
  val: T | null | undefined,
  brand: (value: T) => B,
): B | null => (val ? brand(val) : null)

/**
 * Converts an ISO-8601 timestamp string into a Date instance.
 */
export const toInstant = (raw: string): Date => new Date(raw)

/**
 * Converts a nullable ISO-8601 timestamp string into a Date instance, or `null`.
 */
export const toMaybeInstant = (raw: string | null | undefined): Date | null =>
  optionalMap(raw, toInstant)

/**
 * Parses an ISO-8601 timestamp string as epoch milliseconds, or `null` if the
 * input is null, undefined, empty, or unparseable.
 */
export const toEpoch = (raw: string | null | undefined): number | null => {
  if (!raw) return null
  const parsed = Date.parse(raw)
  return Number.isNaN(parsed) ? null : parsed
}

/**
 * Creates a mapping function that checks if a string is in a known set of enum
 * values; if not, falls back to the specified default value.
 */
export const enumWithDefault = <T extends string>(
  known: readonly T[],
  fallback: T,
): ((raw: string) => T) => {
  const set = new Set<string>(known)
  return (raw: string): T => (set.has(raw) ? (raw as T) : fallback)
}

/**
 * Creates a type guard verifying whether a string belongs to a known set of values.
 */
export const isOneOf = <T extends string>(known: readonly T[]): ((val: string) => val is T) => {
  const set = new Set<string>(known)
  return (val: string): val is T => set.has(val)
}

/**
 * Converts a plain record into a ReadonlyMap preserving key-value pairs.
 */
export const toMap = <V>(record: Readonly<Record<string, V>>): ReadonlyMap<string, V> =>
  new Map(Object.entries(record))

/**
 * Transforms a record into a ReadonlyMap, applying `mapValue` (and optionally `mapKey`)
 * to each entry.
 */
export const toRecordMap = <V, R, K extends string = string, RK = K>(
  record: Readonly<Record<K, V>>,
  mapValue: (val: V, key: K) => R,
  mapKey?: (key: K) => RK,
): ReadonlyMap<RK, R> =>
  new Map(
    Object.entries(record).map(([k, v]) => [
      mapKey ? mapKey(k as K) : (k as unknown as RK),
      mapValue(v as V, k as K),
    ]),
  )

/**
 * Maps the values of a record to new values while preserving its keys.
 */
export const mapValues = <T, R>(
  record: Readonly<Record<string, T>>,
  fn: (val: T, key: string) => R,
): Readonly<Record<string, R>> =>
  Object.fromEntries(Object.entries(record).map(([k, v]) => [k, fn(v, k)]))
