import type { Preview } from '@storybook/react-vite'

import { BREAKPOINTS } from '../src/presentation/layout/layout-tokens.ts'
import { OverlayHost } from '../src/presentation/layout/OverlayHost.tsx'

// The whole stylesheet, exactly as `main.tsx` loads it. A workbench styled by a
// subset of the application's CSS is a workbench that lies: the console's
// appearance depends on `tokens.css` for its palette and on `structure.css`
// last of all to correct the files above it, so anything less than the real
// import chain renders components that look right nowhere else.
import '../src/styles/index.css'

const preview: Preview = {
  /** An `OverlayHost` around every story, and the reason it is here rather
   *  than in the stories that need one.
   *
   * A `Tooltip`, `Popover` or `Menu` with no host in scope renders its trigger
   * and **no content at all** — argued in `Tooltip.tsx`, and a real behaviour
   * rather than an oversight. In a workbench that means the trigger appears,
   * the explanation silently does not, and the one thing only a browser can
   * check (does it flip against the viewport, does it paint above a drawer)
   * cannot be checked at all.
   *
   * Per-story was the previous rule and it failed six times out of seven:
   * `TopicQueue.stories.tsx` mounted a host, and the stories for `GateReview`,
   * `WorkerList`, `RunPanel`, `Artifacts`, `AutonomyPanel` and `StageRail` did
   * not. That ratio is the argument. The rule asks an author to know a thing
   * about a component two files away, gives no signal when they do not, and
   * the story still renders — so nothing ever says it is wrong.
   *
   * Two costs, both real:
   *
   * - A story that mounts a `Shell` now has two hosts, since `Shell` mounts
   *   its own. The inner one wins — `useLayer` reads the nearest `HostContext`
   *   — so layers register with the shell's host exactly as they do in the
   *   application, and the outer one stays empty. Harmless, but it means
   *   `Shell.stories.tsx` is not testing quite what it looks like it is.
   * - Through `setProjectAnnotations` (`vitest.setup.ts`) this wraps every
   *   test that composes a story, not only the stories. That is deliberate:
   *   the workbench and the suite disagreeing about what a component renders
   *   is the failure this whole change is about.
   */
  decorators: [
    (Story) => (
      <OverlayHost>
        <Story />
      </OverlayHost>
    ),
  ],

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
