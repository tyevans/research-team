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
 *  repository-wide grep -- it was written when `.pane-body` was dead in the
 *  session view and alive in the research rail and the course page.
 *
 *  Both have since migrated, so the phase-C rule below *is* repository-wide
 *  over `styles`, which is the shape a rule takes once the last legitimate
 *  user is gone. The scoping is still what lets the phase-B rules forbid
 *  `replace('_', ' ')` under `presentation/research` while the landing page
 *  has not migrated. */
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
  {
    phase: 'B',
    what: 'the research rail had a fourth fold implementation of its own',
    why: 'Replaced by `Pane` with `collapseTo="strip"` and `useResearchPanes`. `RailPane` was the third component in this codebase to write a fold, and the only one whose toggle announced itself correctly -- which is the tell that the behaviour belonged to a primitive rather than to a view.',
    where: 'presentation/research',
    forbid: [/\bRailPane\b/, /'is-folded'/, /className=\{?clsx\('pane'/],
  },
  {
    phase: 'B',
    what: 'the research view drew its own topic row and spelled its own status',
    why: "Replaced by `entity/topic/TopicRow` and `EntityStatus`. `status.replace('_', ' ')` was the third copy of a domain vocabulary rule, and all three were wrong the same way: a string pattern replaces only the first underscore.",
    where: 'presentation/research',
    forbid: [/replace\('_'/, /className="topic-row/, /className="topic-question"/],
  },
  {
    phase: 'B',
    what: 'the research panes were folded and sized by class names the stylesheet keyed on',
    why: '`.pane-seeding`, `.pane-topics`, `.pane-documents` and `.pane-graph` are gone; a research pane is `.lay-pane` selected by `data-pane`. The 240px floor those rules carried is `minContent` on the pane, which travels with it instead of being a literal two selectors reach.',
    where: 'styles',
    forbid: [
      /\.pane-seeding/,
      /\.pane-topics/,
      /\.pane-documents/,
      /\.pane-graph/,
      /\.pane\.is-folded/,
    ],
  },
  {
    phase: 'C',
    what: 'the course page built its own two-pane grid and its own pane markup',
    why: 'Replaced by `Split`, `COURSE_TRACKS` and two `Pane`s. The grid was declared across two stylesheets -- `display: grid` in `panes.css`, the tracks in `course.css` -- so neither file described it alone, which is the same split-brain `SESSION_TRACKS` was written for.',
    where: 'presentation/course',
    forbid: [
      /className="panes/,
      /className="pane /,
      /className="pane-head"/,
      /className="pane-meta"/,
    ],
  },
  {
    phase: 'C',
    what: 'the old pane stylesheet outlived the views that used it',
    why: '`panes.css` is `scrub-bar.css` now and holds no pane rule. Its own comment named this migration as the one it was waiting for: "This rule and `.course-panes` go together when the course page migrates." A pane is `.lay-pane` in `layout.css`, and nothing else may re-declare these names.',
    where: 'styles',
    forbid: [
      /^\.panes\b/m,
      /^\.pane\b/m,
      /^\.pane-head\b/m,
      /^\.pane-body\b/m,
      /^\.pane-meta\b/m,
      /^\.pane-toggle\b/m,
      /\.course-panes/,
    ],
  },
  {
    phase: 'D',
    what: 'the drawer and the agent dock each floated themselves',
    why: 'Both are `Overlay` layers now, in the one host at `--z-overlay`. `.drawer-backdrop` was 20 and `.agents-panel` was 40, which is *why* a popover painted over an `aria-modal` dialog -- the two numbers were the defect, not a symptom of it. A reappearance of either class is that arrangement returning.',
    where: 'styles',
    forbid: [/\.drawer-backdrop/, /\.agents-panel\s*\{[^}]*z-index/],
  },
  {
    phase: 'D',
    what: 'Drawer hand-rolled a focus trap and its own Escape listener',
    why: 'Replaced by `inert` on `.lay-app-root` and the host owning Escape. The trap cycled Tab among its own children, which is a simulation of confinement rather than confinement: it said nothing about the pointer, nothing about assistive technology, and nothing about the popover painting on top. `FOCUSABLE_SELECTOR` coming back means somebody is re-implementing it.',
    where: 'presentation/common',
    forbid: [/FOCUSABLE_SELECTOR/, /addEventListener\('keydown'/],
  },
  {
    phase: 'D',
    what: 'the agent dock reasoned about whether a drawer was in front of it',
    why: 'The guard read `if (!expanded || watching) return` -- a popover deciding whether it still owned Escape based on what else was open. It was also *wrong*, because the stylesheet put the popover in front of the thing it had stood down for. The host gives Escape to the topmost layer and a layer cannot see its neighbours, so there is nothing left to reason about. Either listener coming back here is that coupling returning.',
    where: 'presentation/agents',
    forbid: [/addEventListener\('keydown'/, /addEventListener\('pointerdown'/],
  },
  {
    phase: 'B',
    what: 'stylesheets each carried their own stacking numbers',
    why: 'Eight literal `z-index` declarations across five values, two of which produced a popover painting over an `aria-modal` dialog. Every one now names a role from `tokens.css`. `scripts/stacking.test.ts` is the real enforcement and is more precise than this -- it also rejects an undeclared token and a fourth role. This entry is here so the *count* is recorded where the other phase deletions are; if it ever fires, read that test first.',
    where: 'styles',
    forbid: [/z-index\s*:\s*\d/],
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
