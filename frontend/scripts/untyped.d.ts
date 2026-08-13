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

/** The mutation harness. `.mjs` because it is a CLI in the same family as
 *  `check-size.mjs`, and its `classify` is imported by `mutate.test.ts`.
 *
 *  A real signature rather than `any`, unlike the two above: this is our
 *  module, the shape is four words wide, and the test asserts against the
 *  verdicts by name — so `any` here would let a renamed verdict typecheck and
 *  fail at run time.
 *
 *  It does duplicate the JSDoc in `mutate.mjs`, and the way to remove the
 *  duplication was tried and rejected: `allowJs` in `tsconfig.node.json` lets
 *  TypeScript read that JSDoc as the single source, but it also pulls every
 *  `.mjs` into the project, which collides with `allowDefaultProject` in
 *  `eslint.config.js` and makes the eslint config itself typed — surfacing an
 *  unrelated pre-existing mismatch in `eslint-config.test.ts`. Two lines of
 *  duplication is the cheaper of the two. */
/** The deletion check. Same reasoning as `mutate.mjs` below: our module, a
 *  narrow shape, and `check-deleted.test.ts` asserts on the two field names —
 *  so `any` would let `added`/`removed` be renamed and typecheck. */
declare module '*/check-deleted.mjs' {
  export const compareStylesheets: (
    present: string[],
    manifest: string[],
  ) => { added: string[]; removed: string[] }
}

declare module '*/mutate.mjs' {
  export const classify: (output: string) => {
    verdict: 'killed' | 'survived' | 'unparsed' | 'unknown'
    killedBy: string[]
  }
}
