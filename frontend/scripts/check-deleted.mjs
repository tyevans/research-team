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
    phase: '4',
    what: 'the agent dock positioned its own popover',
    why: '`.agents-panel` was `position: fixed; top: var(--topbar-h); right: var(--space-4)`, with a second rule at 420px re-laying it out full-width. That is a hand-rolled anchor: right only while the widget sits at the right-hand end of a full-width bar, unable to flip off a viewport edge, and describing the topbar from a file that cannot see it. The panel is `Popover` content now and Radix measures the trigger, so any positioning here fights the inline transform the positioner writes. The 420px override went with it.',
    where: 'styles',
    // `(?:[^}]*;)?\s*top:` rather than `[^}]*top:`, because the rule legitimately keeps
    // `border-top: 0` -- the panel is square where it meets the bar. A pattern
    // that cannot tell a shorthand from a longhand fires on correct code,
    // which is the failure mode this whole file's own comment warns about.
    forbid: [/\.agents-panel\s*\{(?:[^}]*;)?\s*position:/, /\.agents-panel\s*\{(?:[^}]*;)?\s*top:/],
  },
  {
    phase: '4',
    what: 'the agent dock moved focus into its own panel and back out again',
    why: "A `useEffect` reached into the panel with `querySelector('button')` on open, and a `close()` helper called `toggleRef.current?.focus()`. Radix's focus scope does both, and does the first better -- it focuses the first *tabbable* node rather than the first `<button>`, which is the same element today and stops being so the moment a row gains a link. A `querySelector` for a focus target here means somebody is re-implementing a focus scope beside one that is already running, and two of those disagree the first time the panel's markup changes.",
    where: 'presentation/agents',
    // Narrow on purpose. A bare `/querySelector/` fired on `AgentWidget.test.tsx`,
    // which reaches into the DOM for entirely legitimate reasons, and a rule
    // that fails on correct code is a rule somebody turns off. These two name
    // the deleted lines instead: the panel query, and the ref that existed only
    // to be focused by hand.
    forbid: [/querySelector<HTMLElement>\('button'\)/, /\btoggleRef\b/],
  },
  {
    phase: '4',
    what: 'the row menu was a Disclosure wearing menu chrome',
    why: '`.menu > .disc-head`, `.menu > .disc-head .disc-caret` and `.menu > .disc-body:not([hidden])` dressed a disclosure up as a menu and got the ARIA contract wrong doing it: `aria-expanded` over a region, no `role="menu"`, no arrow-key movement between items, no typeahead, and no focus return. It is a `Menu` now. The three `>` selectors are the reason this rule is over `styles` as well -- a combinator is a claim about markup, and this one silently stopped matching the moment the markup moved.',
    where: 'styles',
    forbid: [/^\.menu\s*\{/m, /\.menu\s*>/],
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
    phase: 'E',
    what: 'the application shell built its own header and main',
    why: '`App.tsx` renders `Shell`, so `.topbar` and `<main id="app">` are gone -- both were the rules `.lay-chrome` and `.lay-surface` already declared, written a second time. This is not housekeeping: while the shell was hand-built it mounted no `OverlayHost`, and `Overlay` returns `null` without one, so every drawer, confirm and popover in the console rendered nothing. `App.test.tsx` is what fails now if the host goes; this fails if the markup that displaced it comes back.',
    where: 'styles',
    forbid: [/\.topbar\s*\{/, /^#app\s*\{/m],
  },
  {
    phase: '2',
    what: 'the session view folded with DOM-owned state',
    why: 'S-D14. `<details>` owns whether it is open, so a fold inside a view that refetches shuts under the reader -- and `Conversation` re-renders on every turn end. `Disclosure` takes `open` and `onToggle` so the state lives above the refetch. `Segments.test.tsx` is the real net -- six of its seven cases fail against a `<details>`-backed `Disclosure`, checked -- and this rule covers the rest of the directory, where a new `<details>` would be untested and silent. Scoped to `presentation/session` deliberately: `AutonomyPanel` keeps its `<details>` on purpose and says why. It has no refetch to survive and real find-in-page value over 24 controls, so the trade §9 makes globally does not hold there.',
    where: 'presentation/session',
    forbid: [/<details/, /<summary/],
  },
  {
    phase: '1',
    what: 'the topic dialog kept its own copy of the trap Drawer had already deleted',
    why: 'It carried a second `FOCUSABLE_SELECTOR`, a second focus-in/restore pair, a second `.drawer-backdrop` and a second `role="dialog"` aside -- the duplication `Drawer`\'s own comment predicted, written down, and then made anyway. Phase D deleted the copy in `presentation/common` and this rule covers where the other one lived. The trap is the part that matters: it cycled Tab among its own children while the agent dock painted on top of the dialog and stayed clickable, which is what a simulation of confinement cannot see and `inert` does not permit.',
    where: 'presentation/research',
    forbid: [/FOCUSABLE_SELECTOR/, /className="drawer-backdrop"/],
  },
  {
    phase: '1',
    what: 'ending a session asked with the browser’s own confirm box',
    why: 'S-D1, and the last `window.confirm` in the console. It blocks the tab, cannot be styled, cannot be reached by the keyboard contract every other dialog here honours, and renders its two sentences as one paragraph joined by `\\n\\n` because that is the only thing it can render. Those sentences are the load-bearing part -- "end this session" reads as destructive and they are what say the log survives -- so they moved verbatim into `Confirm`. A `window.confirm` anywhere under `src` is that box coming back.',
    // The empty string is every file: `where` is matched with `startsWith`
    // against a path already relative to `src`, so `'src'` would scope this to
    // nothing at all and pass forever. This is the first repo-wide rule and
    // that is deliberate -- the point is not that `SessionView` stops asking
    // this way, it is that nothing starts.
    where: '',
    forbid: [/window\.confirm\(/],
  },
  {
    phase: '3',
    what: 'explanations lived in `title` attributes',
    why: 'S-D3. A `title` is announced on hover, after a delay the operating system owns, and on nothing else -- not on focus, not on touch, not to a screen reader reading a `<span>`. Fifty-one of them carried real sentences ("Also autos the workflow review gate, so a run can cross stage boundaries unattended") and every one of them reached a mouse and no other reader. They are `Tooltip`s where they explained something, accessible names where they named an icon, and deleted where they repeated the text beside them. A `title=` here is one of those three arriving as the fourth.',
    // Repo-wide over `presentation`, which it can only be because no component
    // under it has a prop called `title` any more: `Drawer`, `Confirm`,
    // `EmptyState` and `ErrorBox` all take `heading`, renamed in the same
    // commit precisely so this rule does not have to tell a heading from an
    // attribute with a regex. It cannot -- both are `title=` in JSX -- and a
    // rule that guesses is a rule somebody turns off.
    //
    // Two exemptions, both outside this scope and both legitimate.
    // `infrastructure/rendering/markdown.ts` keeps `title` in `ALLOWED_ATTR`
    // and sets it on links, because that is markdown's own `[text](href
    // "title")` and stripping it would be this console editing documents it
    // renders. And an `<iframe>` needs a `title` as a genuine accessibility
    // requirement -- there is none in this codebase today, so widening the
    // scope to all of `src` would forbid the one attribute nobody may remove.
    where: 'presentation',
    forbid: [/title=/],
  },
  {
    phase: '3',
    what: 'approvals were rendered per session, from three call sites',
    why: 'Replaced by one `DecisionBar` in the shell, subscribed to the whole feed. The three call sites -- the conversation footer, the worker drawer, and the course page through that drawer -- each showed only the approvals of the session already on screen, so "is anything waiting on me?" had a different answer on every page and the honest way to find out was to open every session in turn. An import of `Approvals` from either directory is one of those call sites coming back; the bar is the only thing that may render it.',
    where: 'presentation/session',
    forbid: [/from '\.\/Approvals\.tsx'/],
  },
  {
    phase: '3',
    what: 'the worker drawer took decisions as well as showing them',
    why: "Same replacement, other call site. The drawer's argument -- the person watching is the person positioned to decide -- was right and too narrow: it only held while that drawer was open.",
    where: 'presentation/course',
    // `AutonomyAllowAll` is deliberately *not* forbidden here, and the reason
    // is a limit of this check rather than a decision: `where` is a directory
    // prefix, and `AutonomyPanel.test.tsx` lives in the same directory and
    // legitimately renders the control as a unit. A rule that cannot tell the
    // unit test from the deleted call site would fire on the wrong one, and a
    // check that has to be argued with is worse than one fewer check. The
    // `Approvals` import is the half that can be stated precisely, and it is
    // the half that carried the defect.
    forbid: [/from '\.\.\/session\/Approvals\.tsx'/],
  },
  {
    phase: '3',
    what: 'the approval card had a stylesheet',
    why: 'It is Tailwind utilities in `Approvals.tsx` now. The `.approval*` block in `conversation.css` matched nothing the moment the card was rewritten, and a block that matches nothing is exactly the failure `.extraction-failed > .extraction-summary` recorded -- no test, no error, just a rule that quietly stopped applying.',
    where: 'styles',
    forbid: [/^\.approvals\b/m, /^\.approval\b/m, /^\.approval-/m],
  },
  {
    phase: 'B',
    what: 'stylesheets each carried their own stacking numbers',
    why: 'Eight literal `z-index` declarations across five values, two of which produced a popover painting over an `aria-modal` dialog. Every one now names a role from `tokens.css`. `scripts/stacking.test.ts` is the real enforcement and is more precise than this -- it also rejects an undeclared token and a fourth role. This entry is here so the *count* is recorded where the other phase deletions are; if it ever fires, read that test first.',
    where: 'styles',
    forbid: [/z-index\s*:\s*\d/],
  },
  {
    phase: 'B',
    what: 'a story mounted its own OverlayHost, and six that needed one did not',
    why: "The host is in `.storybook/preview.tsx` now, around every story. Per-story was the rule before and it held in exactly one file out of seven -- `TopicQueue.stories.tsx` -- while the stories for `GateReview`, `WorkerList`, `RunPanel`, `Artifacts`, `AutonomyPanel` and `StageRail` silently rendered every trigger with no explanation, because a `Tooltip` with no host renders no content and no error. A rule kept only by remembering it is not a rule. `Shell` and the host's own tests are excluded by `only`, since mounting one is their subject.",
    where: 'presentation',
    // Not `layout/`: `OverlayHost.stories.tsx` is the host's own workbench and
    // `Shell.stories.tsx` mounts the real one. Both are showing the mechanism
    // rather than working around its absence, which is the distinction this
    // rule is drawing.
    only: /^(?!presentation\/layout\/).*\.stories\.tsx$/,
    forbid: [/\bOverlayHost\b/],
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
  // `where` is a directory prefix, which is the right unit for every rule that
  // deleted something from a *view*. `only` narrows further by filename, and
  // exists because one deletion is about a kind of file rather than a place:
  // stories mounting their own `OverlayHost`. Forbidding that anywhere under
  // `presentation` would fail on `Shell.tsx` and `OverlayHost.test.tsx`, which
  // are the two files that must keep doing it.
  const scope = files.filter((path) => {
    const name = relative(SRC, path)
    return name.startsWith(rule.where) && (!rule.only || rule.only.test(name))
  })
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
