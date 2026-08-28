import type { Meta, StoryObj } from '@storybook/react-vite'

import { THEME_CHOICES, THEME_LABELS } from './theme-choice.ts'
import { ThemeControl, ThemeGlyph } from './ThemeControl.tsx'

/** The way in to light mode, and the three glyphs it cycles through.
 *
 * **Use the Theme item in the toolbar while reading this page.** That switch
 * is what this whole change is for, and it is the only place a person can look
 * at both palettes; `a11y.browser.test.tsx` proves the contrast arithmetic in
 * both schemes and can say nothing at all about whether either one looks
 * right.
 *
 * Two things to check here that no test asserts:
 *
 * - **The three glyphs are one family.** They share a circle of the same
 *   radius, so the control does not change size or optical weight as it cycles
 *   — a bar that twitches when you press a button in it reads as a bug. The
 *   sun's rays and the moon's crescent are the only things that differ.
 * - **The half-filled circle reads as "follow the device"** rather than as an
 *   unrelated third symbol. It is deliberately a mixture of the other two. If
 *   it reads as "half brightness" instead, it is the wrong glyph.
 *
 * The states are rendered side by side rather than driven, because the live
 * control shows one at a time and the comparison is the point. `Live` below is
 * the real thing.
 */
const meta: Meta = {
  title: 'shell/ThemeControl',
}

export default meta

type Story = StoryObj

/** All three glyphs at once, which is the only arrangement in which the family
 *  argument above can be checked. The live control can never show two. */
export const EveryGlyph: Story = {
  render: () => (
    <div
      style={{
        display: 'flex',
        gap: 'var(--space-4)',
        alignItems: 'center',
        padding: 'var(--space-3)',
      }}
    >
      {THEME_CHOICES.map((choice) => (
        <div
          key={choice}
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 'var(--space-2)',
            color: 'var(--fg-dim)',
            fontSize: 'var(--t-sm)',
          }}
        >
          <span style={{ display: 'inline-flex', color: 'var(--fg)' }}>
            <ThemeGlyph choice={choice} />
          </span>
          {THEME_LABELS[choice].replace('Colour theme: ', '')}
        </div>
      ))}
    </div>
  ),
}

/** The real control, which changes the *whole preview document* when pressed.
 *
 *  That is not a story artefact -- it is the component doing exactly what it
 *  does in the console, because `color-scheme` and `light-dark()` resolve
 *  against the element that declares them and `tokens.css` declares them on
 *  `:root`. A version of this that only retinted its own wrapper would be a
 *  version that does not work. Pressing it also overrides the toolbar until
 *  the toolbar is used again. */
export const Live: Story = {
  render: () => (
    <div style={{ padding: 'var(--space-3)' }}>
      <ThemeControl />
    </div>
  ),
}
