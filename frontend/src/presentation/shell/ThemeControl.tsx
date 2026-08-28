import { useState } from 'react'

import { Tooltip } from '../common/Tooltip.tsx'
import { nextThemeChoice, THEME_LABELS, type ThemeChoice } from './theme-choice.ts'
import { applyThemeChoice, readThemeChoice, writeThemeChoice } from './theme-storage.ts'

/** The way in to light mode, from every route.
 *
 * In the chrome rather than on a settings page, by `AutonomyLock`'s test for
 * what belongs in that bar -- *is this a property of the page you happen to be
 * on?* A theme is not; it is a property of the reader. It sits beside the lock
 * for the same reason the lock sits where it does.
 *
 * **A cycling button rather than a menu of three**, and the trade is real. A
 * menu shows all three states at once and names the current one without being
 * operated; a cycle hides two of them behind a click. What the cycle buys is
 * that the whole control is one glyph in a bar that is already dense, and that
 * changing the theme is one keystroke rather than four. The cost is paid back
 * in the label: the button's accessible name states the *current* state in a
 * full sentence (`THEME_LABELS`), so a screen reader and a keyboard both get
 * the state without operating anything, and the tooltip carries the same
 * sentence. That is `AutonomyLock`'s arrangement exactly, and it is the answer
 * to the unlabelled-icon defect (S-D2) this console records.
 *
 * If a fourth state ever arrives -- a high-contrast palette is the obvious
 * candidate -- the cycle stops being defensible and this becomes the menu.
 *
 * **`useState` with a lazy initialiser rather than `useMemo`.** CLAUDE.md
 * records why: React may discard a memoised value on a remount, and a theme
 * that resets to `system` when a parent re-keys is a setting that looks like it
 * did not save.
 */
export const ThemeControl = () => {
  const [choice, setChoice] = useState<ThemeChoice>(readThemeChoice)

  const advance = () => {
    const next = nextThemeChoice(choice)
    setChoice(next)
    writeThemeChoice(next)
    applyThemeChoice(next)
  }

  return (
    <Tooltip asChild explanation={`${THEME_LABELS[choice]}. Activate to change.`}>
      <button
        type="button"
        className="btn btn-ghost btn-sm"
        aria-label={THEME_LABELS[choice]}
        onClick={advance}
      >
        <ThemeGlyph choice={choice} />
      </button>
    </Tooltip>
  )
}

/** Drawn rather than written, for `AutonomyLock`'s reason: the console has no
 *  icon set and a glyph from one would be the only one. `currentColor` so it
 *  inherits `.btn`'s hover and disabled colours instead of declaring its own,
 *  and `aria-hidden` because the button already carries the sentence.
 *
 *  Three glyphs on one geometry -- a circle of the same radius in each -- so
 *  the control does not change size or optical weight as it cycles. `system`
 *  is the half-filled circle, which is the established convention for "follow
 *  the device" and reads as a mixture of the other two rather than as a third
 *  unrelated symbol.
 *
 *  Exported, which the rest of this file's glyphs are not: `ThemeControl.stories.tsx`
 *  puts the three side by side, and that comparison is the only way to judge
 *  whether they read as a family. The alternative was a story that reimplements
 *  the SVG, which is a second copy that drifts, or one that seeds `localStorage`
 *  during render to force each state, which is a side effect in render. Widening
 *  the module's surface by one presentational component is the cheapest of the
 *  three. */
export const ThemeGlyph = ({ choice }: { choice: ThemeChoice }) => (
  <svg
    width="12"
    height="12"
    viewBox="0 0 12 12"
    fill="none"
    stroke="currentColor"
    strokeWidth="1.2"
    aria-hidden="true"
  >
    {choice === 'light' ? (
      <>
        <circle cx="6" cy="6" r="2.6" />
        {[0, 45, 90, 135, 180, 225, 270, 315].map((angle) => (
          <line
            key={angle}
            x1="6"
            y1="1.2"
            x2="6"
            y2="2.4"
            transform={`rotate(${String(angle)} 6 6)`}
          />
        ))}
      </>
    ) : choice === 'dark' ? (
      <path d="M8.6 7.9A3.9 3.9 0 0 1 4.1 3.4a3.9 3.9 0 1 0 4.5 4.5Z" />
    ) : (
      <>
        <circle cx="6" cy="6" r="4.2" />
        {/* Filled rather than stroked, so "half" reads at 12px: two 1.2px
            strokes meeting on the diameter would close the gap entirely. */}
        <path d="M6 1.8a4.2 4.2 0 0 1 0 8.4Z" fill="currentColor" stroke="none" />
      </>
    )}
  </svg>
)
