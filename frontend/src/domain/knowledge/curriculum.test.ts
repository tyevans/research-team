import { describe, expect, it } from 'vitest'

import {
  contestedEdges,
  stepsOf,
  type Curriculum,
  type LearningArea,
  type PrerequisiteEdge,
} from './curriculum.ts'

const area = (slug: string, size = 3): LearningArea => ({
  slug,
  title: slug.toUpperCase(),
  summary: null,
  size,
  truncatedMembers: false,
  members: [],
})

const edge = (before: string, after: string, over: Partial<PrerequisiteEdge> = {}) => ({
  before,
  after,
  weight: 1,
  reason: 'its entities are cited by the later area&rsquo;s more than the reverse',
  contested: false,
  ...over,
})

const curriculum = (over: Partial<Curriculum> = {}): Curriculum => ({
  areas: [area('one'), area('two'), area('three')],
  path: {
    slug: 'complete',
    title: 'The complete path',
    destination: null,
    areaSlugs: ['one', 'two', 'three'],
    edges: [edge('one', 'two'), edge('two', 'three')],
  },
  derivedFrom: {
    entities: 30,
    relationships: 12,
    passages: 40,
    semanticEdges: 0,
    usedEmbeddings: false,
    truncated: false,
  },
  ...over,
})

describe('stepsOf', () => {
  it('numbers the steps from one, in the order the path gave', () => {
    expect(stepsOf(curriculum()).map((s) => [s.position, s.area.slug])).toEqual([
      [1, 'one'],
      [2, 'two'],
      [3, 'three'],
    ])
  })

  it('attaches the edge that placed each step, keyed on where it lands', () => {
    const steps = stepsOf(curriculum())

    expect(steps.map((s) => s.reason?.before ?? null)).toEqual([null, 'one', 'two'])
  })

  it('gives a step no reason when nothing ordered it', () => {
    // The server omits an edge below its evidence floor rather than inventing a
    // weak one, so a step with no reason is telling the truth about the pair.
    // Rendering an invented "follows the previous area" would be the one place
    // this UI could manufacture a claim the projection declined to make.
    const steps = stepsOf(curriculum({ path: { ...curriculum().path, edges: [] } }))

    expect(steps.map((s) => s.reason)).toEqual([null, null, null])
  })

  it('does not offer a contested edge as a step&rsquo;s reason', () => {
    // A contested edge is shown once, at the top, as an interruption. Repeating
    // it inline as though it were an ordinary reason would present the one
    // ordering the graph could not settle as the best-explained step on screen.
    const steps = stepsOf(
      curriculum({
        path: { ...curriculum().path, edges: [edge('one', 'two', { contested: true })] },
      }),
    )

    expect(steps.map((s) => s.reason)).toEqual([null, null, null])
  })

  it('skips an area the path names but the map does not carry', () => {
    // The two lists come from one response computed in one pass, so a mismatch
    // means the projection changed under a stale tab. A row reading "unknown
    // area" would invite a reader to conclude something about their project
    // rather than about their tab.
    const steps = stepsOf(
      curriculum({
        path: { ...curriculum().path, areaSlugs: ['one', 'vanished', 'three'] },
      }),
    )

    expect(steps.map((s) => s.area.slug)).toEqual(['one', 'three'])
  })

  it('renumbers around a skipped area rather than leaving a gap', () => {
    const steps = stepsOf(
      curriculum({
        path: { ...curriculum().path, areaSlugs: ['one', 'vanished', 'three'] },
      }),
    )

    expect(steps.map((s) => s.position)).toEqual([1, 2])
  })

  it('is empty when the path is', () => {
    expect(stepsOf(curriculum({ path: { ...curriculum().path, areaSlugs: [] } }))).toEqual([])
  })
})

describe('contestedEdges', () => {
  it('finds the edges the order had to break a cycle to produce', () => {
    const found = contestedEdges(
      curriculum({
        path: {
          ...curriculum().path,
          edges: [edge('one', 'two'), edge('two', 'three', { contested: true })],
        },
      }),
    )

    expect(found.map((e) => e.after)).toEqual(['three'])
  })

  it('is empty when nothing was contested', () => {
    expect(contestedEdges(curriculum())).toEqual([])
  })
})
