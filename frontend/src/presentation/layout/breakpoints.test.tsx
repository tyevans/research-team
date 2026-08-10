import { act, render, screen } from '@testing-library/react'
import { useState } from 'react'
import { afterEach, expect, it, vi } from 'vitest'

import { Pane } from './Pane.tsx'
import { Split } from './Split.tsx'
import type { Track } from './split-tracks.ts'

/** What a split does as the window crosses its two breakpoints.
 *
 * **This is the behaviour most at risk in the session migration**, and it was
 * unprotected until now: `splitTemplate` is tested at a given `wide`, and
 * `Pane` is tested at a given `collapsed`, and nothing drove either of them
 * across a boundary. The failure it guards is bad and quiet -- an inline
 * `grid-template-columns` written at a wide size and never cleared outranks
 * every media query beneath it, so a window that was ever wide never reflows
 * again, at a width nobody developing it is likely to sit at.
 *
 * **What it constrains.** Which media queries are asked, whether the answers
 * are re-read when they change, and what the components emit at each of the
 * three widths. **What it does not.** Anything about layout. jsdom computes no
 * geometry, so "two columns at 900px" is asserted as "no inline template, and
 * the stylesheet's rule is left to apply" -- the rule itself is unverified
 * here and has to be looked at in a browser.
 */

const TRACKS: readonly Track[] = [
  { id: 'timeline', min: 280, weight: 1.05 },
  { id: 'workspace', min: 320, weight: 1.5 },
  { id: 'conversation', min: 280, weight: 1.05 },
]

/** A `matchMedia` that answers from a width, and can be moved.
 *
 * Answering per query rather than a single boolean is the point: this file
 * exists because `wide` and `narrow` are different boundaries and the code
 * used to treat them as one. A stub that said the same thing to both could not
 * have caught that. */
const viewport = (initial: number) => {
  const listeners = new Set<() => void>()
  const asked = new Set<string>()
  let width = initial

  vi.stubGlobal('matchMedia', (query: string) => {
    asked.add(query)
    const min = Number(/min-width:\s*(\d+)px/.exec(query)?.[1] ?? '0')
    return {
      get matches() {
        return width >= min
      },
      media: query,
      addEventListener: (_: string, fn: () => void) => void listeners.add(fn),
      removeEventListener: (_: string, fn: () => void) => void listeners.delete(fn),
    }
  })

  return {
    resizeTo: (next: number) => {
      width = next
      act(() => {
        for (const fn of listeners) fn()
      })
    },
    get asked() {
      return [...asked]
    },
  }
}

const Workbench = () => {
  const [collapsed, setCollapsed] = useState<ReadonlySet<string>>(new Set(['timeline']))
  return (
    <Split
      id="session"
      label="Session panes"
      tracks={TRACKS}
      collapsed={collapsed}
      onCollapsedChange={setCollapsed}
    >
      <Pane id="timeline" label="Event log">
        rows
      </Pane>
      <Pane id="workspace" label="Workspace">
        files
      </Pane>
      <Pane id="conversation" label="Conversation">
        messages
      </Pane>
    </Split>
  )
}

const split = () => screen.getByRole('group', { name: 'Session panes' })
const pane = (label: string) => screen.getByRole('region', { name: label })

afterEach(() => {
  vi.unstubAllGlobals()
})

it('asks about both boundaries, spelled the way the stylesheets are', () => {
  const window_ = viewport(1440)
  render(<Workbench />)

  // The one pair of numbers written in two languages. `theme.test.ts` holds
  // these against `tokens.css`'s `--bp-*`; this holds them against what the
  // component actually asks for, which is the half that a refactor renaming a
  // breakpoint would break silently.
  expect(window_.asked).toContain('(min-width: 1181px)')
  expect(window_.asked).toContain('(min-width: 821px)')
})

it('writes tracks only above the wide breakpoint, and clears them on the way down', () => {
  const window_ = viewport(1440)
  render(<Workbench />)
  expect(split().style.gridTemplateColumns).toBe(
    'var(--rail-w) minmax(320px, 1.5fr) minmax(280px, 1.05fr)',
  )

  // The failure this exists for. Dragging a window narrow has to *clear* the
  // inline style, not merely stop updating it.
  window_.resizeTo(900)
  expect(split().style.gridTemplateColumns).toBe('')

  window_.resizeTo(375)
  expect(split().style.gridTemplateColumns).toBe('')

  // And back, because the collapsed set has to survive the round trip.
  window_.resizeTo(1440)
  expect(split().style.gridTemplateColumns).toBe(
    'var(--rail-w) minmax(320px, 1.5fr) minmax(280px, 1.05fr)',
  )
})

it('keeps a collapsed pane a rail between the breakpoints, and makes it a strip below', () => {
  const window_ = viewport(1440)
  render(<Workbench />)
  expect(pane('Event log')).toHaveAttribute('data-collapse-to', 'rail')

  // 900px: two columns, so the panes are still columns and a folded one is
  // still a 34px rail with its title on its side. Switching on `wide` -- which
  // is what the primitive did before the session view was migrated onto it --
  // turned it into a horizontal strip here, 360px of width early.
  window_.resizeTo(900)
  expect(pane('Event log')).toHaveAttribute('data-collapse-to', 'rail')

  // 375px: the panes stack, so a pane is a row and a rotated title would be
  // lying about which way the layout runs.
  window_.resizeTo(375)
  expect(pane('Event log')).toHaveAttribute('data-collapse-to', 'strip')

  window_.resizeTo(1440)
  expect(pane('Event log')).toHaveAttribute('data-collapse-to', 'rail')
})
