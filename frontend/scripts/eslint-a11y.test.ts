import { ESLint } from 'eslint'
import jsxA11y from 'eslint-plugin-jsx-a11y'
import { describe, expect, it } from 'vitest'

import eslintConfig from '../eslint.config.js'

/** That the accessibility rules are switched on, and that they still fire.
 *
 * This file exists because of one specific hazard, not for completeness.
 * `eslint-plugin-jsx-a11y@6.10.2` is the latest published version and it
 * declares `eslint@^3 || … || ^9`; this project runs eslint 10, and the plugin
 * is held in the tree by an `overrides` entry in `package.json`. It works
 * today — `npm run lint` finds seventeen real problems with it — but it is
 * running outside the range its author supports, and the failure mode that
 * costs the most is the quiet one: a plugin that loads, registers nothing, and
 * turns `npm run lint` green while checking nothing.
 *
 * A lint gate that has stopped checking looks exactly like a codebase with no
 * problems. So the two halves are asserted separately: that our config enables
 * the rules for the files we care about, and that the rules actually report on
 * known-bad JSX when this version of eslint runs them.
 *
 * It lives in `scripts/` with the build tooling rather than in `src/` because
 * it reads a config file off disk and needs a real Node — the same reason
 * `vite.config.ts` puts the `build` vitest project there.
 *
 * Both tests were proved red: the first by removing the `jsxA11y` block from
 * `eslint.config.js`, the second by pointing the inline config at an empty
 * `rules` object.
 */

/** Deliberately bad: a div that can be clicked and cannot be reached any other
 *  way. This is the shape of L-F37's toast and of the revision header fixed in
 *  the same commit as this file, so if `jsx-a11y` ever stops reporting it, the
 *  rules that matter most here are the ones that went quiet. */
const KNOWN_BAD = 'export const Bad = () => <div onClick={() => {}}>dismiss</div>\n'

describe('the accessibility gate', () => {
  it('is enabled for the presentation layer', async () => {
    const eslint = new ESLint({ overrideConfigFile: true, baseConfig: eslintConfig })
    const config = await eslint.calculateConfigForFile('src/presentation/common/Drawer.tsx')

    // Severity 2 rather than merely "present": `--max-warnings 0` means a
    // warning would also fail CI today, but a rule demoted to `warn` is one
    // `--max-warnings` change away from being advisory, and these are not.
    expect(config.rules?.['jsx-a11y/click-events-have-key-events']?.[0]).toBe(2)
    expect(config.rules?.['jsx-a11y/no-static-element-interactions']?.[0]).toBe(2)
    expect(config.rules?.['jsx-a11y/interactive-supports-focus']?.[0]).toBe(2)
  })

  it('is not applied to files that cannot contain JSX', async () => {
    const eslint = new ESLint({ overrideConfigFile: true, baseConfig: eslintConfig })
    const config = await eslint.calculateConfigForFile('src/domain/session/event-kind.ts')

    // Scoping is a performance choice, not a correctness one, and it is
    // asserted so that a future widening is a deliberate edit rather than a
    // side effect of moving the block.
    expect(config.rules?.['jsx-a11y/click-events-have-key-events']).toBeUndefined()
  })

  it('still reports on this version of eslint', async () => {
    /** The plugin's recommended set alone, with no parser options and no type
     *  information — the narrowest thing that answers "does this plugin run
     *  here at all", and the assertion that goes red if a future eslint drops
     *  an API the plugin still uses. */
    const eslint = new ESLint({
      overrideConfigFile: true,
      baseConfig: [
        {
          files: ['**/*.tsx'],
          languageOptions: {
            parserOptions: {
              ecmaFeatures: { jsx: true },
              ecmaVersion: 'latest',
              sourceType: 'module',
            },
          },
          ...jsxA11y.flatConfigs.recommended,
        },
      ],
    })

    const [result] = await eslint.lintText(KNOWN_BAD, { filePath: 'probe.tsx' })
    const ruleIds = result?.messages.map((message) => message.ruleId) ?? []

    expect(ruleIds).toContain('jsx-a11y/click-events-have-key-events')
    expect(ruleIds).toContain('jsx-a11y/no-static-element-interactions')
  })
})
