#!/usr/bin/env node
/**
 * Mutation testing, by hand, for the tests that claim to prove something.
 *
 * This repository's convention is that a test is proved red against a
 * deliberately broken implementation before it is trusted green. Doing that by
 * editing a file, running vitest, and editing it back is fine for one
 * assertion and unreliable for twenty — the edit gets left in, or the run gets
 * misread. This does it mechanically: apply, run, restore, classify.
 *
 * It exists because of what it found. Across four rounds it caught five tests
 * that passed for a reason unrelated to what they asserted — a guard whose
 * absence jsdom could not observe, a role query that matched an element with
 * no role either way, a regex that matched a different element, a rule that
 * was correct and unapplied, and a probe that never parsed. Reading those
 * tests did not reveal any of it.
 *
 * Deliberately **not** wired into `npm run verify`. It is slow, it needs a
 * mutation set written by somebody who knows what the code is supposed to do,
 * and a stale mutation set fails a build for no reason. It is a tool for the
 * person writing the tests, run once, at the moment the tests are written.
 *
 *     node scripts/mutate.mjs mutants.json
 *
 * where `mutants.json` is
 *
 *     {
 *       "target": ["src/presentation/entity"],
 *       "mutants": [
 *         { "label": "…", "file": "src/…/x.ts", "find": "…", "replace": "…" }
 *       ]
 *     }
 *
 * `find` is a literal string, not a pattern: a mutation you cannot read back
 * out of the diff is one you cannot trust.
 */
import { spawnSync } from 'node:child_process'
import { readFileSync, writeFileSync } from 'node:fs'
import process from 'node:process'

/**
 * What a vitest run says about a mutant.
 *
 * **The distinction that matters is `unparsed`.** A mutation that produces a
 * syntax error makes vitest fail at *file* level, which emits no
 * `FAIL … > test name` line — so a parser counting per-test failures sees zero
 * and concludes the mutant survived. That is the worst possible answer: it is
 * not merely wrong, it is wrong in the direction that sends you hunting for
 * assertions which already exist. It happened twice before this function was
 * written, and it is the reason the whole classification is a pure function
 * with tests of its own rather than three lines inlined in the loop.
 *
 * @param {string} output combined stdout and stderr of the vitest run
 * @returns {{verdict: 'killed'|'survived'|'unparsed'|'unknown', killedBy: string[]}}
 */
export const classify = (output) => {
  if (
    output.includes('Failed Suites') ||
    output.includes('Unexpected token') ||
    output.includes('Transform failed') ||
    output.includes('Expression expected')
  ) {
    return { verdict: 'unparsed', killedBy: [] }
  }

  const killedBy = [
    ...new Set(
      output
        .split('\n')
        .filter((line) => line.includes(' FAIL ') && line.includes(' > '))
        .map((line) => line.split(' > ').slice(1).join(' > ').trim()),
    ),
  ].sort()

  if (killedBy.length > 0) return { verdict: 'killed', killedBy }
  // "N passed" with no failures is the only shape that may be read as
  // survival, and only after the unparsed check above has run.
  if (/Tests\s+\d+ passed/.test(output)) return { verdict: 'survived', killedBy: [] }
  return { verdict: 'unknown', killedBy: [] }
}

const run = (target) =>
  spawnSync('npx', ['vitest', 'run', '--project', 'app', ...target], {
    encoding: 'utf8',
  })

const main = () => {
  const specPath = process.argv[2]
  if (!specPath) {
    console.error('usage: node scripts/mutate.mjs <mutants.json>')
    process.exit(2)
  }

  const spec = JSON.parse(readFileSync(specPath, 'utf8'))
  const originals = new Map()
  for (const mutant of spec.mutants) {
    if (!originals.has(mutant.file)) originals.set(mutant.file, readFileSync(mutant.file, 'utf8'))
  }

  const restore = () => {
    for (const [file, text] of originals) writeFileSync(file, text)
  }
  // A crash must not leave a mutated working tree behind, which is the failure
  // mode that turns a testing tool into a lost afternoon.
  process.on('exit', restore)
  process.on('SIGINT', () => process.exit(130))

  let survived = 0
  let inconclusive = 0

  for (const mutant of spec.mutants) {
    const original = originals.get(mutant.file)
    if (!original.includes(mutant.find)) {
      // An anchor that no longer matches means the mutation was never applied,
      // and a run that did not mutate anything proves nothing. Loud, because
      // silently skipping is how a mutation set rots into decoration.
      console.log(`\n### ${mutant.label}\n  !! ANCHOR NOT FOUND — mutation not applied`)
      inconclusive += 1
      continue
    }

    writeFileSync(mutant.file, original.replace(mutant.find, mutant.replace))
    const result = run(spec.target)
    writeFileSync(mutant.file, original)

    const { verdict, killedBy } = classify(`${result.stdout ?? ''}${result.stderr ?? ''}`)
    console.log(`\n### ${mutant.label}`)
    if (verdict === 'killed') {
      console.log(killedBy.map((name) => `  RED: ${name}`).join('\n'))
    } else if (verdict === 'unparsed') {
      console.log('  !! MUTANT DID NOT COMPILE — inconclusive, rewrite the mutation')
      inconclusive += 1
    } else if (verdict === 'survived') {
      console.log('  !!! SURVIVED — no test asserts this')
      survived += 1
    } else {
      console.log('  !! could not classify the run')
      inconclusive += 1
    }
  }

  console.log(
    `\n${String(spec.mutants.length)} mutants: ${String(spec.mutants.length - survived - inconclusive)} killed, ${String(survived)} survived, ${String(inconclusive)} inconclusive`,
  )
  // Exit 0 regardless. A surviving mutant is information for the person
  // running this, not a build failure — this is not in the verify chain and
  // making it exit non-zero would invite somebody to put it there.
}

// Importable for its tests without running the CLI.
if (process.argv[1]?.endsWith('mutate.mjs')) main()
