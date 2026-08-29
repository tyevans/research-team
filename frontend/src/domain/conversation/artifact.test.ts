import { describe, expect, it } from 'vitest'

import { SHAPE_GLYPH, artifactOf, type Shape } from './artifact.ts'

const message = (artifact: unknown) => ({
  role: 'tool' as const,
  content: '19 match(es) …',
  toolCalls: [],
  isError: false,
  name: 'search_sources',
  artifact,
})

const hitList = {
  shape: 'hit_list',
  version: 1,
  pattern: 'magic',
  total: 19,
  suppressed: 0,
  sources: [
    {
      source_id: 's1',
      title: 'a',
      label: null,
      char_count: 100,
      total: 2,
      hits: [{ start: 1, end: 5, snippet: 'x' }],
    },
  ],
}

describe('artifactOf', () => {
  it('parses a hit list', () => {
    const parsed = artifactOf(message(hitList))
    expect(parsed?.shape).toBe('hit_list')
    expect(parsed?.shape === 'hit_list' && parsed.sources[0]?.hits[0]?.start).toBe(1)
  })

  it('returns null for a message written before artifacts existed', () => {
    // The permanent path, and the reason it is tested as a path rather than as
    // an error case: every message in a real database takes it.
    expect(artifactOf(message(null))).toBeNull()
    expect(artifactOf(message(undefined))).toBeNull()
  })

  it('returns null for a shape it does not know', () => {
    // Distinct from the case above only in what produced it -- an older console
    // meeting a newer backend. Both fall back to text, which is why `version`
    // is on the wire at all: without it the two are the same `null` and nobody
    // can tell an unconverted tool from an unreadable one.
    expect(artifactOf(message({ shape: 'hologram', version: 1 }))).toBeNull()
  })

  it('returns null rather than throwing on a malformed artifact', () => {
    // A card that throws takes the whole transcript down with it -- including
    // the surrounding messages a reader would use to work out what went wrong.
    expect(artifactOf(message({ shape: 'hit_list', version: 1 }))).toBeNull()
    expect(artifactOf(message({ shape: 'hit_list', version: 1, sources: 'lots' }))).toBeNull()
    expect(artifactOf(message('a string'))).toBeNull()
  })

  it('normalises an absent nullable to null rather than leaving it undefined', () => {
    // `title` is `str | None` in Python and is omitted by at least one tool.
    // A renderer writing `title ?? source_id` works either way; one writing
    // `'title' in source` does not, and the difference is invisible until a
    // card renders `undefined` as a source name.
    const parsed = artifactOf(
      message({
        ...hitList,
        sources: [{ ...hitList.sources[0], title: undefined, label: undefined }],
      }),
    )
    expect(parsed?.shape === 'hit_list' && parsed.sources[0]?.title).toBeNull()
  })

  it('keeps a value the schema does not describe from failing the parse', () => {
    // The console must keep working against a backend that grew a field it
    // does not read yet -- the same tolerance `dto.ts` states for every other
    // wire shape.
    const parsed = artifactOf(message({ ...hitList, weather: 'fine' }))
    expect(parsed?.shape).toBe('hit_list')
  })
})

describe('SHAPE_GLYPH', () => {
  it('names every shape exactly once', () => {
    // A shape with no glyph would render a blank gutter, which reads as a row
    // that failed rather than as a shape nobody assigned a mark to. Derived
    // from the union rather than hand-listed, so an eighth shape fails to
    // typecheck here before it can ship blank.
    const shapes: readonly Shape[] = [
      'hit_list',
      'entity_list',
      'excerpt',
      'inventory',
      'acknowledgement',
      'file_change',
      'delegation',
    ]
    for (const shape of shapes) expect(SHAPE_GLYPH[shape]).toBeTruthy()
    expect(new Set(Object.values(SHAPE_GLYPH)).size).toBe(shapes.length)
  })
})
