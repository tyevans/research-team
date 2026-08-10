/** Declarations for two modules `scripts/eslint-a11y.test.ts` imports and that
 *  ship no types of their own.
 *
 *  `any` rather than a hand-written shape, deliberately. A guessed type for
 *  someone else's module is a second source of truth that nothing checks: it
 *  looks like safety and it is a comment with syntax. Both of these are used
 *  in exactly one file, which asserts on the *behaviour* it gets back rather
 *  than on the shape, so there is nothing here for a type to protect.
 *
 *  This file is inside `tsconfig.node.json`'s `include` and outside
 *  `tsconfig.json`'s, so the escape hatch reaches the build tooling only —
 *  application code cannot import either module and cannot see these
 *  declarations. */

/** No `@types/` package exists and the plugin is CommonJS with no bundled
 *  types. Delete this the day it ships them. */
declare module 'eslint-plugin-jsx-a11y' {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const plugin: any
  export default plugin
}

/** The repository's own eslint config, which is `.js` because that is what
 *  eslint loads without a build step. Typing it properly would mean typing
 *  every plugin in it. */
declare module '*/eslint.config.js' {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const config: any
  export default config
}
