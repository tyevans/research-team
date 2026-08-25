import { expect, it } from 'vitest'

import { splitTemplate, toggleCollapsed, type Track } from './split-tracks.ts'

/** The sizing rules, tested where they are actually decidable.
 *
 * **What these tests constrain, and what they do not.** They constrain the
 * *decision*: which template string is produced, and whether one is produced
 * at all. They constrain nothing about layout. jsdom computes no geometry --
 * `vitest.setup.ts` stubs `matchMedia`, `ResizeObserver` and
 * `getBoundingClientRect` with a comment saying real layout is Playwright's
 * job, and there is no Playwright in this repository -- so a test can assert
 * that `Split` emits `minmax(280px, 1.05fr) var(--rail-w) …` and can never
 * assert that the grid it describes puts three panes side by side, that the
 * rail is 34px wide, or that a collapsed pane gives its width to its
 * neighbours.
 *
 * That is the whole point of the split between this file and `Split.tsx`: the
 * part a test can hold is a pure function, so it is one. Everything else is
 * checked in Storybook, in a browser, by a person.
 *
 * Each assertion was proved red: the `wide` branch inverted, the rail track
 * replaced by a minmax, the `>=` in the last-open guard changed to `===`, and
 * `refused` hard-coded false.
 */

const TRACKS: readonly Track[] = [
  { id: 'timeline', min: 280, weight: 1.05 },
  { id: 'workspace', min: 320, weight: 1.5 },
  { id: 'conversation', min: 280, weight: 1.05 },
]

const none = new Set<string>()

it('sizes every open track from one declaration', () => {
  expect(splitTemplate({ tracks: TRACKS, collapsed: none, wide: true })).toBe(
    'minmax(280px, 1.05fr) minmax(320px, 1.5fr) minmax(280px, 1.05fr)',
  )
})

it('caps a track at a ceiling it declares instead of a share of the leftover', () => {
  // A sidebar is not a peer competing for free space: it is a fraction of the
  // window, and an fr weight cannot say that -- `1fr` of three tracks is a
  // share of what the *floors* left over, so the same weight is a different
  // fraction at every width. `max` says the fraction directly.
  //
  // Red without the `max` arm in `splitTemplate`: emits `minmax(344px, 1fr)`.
  const sidebar: readonly Track[] = [
    { id: 'queue', min: 344, max: '25%' },
    { id: 'material', min: 422, weight: 1 },
  ]

  expect(splitTemplate({ tracks: sidebar, collapsed: none, wide: true })).toBe(
    'minmax(344px, 25%) minmax(422px, 1fr)',
  )
})

it('gives a collapsed track the fixed rail width, not a smaller minmax', () => {
  // A fixed track rather than a reduced minimum, which is the whole point of
  // collapsing: the space a collapsed pane gives up has to go to the open
  // ones, and a `minmax` floor would keep claiming a share of the free space.
  expect(splitTemplate({ tracks: TRACKS, collapsed: new Set(['workspace']), wide: true })).toBe(
    'minmax(280px, 1.05fr) var(--rail-w) minmax(280px, 1.05fr)',
  )
})

it('emits no template at all below the breakpoint', () => {
  // The single most important assertion in this file. Below the widest
  // breakpoint the stylesheet reflows the panes, and an inline
  // `grid-template-columns` outranks a media query -- so a `Split` that
  // emitted a template here would silently defeat every responsive rule
  // beneath it, at a window width nobody developing it is likely to use.
  expect(splitTemplate({ tracks: TRACKS, collapsed: none, wide: false })).toBeUndefined()
  expect(
    splitTemplate({ tracks: TRACKS, collapsed: new Set(['timeline']), wide: false }),
  ).toBeUndefined()
})

it('collapses and expands a pane', () => {
  const first = toggleCollapsed({ tracks: TRACKS, collapsed: none, id: 'timeline' })
  expect([...first.collapsed]).toEqual(['timeline'])
  expect(first.refused).toBe(false)

  const back = toggleCollapsed({ tracks: TRACKS, collapsed: first.collapsed, id: 'timeline' })
  expect([...back.collapsed]).toEqual([])
})

it('refuses to hide the last open pane, and says that it refused', () => {
  const collapsed = new Set(['timeline', 'workspace'])
  const result = toggleCollapsed({ tracks: TRACKS, collapsed, id: 'conversation' })

  // A view with nothing in it has no way back except a toggle you can no
  // longer see. The research rail permits exactly this today and its own
  // report records the cost: a folded seeding pane, with fold state persisted
  // across reloads, leaves a reader looking at "nothing has been seeded" with
  // no seeding control anywhere on screen.
  expect(result.collapsed).toBe(collapsed)
  expect(result.refused).toBe(true)
})

it('refuses even when the collapsed set names a pane that no longer exists', () => {
  // The stale entry must not buy an extra fold. Every *real* pane here is
  // already folded, so the refusal is right whether or not the removed one is
  // counted -- which is what the test below is for. Collapsed state is
  // persisted across reloads in this console, so a set naming a pane from a
  // previous layout is ordinary rather than contrived.
  const collapsed = new Set(['timeline', 'workspace', 'a-pane-that-was-removed'])
  const result = toggleCollapsed({ tracks: TRACKS, collapsed, id: 'conversation' })

  expect(result.refused).toBe(true)
})

it('lets a pane close when the only thing in the way is a pane that was removed', () => {
  // The bug this was reported as: "I can never collapse the queue". The
  // project page's stored group still holds `holder` from when it had three
  // columns, and counting it made a two-track layout look full at one fold.
  // The reader is told a rule the layout is not up against, on a page where
  // nothing is folded at all.
  //
  // Fails against the old count, which was `next.size >= tracks.length` over
  // an unfiltered set.
  const tracks: readonly Track[] = [
    { id: 'queue', min: 344, max: '25%' },
    { id: 'material', min: 784, weight: 1 },
  ]
  const collapsed = new Set(['holder'])

  const result = toggleCollapsed({ tracks, collapsed, id: 'queue' })

  expect(result.refused).toBe(false)
  // And the dead entry is gone from what gets stored, rather than waiting to
  // confuse the next count.
  expect([...result.collapsed]).toEqual(['queue'])
})

it('drops a removed pane from the set when one is expanded', () => {
  // The other path out of `toggleCollapsed`, which returns early and would
  // keep the stale entry if the filter were applied only on the closing side.
  const tracks: readonly Track[] = [
    { id: 'queue', min: 344, max: '25%' },
    { id: 'material', min: 784, weight: 1 },
  ]

  const result = toggleCollapsed({
    tracks,
    collapsed: new Set(['holder', 'queue']),
    id: 'queue',
  })

  expect([...result.collapsed]).toEqual([])
})

it('never mutates the set it was given', () => {
  const collapsed = new Set(['timeline'])
  toggleCollapsed({ tracks: TRACKS, collapsed, id: 'workspace' })

  // The caller holds this set in React state. Mutating it in place would make
  // the change invisible to a re-render, which is the kind of bug that looks
  // like a missing dependency array for a week.
  expect([...collapsed]).toEqual(['timeline'])
})
