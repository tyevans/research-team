import type { StorybookConfig } from '@storybook/react-vite'

/** The workbench.
 *
 * Storybook's job here is the one §5 of the component-system spec gives it:
 * making the set of components that already exist answerable at a glance. Four
 * free-text filters, three fold implementations and three empty-state wordings
 * for one situation all got written because finding out whether a thing
 * already existed meant grepping for a name you had to guess first.
 *
 * Deliberately thin. No addons are installed: `addon-a11y` is worth having and
 * belongs with the components it would check, and `addon-vitest` needs vitest
 * browser mode and a Chromium download, which is phase 6's cost to pay rather
 * than this one's. Stories reach `vitest` through `composeStories` instead, so
 * they run inside the `app` project that already exists and CI gains no job.
 *
 * `storybook build` is deliberately *not* in `npm run verify`. It roughly
 * doubles frontend CI time to catch a story that fails to compile, and
 * `typecheck` already catches that -- stories are TypeScript inside `src/`.
 * What that leaves unchecked is a story that compiles and throws when
 * rendered; the answer to that is a test importing it, not a build step.
 */
const config: StorybookConfig = {
  stories: ['../src/**/*.stories.tsx'],
  addons: [],
  framework: {
    name: '@storybook/react-vite',
    options: {},
  },
  // `vite.config.ts` is picked up automatically, which is what puts the alias
  // map, the React plugin and Tailwind in front of a story without any of it
  // being restated here. Restating it is how the workbench and the application
  // come to disagree about what a component renders like.
  core: { disableTelemetry: true },
}

export default config
