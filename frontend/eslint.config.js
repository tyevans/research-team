import js from '@eslint/js'
import prettier from 'eslint-config-prettier'
import jsxA11y from 'eslint-plugin-jsx-a11y'
import reactHooks from 'eslint-plugin-react-hooks'
import globals from 'globals'
import tseslint from 'typescript-eslint'

/** Lint rules, chosen for the two mistakes this codebase can actually make.
 *
 * The layering is the architecture, and nothing but a rule enforces it — so
 * `no-restricted-imports` is the load-bearing entry here: the domain may not
 * import React or an adapter, and the application may not import a concrete
 * adapter. Everything else is the standard recommended set.
 */
export default tseslint.config(
  { ignores: ['dist', 'node_modules', 'coverage'] },

  js.configs.recommended,
  ...tseslint.configs.recommendedTypeChecked,
  {
    languageOptions: {
      globals: globals.browser,
      parserOptions: {
        projectService: {
          // The build tooling sits outside `tsconfig.json` on purpose — that
          // config is the browser's, and application code must not be able to
          // see `process` or `fs`. These files are still linted, against an
          // inferred program rather than a named project.
          //
          // Keep this list short. tseslint caps the default project at eight
          // files, and crossing the cap does not fail cleanly: it reports a
          // parse error against one file and then, because a blown default
          // project resolves no types at all, buries the cause under
          // `no-unsafe-*` errors somewhere else entirely. `scripts/` and
          // `.storybook/` each carry their own `tsconfig.json` instead —
          // `projectService` picks the nearest one per file — and anything
          // new should do the same rather than being added here.
          allowDefaultProject: ['eslint.config.js', 'vite.config.ts', 'scripts/*.mjs'],
        },
        tsconfigRootDir: import.meta.dirname,
      },
    },
    plugins: { 'react-hooks': reactHooks },
    rules: {
      ...reactHooks.configs.recommended.rules,
      '@typescript-eslint/no-unused-vars': ['error', { argsIgnorePattern: '^_' }],
      // Deliberate in several places: a fire-and-forget refresh whose failure is
      // already handled inside the promise.
      '@typescript-eslint/no-floating-promises': ['error', { ignoreVoid: true }],
      // Every repository port is async by contract. An implementation that
      // happens to have nothing to await — a fake, or a method that only maps —
      // is still correct, and rewriting it to return a bare promise would make
      // it read worse for no gain.
      '@typescript-eslint/require-await': 'off',
    },
  },

  /** Accessibility, checked rather than reviewed.
   *
   *  Scoped to `.tsx` because that is where JSX is; a `.ts` file cannot fail
   *  one of these rules and including it only slows the run down.
   *
   *  This is the recommended set unmodified. The alternative considered was
   *  `strict`, which adds rules about label nesting and anchor content that
   *  would have needed markup changes to satisfy — and markup changes are out
   *  of scope for a phase whose promise is that no pixel moves. `recommended`
   *  is also what a new contributor will expect, which is the whole reason for
   *  preferring a standard plugin to a house rule.
   *
   *  A caveat worth knowing: the plugin declares no support for eslint 10 and
   *  is pinned into this tree by an override — see the note in
   *  `package.json`. `eslint.config.test.ts` exists because of that: it feeds
   *  known-bad JSX through this config and asserts the rules actually fire, so
   *  a plugin that silently stops working is a failing test rather than a
   *  quietly clean lint. */
  {
    files: ['src/**/*.tsx'],
    ...jsxA11y.flatConfigs.recommended,
  },

  /** A class name built by interpolating into a template literal is a trap the
   *  formatter arms.
   *
   *  `prettier-plugin-tailwindcss@0.8.1` rewrites
   *  `` `artifact${present ? '' : ' artifact-missing'}` `` by deleting the
   *  leading space inside the conditional, producing the single class
   *  `artifactartifact-missing` and silently unstyling the element. It is a
   *  bug in the plugin, it corrupts on `npm run format` rather than on
   *  `format:check`, and the result typechecks and renders — so nothing else
   *  in the chain notices.
   *
   *  Two files hit it when the plugin landed: `course/Artifacts.tsx` and
   *  `course/StageRail.tsx`, the only two in the codebase not already using
   *  `clsx`. Both were converted. This rule is what stops the third.
   *
   *  Considered and rejected: dropping the plugin. It is the piece of
   *  anti-bikeshedding that makes class order mechanical rather than a matter
   *  of opinion on every review, and that value grows with every component
   *  moved onto utilities while this hazard stays a fixed two-line rule. The
   *  trade is worth making *with* a guard and would not be without one.
   *
   *  **The shape was measured, not guessed**, because the first version of
   *  this rule fired on every interpolated `className` and flagged eleven
   *  sites the plugin does not touch. Running each form through Prettier and
   *  diffing the output:
   *
   *      `k-${kind}`                          unchanged
   *      `rev k-${kind}`                      unchanged
   *      `base ${on ? 'a' : 'b'}`             unchanged
   *      `base ${kind} tail`                  unchanged
   *      'plain ' + (on ? 'a' : '')           unchanged
   *      `artifact${on ? '' : ' missing'}`    CORRUPTED
   *      `rail${short ? ' short' : ''}`       CORRUPTED
   *
   *  The discriminator is a **string literal beginning with a space inside the
   *  interpolation** — that leading space is the class separator, and it is
   *  the only thing the plugin eats. A template that separates its classes
   *  with static text is safe, because the plugin leaves the quasis alone.
   *
   *  So the rule matches exactly that and nothing else. Firing on the safe
   *  forms would have meant rewriting eleven working components in a phase
   *  that promises to change no rendered page, to guard against a bug they do
   *  not have — and a rule that flags mostly-false positives is one people
   *  learn to disable. `eslint-config.test.ts` asserts it fires on the
   *  corrupting form and stays quiet on the safe ones. */
  {
    files: ['src/**/*.tsx'],
    rules: {
      'no-restricted-syntax': [
        'error',
        {
          selector:
            'JSXAttribute[name.name="className"] > JSXExpressionContainer > TemplateLiteral Literal[value=/^ /]',
          message:
            'Build class names with clsx, not by interpolating a space-prefixed string into a template literal: prettier-plugin-tailwindcss deletes that leading space and silently merges two class names into one.',
        },
      ],
    },
  },

  /** The domain is pure. No framework, no transport, no browser API — if a rule
   *  here fires, something that belongs in an adapter has drifted inward. */
  {
    files: ['src/domain/**/*.ts'],
    rules: {
      'no-restricted-imports': [
        'error',
        {
          patterns: [
            {
              group: ['react', 'react-dom', 'zustand', '@tanstack/*'],
              message: 'The domain layer must not depend on a framework.',
            },
            {
              group: [
                '@infrastructure/*',
                '@presentation/*',
                '@app/*',
                '../../infrastructure/*',
                '../../presentation/*',
              ],
              message: 'The domain layer must not depend on an outer layer.',
            },
          ],
        },
      ],
    },
  },

  /** The application layer depends on ports, never on the adapter behind one.
   *  The composition root is the only module allowed to name an adapter. */
  {
    files: ['src/application/**/*.ts', 'src/application/**/*.tsx'],
    ignores: ['src/application/**/*.test.ts'],
    rules: {
      'no-restricted-imports': [
        'error',
        {
          patterns: [
            {
              group: ['@presentation/*'],
              message: 'The application layer must not depend on the UI.',
            },
          ],
        },
      ],
    },
  },

  /** The presentation layer talks to the HTTP adapter through a port, never by
   *  naming it.
   *
   *  Two instances were found by an audit rather than by the build, and both
   *  had the same shape: a component reaching past the port for something the
   *  adapter happened to export. `RunPanel` imported `ResearchDisabledError`
   *  from `http/project-repository.ts` and branched on it with `instanceof`,
   *  which handed a component a second reason to change — the repository's
   *  error taxonomy. `SessionTree` imported `summariesAsForest` from
   *  `http/mappers.ts`, a function that never touched a wire type and was
   *  simply filed in the wrong layer. Both are fixed; this rule is what stops
   *  the third, because an audit runs when somebody remembers and CI runs
   *  always.
   *
   *  Scoped to `@infrastructure/http/*` rather than to `@infrastructure/*`, and
   *  that narrowness is deliberate rather than a concession. It is the *store*
   *  presentation must not know about — how a thing is fetched, and in what
   *  shape it arrived. The other two infrastructure folders are not stores:
   *  `rendering/` is `common/content.tsx`'s markdown and diff engines, which
   *  are pure functions over strings with no transport and no state, and
   *  `storage/` supplies `InMemoryPreferenceStore` to tests as a test double.
   *  Banning those would produce two exceptions carrying no architectural
   *  meaning, and a rule mostly made of exceptions is one people stop reading.
   *  Widening this group is the right move on the day either of those grows a
   *  fetch.
   *
   *  No exception is needed today: with the two fixes in place, nothing under
   *  `src/presentation/` imports `@infrastructure/http/*` at all, so the rule
   *  ships green with an empty allow-list. `eslint-config.test.ts` proves it
   *  fires rather than trusting that. */
  {
    files: ['src/presentation/**/*.ts', 'src/presentation/**/*.tsx'],
    rules: {
      'no-restricted-imports': [
        'error',
        {
          patterns: [
            {
              group: ['@infrastructure/http/*', '../../infrastructure/http/*'],
              message:
                'The presentation layer must reach the HTTP adapter through a port, not by naming it. Put the type or function on the abstraction instead: an error the UI branches on belongs in @application/ports/errors.ts, and a fold over domain types belongs in domain/.',
            },
          ],
        },
      ],
    },
  },

  {
    files: ['**/*.test.ts', '**/*.test.tsx'],
    rules: {
      // Test doubles are partial on purpose; asserting on them is the point.
      '@typescript-eslint/no-unsafe-assignment': 'off',
      '@typescript-eslint/no-unsafe-member-access': 'off',
    },
  },

  /** The build tooling runs in Node, not in the browser, and is the one place
   *  in this repository allowed to say `process`. It is linted rather than
   *  ignored: a size gate that throws on its own bug reports a passing build.
   *
   *  These files sit outside `tsconfig.json` on purpose — that config is the
   *  browser's, and application code must not be able to see `process` or `fs`
   *  — so they are linted against an inferred program. For the `.js` among
   *  them that means no type information at all, and a type-aware rule asking
   *  for it errors rather than degrading, hence `disableTypeChecked`. */
  {
    files: ['vite.config.ts', 'scripts/**/*.ts'],
    languageOptions: { globals: globals.node },
  },
  {
    files: ['**/*.js', '**/*.mjs'],
    ...tseslint.configs.disableTypeChecked,
    languageOptions: { globals: globals.node },
  },

  /** Last, so it wins: formatting is Prettier's job and nothing here should
   *  have an opinion about it. Two tools disagreeing about a line break is a
   *  loop a developer has to break by hand, every time. */
  prettier,
)
