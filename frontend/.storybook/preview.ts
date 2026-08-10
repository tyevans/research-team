import type { Preview } from '@storybook/react-vite'

import { BREAKPOINTS } from '../src/presentation/layout/layout-tokens.ts'

// The whole stylesheet, exactly as `main.tsx` loads it. A workbench styled by a
// subset of the application's CSS is a workbench that lies: the console's
// appearance depends on `tokens.css` for its palette and on `structure.css`
// last of all to correct the files above it, so anything less than the real
// import chain renders components that look right nowhere else.
import '../src/styles/index.css'

const preview: Preview = {
  parameters: {
    // Dark, because the console is. Storybook's default is white and every
    // component here is drawn for `--bg: #0b0d10`; on white they are illegible
    // and, worse, they are illegible in a way that looks like a component bug.
    backgrounds: {
      options: { console: { name: 'console', value: '#0b0d10' } },
    },

    /** Viewports either side of the one boundary the layout changes shape at,
     *  derived from the same constants `Split` asks `matchMedia` about rather
     *  than written out here. A story called "below the breakpoint" that is
     *  actually above it is worse than no story, and hard-coded pixel widths
     *  beside a breakpoint that moves is how that happens.
     *
     *  These matter more than a convenience usually would: jsdom lays nothing
     *  out, so Storybook in a real browser is the only place the breakpoint
     *  handoff is exercised at all. */
    viewport: {
      options: {
        wide: {
          name: `wide (≥ ${String(BREAKPOINTS.wide)}px)`,
          styles: { width: `${String(BREAKPOINTS.wide + 100)}px`, height: '900px' },
          type: 'desktop',
        },
        narrow: {
          name: `narrow (< ${String(BREAKPOINTS.wide)}px)`,
          styles: { width: `${String(BREAKPOINTS.wide - 100)}px`, height: '900px' },
          type: 'desktop',
        },
        tight: {
          name: `tight (< ${String(BREAKPOINTS.tight)}px)`,
          styles: { width: `${String(BREAKPOINTS.tight - 40)}px`, height: '800px' },
          type: 'mobile',
        },
      },
    },
  },
  initialGlobals: { backgrounds: { value: 'console' } },
}

export default preview
