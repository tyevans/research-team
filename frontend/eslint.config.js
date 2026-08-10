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
