import js from '@eslint/js'
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
        projectService: true,
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

  /** The domain is pure. No framework, no transport, no browser API — if a rule
   *  here fires, something that belongs in an adapter has drifted inward. */
  {
    files: ['src/domain/**/*.ts'],
    rules: {
      'no-restricted-imports': [
        'error',
        {
          patterns: [
            { group: ['react', 'react-dom', 'zustand', '@tanstack/*'], message: 'The domain layer must not depend on a framework.' },
            { group: ['@infrastructure/*', '@presentation/*', '@app/*', '../../infrastructure/*', '../../presentation/*'], message: 'The domain layer must not depend on an outer layer.' },
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
            { group: ['@presentation/*'], message: 'The application layer must not depend on the UI.' },
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
)
