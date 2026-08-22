import { readFileSync } from 'node:fs'
import { fileURLToPath, URL } from 'node:url'

import ts from 'typescript'
import { describe, expect, it } from 'vitest'

import viteConfig from '../vite.config.ts'

/** The path aliases are declared twice — once for the type checker, once for
 *  the bundler — because the two tools read different files and neither can be
 *  told to consult the other without a plugin whose own dependency is
 *  unmaintained.
 *
 *  Two declarations of one fact is a defect this test downgrades to a caught
 *  one. Drift here is quiet and unpleasant: `tsc` resolves an alias the bundler
 *  does not, so the code type-checks, lints, and then fails at run time with a
 *  bare import error — or worse, resolves to a stale second copy of a module
 *  and the store silently has two instances. */
const read = (file: string) => {
  const path = fileURLToPath(new URL(`../${file}`, import.meta.url))
  // tsconfig.json is JSON with comments; TypeScript's own parser is already a
  // dependency and is the only thing guaranteed to read it the way tsc does.
  const parsed = ts.parseConfigFileTextToJson(path, readFileSync(path, 'utf8'))
  expect(parsed.error, `${file} does not parse`).toBeUndefined()
  return parsed.config as { compilerOptions?: { paths?: Record<string, string[]> } }
}

describe('the path aliases', () => {
  const tsPaths = read('tsconfig.json').compilerOptions?.paths ?? {}
  const viteAliases = (viteConfig as { resolve?: { alias?: Record<string, string> } }).resolve
    ?.alias

  it('are declared for the same set of names in both configs', () => {
    const fromTs = Object.keys(tsPaths)
      .map((key) => key.replace(/\/\*$/, ''))
      .sort()
    expect(Object.keys(viteAliases ?? {}).sort()).toEqual(fromTs)
  })

  it('point at the same directory in both configs', () => {
    for (const [pattern, targets] of Object.entries(tsPaths)) {
      const name = pattern.replace(/\/\*$/, '')
      // "src/domain/*" and an absolute path ending "/src/domain" are the same
      // directory said two ways.
      const expected = targets[0]?.replace(/\/\*$/, '').replace(/^\.\//, '')
      expect(viteAliases?.[name], `alias ${name}`).toMatch(new RegExp(`/${expected}$`))
    }
  })

  it('are all actually used, so a stale one cannot sit here unnoticed', () => {
    expect(Object.keys(tsPaths).length).toBeGreaterThan(0)
  })
})

describe('the build target', () => {
  it('matches what the type checker is told to produce', () => {
    // If these diverge, tsc accepts syntax esbuild will down-level (or not),
    // and the thing shipped is not the thing checked.
    const target = read('tsconfig.json').compilerOptions as { target?: string } | undefined
    const build = (viteConfig as { build?: { target?: string } }).build
    expect(build?.target?.toLowerCase()).toBe(target?.target?.toLowerCase())
  })
})

describe('output filenames', () => {
  /** No content hash in any emitted filename.
   *
   *  A hash reappearing is silent: a hashed build serves perfectly well, and
   *  the only symptoms are downstream and delayed. `scripts/check-size.mjs`
   *  buckets by filename and its keys are these names, so a hash empties every
   *  bucket; and `_RevalidatedStatics` in `app.py` sends `no-cache` *because*
   *  these names are stable, which becomes a pure download tax the moment they
   *  are not.
   *
   *  Asserted against `vite.config.ts` rather than against the built output.
   *  The Python suite used to check this by listing
   *  `web/static/assets` -- which stopped being possible when the built console
   *  was untracked, since that directory does not exist until someone builds.
   *  The config is the source of truth anyway: a build can only carry a hash
   *  the config asked for.
   */
  it('carries no content hash', () => {
    const output = viteConfig.build?.rollupOptions?.output as Record<string, string>

    for (const key of ['entryFileNames', 'chunkFileNames', 'assetFileNames']) {
      expect(output[key], `${key} must not interpolate a hash`).not.toContain('[hash]')
    }
  })
})
