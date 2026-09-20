import { describe, expect, it } from 'vitest'

import {
  brandOrNull,
  enumWithDefault,
  isOneOf,
  mapValues,
  optionalMap,
  toEpoch,
  toInstant,
  toMaybeInstant,
  toMap,
  toRecordMap,
} from './mapper-utils.ts'

describe('mapper-utils', () => {
  describe('optionalMap', () => {
    it('returns null when input is null or undefined', () => {
      expect(optionalMap(null, (x: number) => x * 2)).toBeNull()
      expect(optionalMap(undefined, (x: number) => x * 2)).toBeNull()
    })

    it('transforms value when input is present', () => {
      expect(optionalMap(5, (x) => x * 2)).toBe(10)
      expect(optionalMap('hello', (s) => s.toUpperCase())).toBe('HELLO')
    })
  })

  describe('brandOrNull', () => {
    const Brand = (s: string) => `brand:${s}` as const

    it('returns null when input is null, undefined, or empty string', () => {
      expect(brandOrNull(null, Brand)).toBeNull()
      expect(brandOrNull(undefined, Brand)).toBeNull()
      expect(brandOrNull('', Brand)).toBeNull()
    })

    it('wraps valid string in brand constructor', () => {
      expect(brandOrNull('abc-123', Brand)).toBe('brand:abc-123')
    })
  })

  describe('toInstant and toMaybeInstant', () => {
    it('converts valid ISO string to Date', () => {
      const instant = toInstant('2026-01-01T12:00:00.000Z')
      expect(instant).toBeInstanceOf(Date)
      expect(instant.toISOString()).toBe('2026-01-01T12:00:00.000Z')
    })

    it('toMaybeInstant returns null on null or undefined', () => {
      expect(toMaybeInstant(null)).toBeNull()
      expect(toMaybeInstant(undefined)).toBeNull()
    })

    it('toMaybeInstant converts valid ISO string to Date', () => {
      const instant = toMaybeInstant('2026-01-01T12:00:00.000Z')
      expect(instant).toBeInstanceOf(Date)
      expect(instant?.toISOString()).toBe('2026-01-01T12:00:00.000Z')
    })
  })

  describe('toEpoch', () => {
    it('returns null for null, undefined, empty, or invalid strings', () => {
      expect(toEpoch(null)).toBeNull()
      expect(toEpoch(undefined)).toBeNull()
      expect(toEpoch('')).toBeNull()
      expect(toEpoch('invalid-date')).toBeNull()
    })

    it('returns epoch milliseconds for valid ISO string', () => {
      const ms = Date.parse('2026-01-01T00:00:00.000Z')
      expect(toEpoch('2026-01-01T00:00:00.000Z')).toBe(ms)
    })
  })

  describe('enumWithDefault', () => {
    const KNOWN = ['apple', 'banana', 'cherry'] as const
    const toFruit = enumWithDefault(KNOWN, 'apple')

    it('returns the known enum member', () => {
      expect(toFruit('apple')).toBe('apple')
      expect(toFruit('banana')).toBe('banana')
      expect(toFruit('cherry')).toBe('cherry')
    })

    it('returns the fallback for unknown strings', () => {
      expect(toFruit('pear')).toBe('apple')
      expect(toFruit('')).toBe('apple')
      expect(toFruit('APPLE')).toBe('apple')
    })
  })

  describe('isOneOf', () => {
    const KNOWN = ['one', 'two'] as const
    const isKnown = isOneOf(KNOWN)

    it('returns true for known values', () => {
      expect(isKnown('one')).toBe(true)
      expect(isKnown('two')).toBe(true)
    })

    it('returns false for unknown values', () => {
      expect(isKnown('three')).toBe(false)
      expect(isKnown('')).toBe(false)
    })
  })

  describe('toMap', () => {
    it('converts record to ReadonlyMap', () => {
      const map = toMap({ a: 1, b: 2 })
      expect(map.get('a')).toBe(1)
      expect(map.get('b')).toBe(2)
      expect(map.size).toBe(2)
    })
  })

  describe('toRecordMap', () => {
    it('maps values and keys into a ReadonlyMap', () => {
      const map = toRecordMap(
        { a: 1, b: 2 },
        (val) => val * 10,
        (key) => `key_${key}`,
      )
      expect(map.get('key_a')).toBe(10)
      expect(map.get('key_b')).toBe(20)
    })
  })

  describe('mapValues', () => {
    it('transforms values while preserving keys', () => {
      const result = mapValues({ x: 2, y: 3 }, (val) => val * 2)
      expect(result).toEqual({ x: 4, y: 6 })
    })
  })
})
