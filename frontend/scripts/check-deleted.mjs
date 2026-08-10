#!/usr/bin/env node
/* What each landed phase of the UI migration promised to remove.
 *
 * `component-system-spec.md` §15 names the one discipline the whole rollout
 * rests on -- "a phase that adds a mechanism without removing the old one has
 * not shipped" -- and then concedes that it is "a promise rather than a
 * mechanism", because nothing in the four gates fails when a superseded
 * implementation is left in place. It also names the honest fix, a lint rule
 * or a per-phase checklist, and records that neither exists.
 *
 * This is that, in the shape this repository already uses for the same
 * problem: `check-size.mjs` for the bundle, the AST guard over the `create_app`
 * call site, `apply_schema`'s column reconciliation with a test that drops a
 * column and reopens. A promise nobody can break by accident.
 *
 * The cost, stated because it is real: this is a list of strings, and a list
 * of strings drifts. A rule kept after the thing it guards has legitimately
 * come back is a build failing for no reason. So each entry carries the phase
 * that added it and a sentence about what it means, and removing one is a
 * decision somebody makes in a diff rather than a silent edit -- which is the
 * most a check like this can offer.
 */
import { readFileSync, readdirSync, statSync } from 'node:fs'
import { join, relative } from 'node:path'
import { fileURLToPath, URL } from 'node:url'

const SRC = fileURLToPath(new URL('../src', import.meta.url))

/** `where` is a path prefix under `src/`, so a rule can forbid a name in the
 *  files that replaced it without forbidding it in the ones that still
 *  legitimately use it. That distinction is the whole reason this is not a
 *  repository-wide grep: `.pane-body` is dead in the session view and alive in
 *  the research rail and the course page. */
const RULES = [
  {
    phase: 'A',
    what: 'the session view built its own three-pane grid',
    why: 'Replaced by `Split` and `SESSION_TRACKS`. Two declarations of the same three columns disagreed by 20px on two of them, and only the inline one was ever on screen.',
    where: 'presentation/session',
    forbid: [/\bgridTemplateColumns\b/, /\busePanes\b/, /from '\.\/Pane\.tsx'/],
  },
  {
    phase: 'A',
    what: 'the session view had its own Pane with a glyph for an accessible name',
    why: 'Replaced by `presentation/layout/Pane.tsx`, whose toggle carries a sentence. The glyph is the S-D2 defect; a reintroduction here is that defect coming back.',
    where: 'presentation/session',
    forbid: [/className=\{?clsx\('pane'/, /'pane-body-split'/],
  },
  {
    phase: 'A',
    what: 'the session panes were folded by a class the stylesheet keyed on',
    why: '`.pane.collapsed` is gone; a folded pane is `.lay-pane.is-collapsed` with `data-collapse-to`. The old rule set `display: none` and left the folded composer in the accessibility tree.',
    where: 'styles',
    forbid: [/\.pane\.collapsed/, /\.pane-conversation/, /\.pane-timeline/, /\.pane-workspace/],
  },
  {
    phase: 'A',
    what: 'the rail width and the breakpoints were literals in more than one place',
    why: '`--rail-w` and `--bp-*` in `tokens.css`, `layout-tokens.ts` for the JavaScript, and `theme.test.ts` holding the two together. A bare `34px` is the third copy coming back.',
    where: 'styles',
    // The lookbehind spares the one declaration that is supposed to exist:
    // `--rail-w: 34px` in `tokens.css` is the definition, and `theme.test.ts`
    // is what holds it against `layout-tokens.ts`. Everything else spelling the
    // number out is the copy this rule is for -- it was written three times
    // before phase A, once in a hook and twice in `responsive.css`.
    forbid: [/(?<!--rail-w):\s*34px/, /min-width:\s*1180px/],
  },
]

/** Comments removed before matching, which `theme.test.ts` also does and for
 *  the same reason: this asks whether a mechanism has come back, and a
 *  docstring explaining why one was removed is the opposite of that. The first
 *  run of this script failed on `SessionView.test.tsx`, whose whole purpose is
 *  to describe the hole the deleted line left -- a check that forbids naming
 *  what it deleted makes the deletion undocumentable.
 *
 *  Block comments first, then line comments, and `//` only when it is not part
 *  of a `://`. That last guard is for URLs in comments; a pattern in this file
 *  would not match one anyway, so the cost of being wrong here is a missed
 *  match rather than a false alarm, and a missed match is the safer direction
 *  for a check whose failure mode is crying wolf. */
const withoutComments = (source) =>
  source.replace(/\/\*[\s\S]*?\*\//g, '').replace(/(^|[^:])\/\/[^\n]*/g, '$1')

const files = (function walk(dir) {
  return readdirSync(dir).flatMap((entry) => {
    const path = join(dir, entry)
    return statSync(path).isDirectory() ? walk(path) : [path]
  })
})(SRC)

const failures = []
for (const rule of RULES) {
  const scope = files.filter((path) => relative(SRC, path).startsWith(rule.where))
  for (const path of scope) {
    const source = withoutComments(readFileSync(path, 'utf8'))
    for (const pattern of rule.forbid) {
      if (!pattern.test(source)) continue
      failures.push({ rule, path: relative(SRC, path), pattern })
    }
  }
}

if (failures.length === 0) {
  const count = RULES.length
  console.log(`Nothing has come back — ${String(count)} deletion rules hold.`)
  process.exit(0)
}

for (const { rule, path, pattern } of failures) {
  console.error(`\n✗ src/${path} matches ${String(pattern)}`)
  console.error(`  Phase ${rule.phase} deleted ${rule.what}.`)
  console.error(`  ${rule.why}`)
}
console.error(
  `\n${String(failures.length)} superseded thing(s) are back. If one of these is deliberate, ` +
    `delete its rule in scripts/check-deleted.mjs in the same commit and say why.`,
)
process.exit(1)
