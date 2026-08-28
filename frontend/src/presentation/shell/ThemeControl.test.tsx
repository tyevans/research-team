import { render, screen } from '@testing-library/react'
import { userEvent } from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import { ThemeControl } from './ThemeControl.tsx'
import {
  nextThemeChoice,
  THEME_CHOICES,
  THEME_LABELS,
  THEME_STORAGE_KEY,
  type ThemeChoice,
} from './theme-choice.ts'
import { readThemeChoice } from './theme-storage.ts'

/** The control's behaviour, in jsdom, where **none of the colour is visible**.
 *
 * That split is deliberate and is worth stating so nobody adds a colour
 * assertion here and believes it. jsdom applies no stylesheet, so a test in
 * this file cannot tell a working theme from a broken one -- it can only tell
 * whether the right attribute was written and the right thing was stored and
 * announced. The other half, that the attribute changes what is painted, is
 * `src/styles/theme.browser.test.tsx` and cannot live anywhere else.
 *
 * What that means for reading these: every assertion below would still pass on
 * a console whose light palette was never written. They are about the control,
 * not about the theme.
 */

const priorTheme = document.documentElement.getAttribute('data-theme')

beforeEach(() => {
  localStorage.clear()
  document.documentElement.removeAttribute('data-theme')
})

afterEach(() => {
  localStorage.clear()
  if (priorTheme === null) document.documentElement.removeAttribute('data-theme')
  else document.documentElement.setAttribute('data-theme', priorTheme)
})

describe('the theme control', () => {
  it('starts on the system preference', () => {
    render(<ThemeControl />)
    expect(screen.getByRole('button')).toHaveAccessibleName(THEME_LABELS.system)
  })

  it('names its current state without being operated', () => {
    // The S-D2 defect this console records: an icon whose only label is a
    // tooltip is unlabelled for a screen reader and for a keyboard. Fails if
    // `aria-label` is dropped in favour of the `Tooltip` alone -- the tooltip
    // contributes nothing to the accessible name until it opens.
    localStorage.setItem(THEME_STORAGE_KEY, 'light')
    render(<ThemeControl />)
    expect(screen.getByRole('button')).toHaveAccessibleName(THEME_LABELS.light)
  })

  it('remembers an explicit choice and writes it to the document', async () => {
    render(<ThemeControl />)
    await userEvent.click(screen.getByRole('button'))

    // `system` -> `light` is the first step of the cycle.
    expect(localStorage.getItem(THEME_STORAGE_KEY)).toBe('light')
    expect(document.documentElement.getAttribute('data-theme')).toBe('light')
    expect(screen.getByRole('button')).toHaveAccessibleName(THEME_LABELS.light)
  })

  it('returns to the system preference after a full cycle', async () => {
    // Three clicks, not two. A two-state toggle cannot express "keep following
    // the desktop" -- it can only sample the preference once -- so the third
    // state has to be reachable, and the only way it is reachable is by
    // completing the cycle. Fails if `THEME_CHOICES` is reduced to two.
    render(<ThemeControl />)
    const button = screen.getByRole('button')
    for (let step = 0; step < THEME_CHOICES.length; step += 1) await userEvent.click(button)

    expect(localStorage.getItem(THEME_STORAGE_KEY)).toBe('system')
    expect(document.documentElement.getAttribute('data-theme')).toBe('system')
  })

  it('writes data-theme even for system', async () => {
    // Not cosmetic. `theme.css`'s `dark:` variant matches
    // `[data-theme='system']` under a dark media query, and an attribute that
    // is absent matches no selector at all -- so removing it here would make
    // every `dark:` utility inert for the default setting. Nothing writes one
    // today, which is exactly why this would be discovered late.
    render(<ThemeControl />)
    const button = screen.getByRole('button')
    for (let step = 0; step < THEME_CHOICES.length; step += 1) await userEvent.click(button)
    expect(document.documentElement.hasAttribute('data-theme')).toBe(true)
  })
})

describe('the stored choice', () => {
  it('falls back to system when the stored value is not one', () => {
    // `localStorage` is shared with whatever else this origin has ever run and
    // is editable by hand. A junk value must not reach `data-theme`, where it
    // would match none of the three rules and leave the console on whatever
    // `:root` says -- which happens to be right, and would be right by accident.
    localStorage.setItem(THEME_STORAGE_KEY, 'sepia')
    expect(readThemeChoice()).toBe('system')
  })

  it('cycles in a fixed order', () => {
    // The order is stated once, in `theme-choice.ts`, so the control and this
    // test cannot disagree about it. Asserted as a closed loop rather than as
    // three pairs: what matters is that every state is reachable from every
    // other, which a list of pairs can satisfy while still stranding one.
    const seen = new Set<string>()
    let choice: ThemeChoice = THEME_CHOICES[0]
    for (let step = 0; step < THEME_CHOICES.length; step += 1) {
      seen.add(choice)
      choice = nextThemeChoice(choice)
    }
    expect(seen.size).toBe(THEME_CHOICES.length)
    expect(choice).toBe(THEME_CHOICES[0])
  })
})
