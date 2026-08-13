import { ESLint } from 'eslint'
import jsxA11y from 'eslint-plugin-jsx-a11y'
import { describe, expect, it } from 'vitest'

import eslintConfig from '../eslint.config.js'

/** That this repository's own lint rules are switched on, and that they fire.
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

/** The guard against the formatter corrupting a class name.
 *
 * `prettier-plugin-tailwindcss@0.8.1` deletes the leading space inside an
 * interpolation, turning `` `a${c ? ' b' : ''}` `` into one merged class. It
 * corrupts on `format`, not on `format:check`, and the damage typechecks and
 * renders — so this rule is the only thing in the chain that can see it.
 *
 * The negative cases matter as much as the positive one: a rule that fires on
 * every template literal would push people back to string concatenation, which
 * has the same hazard and no rule watching it.
 *
 * Proved red by deleting the `no-restricted-syntax` block from
 * `eslint.config.js`; proved not-overreaching by checking the two safe forms
 * stay clean with the block in place. */
describe('the class-name guard', () => {
  /** Linted against the *real* config, unlike the a11y probe above, because
   *  this rule is ours rather than a plugin's and "is it wired up" and "does
   *  it fire" are the same question for it.
   *
   *  The file path has to be one that already exists. `projectService` resolves
   *  every `src/**` file through `tsconfig.json`, and an invented path is a
   *  fatal parse error rather than a lint result — which is how this test first
   *  failed, reporting `[null]`. The text is linted, the path is only used to
   *  choose a config and a TS program, and the rule under test is syntactic, so
   *  borrowing a real path costs nothing. Other rules will report on this text;
   *  the assertions look only for this one. */
  /** The rule's real options, lifted out of the real config, then run without
   *  a type-aware program.
   *
   *  The obvious version — `new ESLint({ baseConfig: eslintConfig })` and lint
   *  the text — builds a TypeScript program over the whole of `src/` on the
   *  first call. That passed when run alone and timed out at five seconds
   *  inside the full suite, which looked like flakiness and was not: it failed
   *  in a direction load explains completely. Memoizing the instance fixed
   *  calls two through six and not the first, because the cost is the program
   *  and there is exactly one of those to build.
   *
   *  Raising the timeout would have hidden it rather than fixed it. Reading
   *  the options out of the real config and handing them to a parser with no
   *  project keeps the thing that matters — the selector and severity under
   *  test are the ones the repository actually ships, not a copy — and costs
   *  milliseconds. `calculateConfigForFile` resolves config without a program,
   *  so it is cheap for the same reason. */
  const options = async () => {
    const resolver = new ESLint({ overrideConfigFile: true, baseConfig: eslintConfig })
    const config = await resolver.calculateConfigForFile('src/presentation/common/Drawer.tsx')
    return config.rules?.['no-restricted-syntax'] as [number, ...unknown[]] | undefined
  }

  const lint = async (source: string) => {
    const [severity, ...restrictions] = (await options()) ?? []
    // A missing rule must not read as a clean lint. Without this the negative
    // assertions below would all pass against a config that had lost the rule
    // entirely, which is the exact failure this file exists to catch.
    expect(severity).toBe(2)

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
          rules: { 'no-restricted-syntax': ['error', ...restrictions] },
        },
      ],
    })
    const [result] = await eslint.lintText(source, { filePath: 'probe.tsx' })
    const messages = result?.messages ?? []

    // A probe that does not parse reports one fatal message with a `null`
    // ruleId, and every "this should not fire" assertion then passes for the
    // wrong reason. That happened here, and the negative half of this suite
    // was green against a deliberately broken rule until it was found. Failing
    // on a fatal message turns a silently useless test into a loud one.
    const fatal = messages.find((message) => message.fatal)
    if (fatal) throw new Error(`probe did not parse: ${fatal.message}`)

    return messages.map((message) => message.ruleId)
  }

  it('rejects a class name interpolated into a template literal', async () => {
    // The exact shape that shipped in `Artifacts.tsx` and would have been
    // corrupted by the next `npm run format`.
    expect(
      await lint("export const B = () => <li className={`artifact${1 ? '' : ' gone'}`} />\n"),
    ).toContain('no-restricted-syntax')
  })

  it('allows the interpolated forms Prettier leaves alone', async () => {
    // Measured rather than assumed -- each of these was run through Prettier
    // and came back unchanged. They are here because the first version of the
    // rule flagged all of them, which would have meant rewriting eleven
    // working components to guard against a bug they do not have.
    const safe = [
      'const B = () => <li className={`k-${x}`} />',
      'const B = () => <li className={`rev k-${x}`} />',
      "const B = () => <li className={`base ${x ? 'a' : 'b'}`} />",
      'const B = () => <li className={`base ${x} tail`} />',
    ]
    for (const source of safe) {
      // Plain JavaScript, deliberately. The first version of this test
      // declared `x` with `declare const x: string`, which the probe's parser
      // — the default one, since the point of this config is to avoid a
      // TypeScript program — cannot parse. Every probe was a fatal parse
      // error, `messages` held one entry with a `null` ruleId, and
      // `.not.toContain('no-restricted-syntax')` passed for a reason that had
      // nothing to do with the rule: **the whole test was green against a
      // deliberately widened selector.** `lint` now fails loudly on a parse
      // error so this cannot recur silently.
      expect(await lint(`const x = 'a'\n${source}\n`)).not.toContain('no-restricted-syntax')
    }
  })

  it('fires on the other corrupting shape, a space-prefixed truthy branch', async () => {
    // `rail${short ? ' short' : ''}` -- the same bug from the other side, and
    // the shape `StageRail.tsx` had.
    expect(
      await lint("export const B = () => <li className={`rail${1 ? ' short' : ''}`} />\n"),
    ).toContain('no-restricted-syntax')
  })

  it('allows clsx, which is the answer the message points at', async () => {
    expect(
      await lint(
        "import clsx from 'clsx'\nexport const B = () => <li className={clsx('artifact', false && 'gone')} />\n",
      ),
    ).not.toContain('no-restricted-syntax')
  })
})

/** The layering guard over presentation's imports.
 *
 * Two violations were found by a human audit rather than by CI — `RunPanel`
 * branching on `ResearchDisabledError` from `http/project-repository.ts`, and
 * `SessionTree` importing `summariesAsForest` from `http/mappers.ts`. Both are
 * fixed, which means the repository now has no instance of the mistake, which
 * means `npm run lint` is green whether or not this rule exists. That is
 * exactly the situation the a11y tests above were written for: a gate with
 * nothing to catch is indistinguishable from a gate that is switched off. So
 * the positive case here is a synthetic import, not a real file.
 *
 * The negative cases are the load-bearing half. `@infrastructure/rendering/*`
 * and `@infrastructure/storage/*` are imported by presentation today and are
 * meant to be, so a rule that grew to `@infrastructure/*` would fail the build
 * on `common/content.tsx` — and these assertions are what turn that widening
 * into a deliberate edit with two exceptions written down, rather than a
 * surprise.
 *
 * Proved red by deleting the `src/presentation/**` block from
 * `eslint.config.js`: the first test then reported no `no-restricted-imports`
 * and failed on the severity check in `lint` below. */
describe('the presentation-layer import guard', () => {
  /** The real rule's options, run without a type-aware program — the same
   *  technique and the same reason as the class-name guard above: building a
   *  TypeScript program over `src/` costs seconds on the first call and this
   *  rule is purely syntactic. */
  const options = async (path: string) => {
    const resolver = new ESLint({ overrideConfigFile: true, baseConfig: eslintConfig })
    const config = await resolver.calculateConfigForFile(path)
    return config.rules?.['no-restricted-imports'] as [number, ...unknown[]] | undefined
  }

  const lint = async (source: string) => {
    const [severity, ...restrictions] =
      (await options('src/presentation/course/RunPanel.tsx')) ?? []
    // A missing rule must not read as a clean lint — without this, every
    // negative assertion below passes against a config that lost the rule.
    expect(severity).toBe(2)

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
          rules: { 'no-restricted-imports': ['error', ...restrictions] },
        },
      ],
    })
    const [result] = await eslint.lintText(source, { filePath: 'probe.tsx' })
    const messages = result?.messages ?? []

    const fatal = messages.find((message) => message.fatal)
    if (fatal) throw new Error(`probe did not parse: ${fatal.message}`)

    return messages
  }

  it('rejects a presentation file naming the HTTP adapter', async () => {
    // The shape `RunPanel.tsx` actually had before this change.
    const messages = await lint(
      "import { ResearchDisabledError } from '@infrastructure/http/project-repository.ts'\nexport const B = () => null\n",
    )

    expect(messages.map((message) => message.ruleId)).toContain('no-restricted-imports')
    // The message is asserted, not just the rule id, because a guard whose
    // text does not say where the thing belongs instead gets satisfied by
    // deleting the import and inlining the concept.
    expect(messages[0]?.message).toContain('@application/ports/errors.ts')
  })

  it('rejects the relative spelling of the same import', async () => {
    // `@infrastructure/*` is an alias, and a path alias is a convention rather
    // than a boundary — nothing stops `../../infrastructure/http/mappers.ts`.
    // The domain block above already guards both spellings; so does this one.
    expect(
      (
        await lint(
          "import { summariesAsForest } from '../../infrastructure/http/mappers.ts'\nexport const B = () => null\n",
        )
      ).map((message) => message.ruleId),
    ).toContain('no-restricted-imports')
  })

  it('allows the infrastructure presentation is meant to use', async () => {
    // Neither of these is a store. `rendering/` is pure functions over strings
    // -- the markdown and diff engines behind `common/content.tsx` -- and
    // `storage/` supplies a test double. Both are imported by presentation
    // today, so this assertion fails the moment someone widens the group to
    // `@infrastructure/*` without writing the exceptions down.
    const allowed = [
      "import { renderMarkdown } from '@infrastructure/rendering/markdown.ts'",
      "import { InMemoryPreferenceStore } from '@infrastructure/storage/preference-store.ts'",
    ]
    for (const source of allowed) {
      expect(
        (await lint(`${source}\nexport const B = () => null\n`)).map((m) => m.ruleId),
      ).not.toContain('no-restricted-imports')
    }
  })

  it('is not applied outside the presentation layer', async () => {
    // The composition root names adapters on purpose; that is its whole job.
    const config = await options('src/app/container.ts')
    const patterns =
      (config?.[1] as { patterns?: { group: string[] }[] } | undefined)?.patterns ?? []

    expect(patterns.some((p) => p.group.includes('@infrastructure/http/*'))).toBe(false)
  })
})
