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
    phase: '5',
    what: "the `\u22ef` trigger and the topic row's overflow wrapper",
    why: '`.menu-trigger` was six declarations in `tree.css`, which is a *screen* stylesheet, and the topic row wanted the same button -- so the choice was a second copy in `entity.css` or a `MenuTrigger` in the primitive that owns it. Two `\u22ef` buttons drifting apart is a defect nobody would report. `.ent-topic-overflow` went with the span it styled: it wrapped a list of overflow verbs, and there is one `\u22ef` there now. Over `styles` because both are rules, and a rule that matches nothing goes on saying nothing about it.',
    where: 'styles',
    forbid: [/\.menu-trigger\s*\{/, /\.ent-topic-overflow\s*\{/],
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
    phase: '5',
    what: "the decision bar's allow-all was dressed from the course view's stylesheet",
    why: "Same replacement as the approval card, for a sharper reason. `AutonomyAllowAll` moved into the shell's `DecisionBar`, which is already utilities, and left its layout behind in `course.css` -- a file on the die-with-its-screen list. So the policy's own deletion path had a trap in it: rebuilding the course view deletes the stylesheet, and a control that is *not* the course view and is still on screen loses its column, its gap and its indent, with nothing failing. That is `.extraction-failed > .extraction-summary` again -- no test, no error, a rule that quietly stopped applying -- except the rule does not stop matching, it stops existing. `.autonomy-warn` and `.autonomy-error` are still absent from *this* list, and for a reason that has changed: they remain in `course.css` legitimately, because `AutonomyPanel` is a real course-page surface that dies with the file. What was wrong was `AutonomyAllowAll` also reaching for them; the rule below is that half.",
    where: 'styles',
    forbid: [
      /^\.autonomy-allow\b/m,
      /^\.autonomy-allow-head\b/m,
      /^\.autonomy-allow-actions\b/m,
      /^\.autonomy-result\b/m,
      /^\.autonomy-off\b/m,
    ],
  },
  {
    phase: '5',
    what: 'the decision bar reached into `course.css` for its warning and its write error',
    why: "The other half of the rule above. `.autonomy-warn` and `.autonomy-error` stay in `course.css` for `AutonomyPanel`, which is a course-page surface and dies with the file -- but `AutonomyAllowAll` renders in the shell's decision bar on every route, so writing those classes there was a control borrowing dressing from a screen it outlives. It carries the same declarations as utilities now. Scoped to the one file by `only`, because the directory also holds `AutonomyPanel.tsx`, which must go on using them, and a rule that fired on the correct file is a rule somebody turns off.",
    where: 'presentation/course',
    only: /^presentation\/course\/AutonomyAllowAll\.tsx$/,
    forbid: [/autonomy-warn/, /autonomy-error/],
  },
  {
    phase: '5',
    what: 'four shell-reached components were dressed from stylesheets that die with a screen',
    why: '`docs/reports/stylesheet-orphan-sweep.md` found them by inverting the usual question -- not "what does this stylesheet dress" but "what dresses the components that outlive every view". `.drawer*` and the five gate-severity chip tones were in `course.css`, `.chip`\'s base was in `tree.css`, and `.btn-quiet` was in `composer.css`, while `Drawer`, `Chip`, `GateReview` and `AutonomyAllowAll` are all reached from the shell on every route. Deleting any of those files would have unstyled something still on screen with nothing failing -- jsdom applies no stylesheet and a class that resolves to nothing raises no error, which is why this was found by a sweep rather than by a build. The dressing is on the components now (`.btn-quiet` excepted; `shell.css` argues that one). A rule under `src/styles/` reclaiming any of these names is that coupling coming back.',
    where: 'styles',
    // Anchored to the start of a line, which is doing real work rather than
    // being tidy: `responsive.css` legitimately keeps a `.drawer` inside a
    // media query, indented, narrowing the panel below 820px. That override is
    // the reason `Drawer` still writes the class at all, and a pattern that
    // could not tell it from a base rule would fail on correct code.
    // `.btn-quiet` is matched everywhere except `shell.css`, where it now lives
    // beside `.btn` and the four other tones.
    forbid: [
      /^\.drawer\s*\{/m,
      /^\.drawer-(head|title|spacer|body)\b/m,
      /^\.chip\s*\{/m,
      /^\.chip-(invariant|blocking|advisory|human_gate|critic_gate)\b/m,
    ],
  },
  {
    phase: '5',
    what: 'the fifth button tone lived in the session composer',
    why: "Same sweep, split out because its fix is the opposite one and the scope has to differ. `.btn-quiet` could not become utilities: `Button` renders `.btn`, `.btn` sets background, border-colour and colour unlayered, and Tailwind's utilities are in `@layer utilities`, which loses to an unlayered rule regardless of specificity. So it moved to `shell.css` beside the tones it belongs with. Forbidden everywhere else under `styles`, including back in `composer.css`.",
    where: 'styles',
    only: /^styles\/(?!shell\.css$)/,
    forbid: [/^\.btn-quiet\b/m],
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
  {
    phase: 'C1',
    what: 'two whole-page views the project page replaced',
    why: "The route merge's QUEUE slice. `CourseView` and `ResearchView` were the two arms `App.tsx` dispatched a project route between, and slice 0 left both unreferenced rather than deleting them -- a frame with no tenants had nothing to compare against yet. They are gone now, with `use-research-panes.ts` and its `research` preference group, `COURSE_TRACKS` and `COURSE_GROUP`. The `CoursePanes` story and test deliberately survive and declare their two tracks locally: they are the only place `StageList` and `ArtifactList` render real content with no `QueryClientProvider`, so they are a workbench for that pair rather than a fixture of the page that is gone, and deleting five assertions to remove one import would have been a bad trade. What replaces them is one page with three regions and a `QueueHeader`. A file coming back under either name is the merge being undone by somebody who has not read why.",
    where: 'presentation',
    forbid: [/\bCourseView\b/, /\bResearchView\b/, /\buseResearchPanes\b/, /\bCOURSE_TRACKS\b/],
  },
  {
    phase: 'C1',
    what: 'the two deleted views left combinators claiming markup that is gone',
    why: "The §5.1 hazard, and the reason these are patterns over `styles` rather than a note in a report. Every selector here named an ancestor only `CourseView` or `ResearchView` wrote -- `.lay-split[data-split='course'] > .lay-pane`, `.research-rail > [data-pane='topics']`, eleven more -- so the day that markup went they became rules that match nothing, silently, with no test failure and no error. `check-deleted.mjs` already cites `.extraction-failed > .extraction-summary` as this having happened once. They were deleted in the same commit as the views, from `course.css`, `research.css` and `responsive.css`, and this is what stops one being reintroduced by a copy-paste from a stylesheet that still remembers the old shape. **`course.css` and `research.css` themselves are still alive** and are not in this rule: five component families in the first and three in the second are still on screen, which is why neither file left `STYLESHEETS` in this commit. *(Superseded for the second file: slice 3b rewrote all three of those families and `research.css` is deleted. The `.research-rail` and `.research-workbench` patterns here still bind, and now forbid reintroducing them into any stylesheet rather than into that one. `course.css` is still alive and this half stands.)*",
    where: 'styles',
    forbid: [
      /\[data-split='course'\]/,
      /^\.view-course\b/m,
      /^\.course-findings\b/m,
      /\.research-rail\b/,
      /\.research-workbench\b/,
      /^\.view-research\b/m,
    ],
  },
  {
    phase: 'C1',
    what: 'one card was declared three times, in two files, for three sibling panels',
    why: "`.worker-panel` and `.autonomy-panel` in `course.css` and `.run-panel` in `components.css` were the same six declarations -- border, radius, panel background, padding, margin, flex column, gap -- and `course.css`'s own comment described the duplication as deliberate, so that three bands would read as one. `QueueHeader` makes them one band for real, spelled once in utilities around all four panels, so the three rules are dead and deleted. Forbidden rather than merely removed because the failure mode is a reviewer adding one back to fix a panel that looks undressed, which would restore the duplication and not the missing dressing.",
    where: 'styles',
    forbid: [/^\.run-panel\b/m, /^\.worker-panel\b/m, /^\.autonomy-panel\b/m],
  },
  {
    phase: 'C4',
    what: 'the console had two button implementations and one of them is gone',
    why: "`.cmp-btn` in `components.css` dressed `CmpButton`, which six lesson-widget call sites used -- `Mcq`, `Cloze`, `Flashcards` -- while every other button in the console was `Button`/`.btn` from `shell.css`. The two shared no substring, so no grep found them together and neither file gave any sign the other existed; `primitives.stories.tsx`'s `TwoButtons` story is what put them side by side, which is the argument for that story and for this rule in one sentence. They were not the same control: `5px 11px` against `4px 11px`, `--fg` against `--fg-dim`, and a primary action that was an accent **fill** in one and an accent **outline** in the other. `CmpButton` renders `Button` now and the six rules are dead. Forbidden rather than merely removed for the reason C3 gives: these were unlayered rules, so a re-added `.cmp-btn` would beat `.btn`'s utilities-and-rules outright and silently restore the split -- and the failure mode is specific and likely, a reviewer seeing a lesson button that looks unlike the mock and reaching for the class name the old markup used. The `:focus-visible` grouping in `components.css` keeps its other three selectors (`.flash-card`, `.cloze-input`, `.cmp input`), which are not buttons and are not affected. `components.css` itself is very much alive and does not leave `STYLESHEETS`.",
    where: 'styles',
    forbid: [/^\.cmp-btn\b/m],
  },
  {
    phase: 'C3',
    what: "MATERIAL's artifact, finding and document shelves are utilities now",
    why: "The route merge's slice 3, narrowed to the three MATERIAL facets whose markup it actually rewrites. `Artifacts`, `ArtifactList`, `Findings`, `DocumentBrowser` and `DocumentReader` carry their own dressing, and 22 rules left `course.css` with 13 leaving `research.css`. **Neither file dies, and the reason is structural rather than incidental**: what is left in the first is four families that are all QUEUE's (rail, roster, extraction, autonomy) and what is left in the second is the topic list, which is also QUEUE's, plus the graph and the seed form. A MATERIAL-only slice cannot kill either, which is why neither left `STYLESHEETS`. *(Still true of `course.css`. `research.css` died in slice 3b, which was not a MATERIAL-only slice: it took the topic list and the seed form -- QUEUE's -- along with the graph, and those three were the whole of what this paragraph lists as remaining.)* Forbidden rather than merely removed because two of the three carried something a reviewer would not miss: the four artifact chip tones and the five finding edges are `PRESENT_DRESS`/`SEVERITY_EDGE` in the components now, and a re-added `.chip-present` or `.finding-invariant` would win over the utilities outright -- an unlayered rule beats `@layer utilities` -- restoring the split this deletion closed.",
    where: 'styles',
    forbid: [
      /^\.artifacts?\b/m,
      /^\.artifact-/m,
      /^\.prov-src\b/m,
      /^\.chip-(present|missing|inferred|bad)\b/m,
      /^\.findings?\b/m,
      /^\.finding-/m,
      /^\.document-/m,
    ],
  },
  {
    phase: 'C3b',
    what: 'the graph, the topic list and the seed form are utilities, and `research.css` is gone',
    why: "The other half of the route merge's slice 3, and the first stylesheet to leave `STYLESHEETS` since the array was frozen. All 734 lines of `research.css` belonged to exactly three families -- the topic cluster, the graph, and the seed form -- so rewriting those three left nothing behind and the file was deleted rather than emptied. Forbidden rather than merely removed for the reason C3 gives one rule up, which this slice proved twice over: an unlayered rule beats `@layer utilities`, so a re-added `.topic-list` or `.graph-result` would win outright over the utilities that replaced it. That is not hypothetical here -- slice 3a's inward focus ring was written as a utility against exactly such an unlayered rule and did nothing at all for a whole slice, on every document row, with a green suite. The fix that replaced it is `.lay-ring-inward` in `layout.css`, which is a rule and not a utility for the same reason. One name is deliberately narrower than its family: `.graph-` would also match nothing else today, but `^\\.seed-` and `^\\.sub-question` are spelt as anchored prefixes so a future `.seeded-` or `.sub-questionnaire` is not caught by accident.",
    where: 'styles',
    forbid: [/^\.topic-/m, /^\.sub-question/m, /^\.graph-/m, /^\.seed-/m],
  },
]

/** Every stylesheet under `src/styles/` that exists today, frozen.
 *
 * **The decision this records, which is written down nowhere else.** The spec's
 * phase 5 planned to port these 22 files to Tailwind utilities one at a time.
 * That plan was dropped on 2026-08-10 and replaced with: *new and rewritten
 * surfaces use Tailwind utilities; existing stylesheets are deleted, never
 * ported.* The arithmetic behind it is the whole argument -- roughly 6430 lines
 * across these files are attached to markup that increment C's route merge
 * rebuilds anyway, so porting them is work thrown away twice, once writing it
 * and once deleting it. No migration is scheduled. The stylesheets die with the
 * screens they dress.
 *
 * A policy nobody can point at is a policy that lasts until the next person who
 * has not read it, which is why this is a list and not a paragraph in a
 * document. The list is deliberately exhaustive rather than a count: a count
 * fails on the right *number* and says nothing about which file moved.
 *
 * **Why a removal fails too, which reads backwards until you see what it is
 * for.** Deleting one of these is the direction this project wants. The check
 * is not objecting -- it has no way to distinguish a stylesheet deleted on
 * purpose from one lost in a bad merge, and only one of those should be
 * silent. Failing makes the deletion appear in a diff with a line removed from
 * this array beside it, which is the same trade the `RULES` above make and for
 * the same stated reason.
 *
 * **The hole, stated plainly because it is real.** This freezes the *set of
 * files*. It catches a 23rd stylesheet; it does not catch 200 lines of rules
 * for a brand-new surface appended to `research.css`, which is the same policy
 * violation wearing an existing filename. A line-count ratchet per file was
 * considered as the fix and rejected: its failure mode is a build failing on
 * every legitimate three-line correction to a surface that still exists and is
 * still allowed to be corrected -- friction on the common case to catch the
 * rare one, which is how a check earns being switched off. Review is what
 * covers the hole, and this comment is what tells a reviewer to look. */
const STYLESHEETS = [
  'agents.css',
  'base.css',
  'components.css',
  'composer.css',
  'conversation.css',
  'course.css',
  'diff.css',
  'entity.css',
  'index.css',
  'layout.css',
  'markdown.css',
  'responsive.css',
  'scrub-bar.css',
  'shell.css',
  'states.css',
  'structure.css',
  'theme.css',
  'timeline.css',
  'tokens.css',
  'tree.css',
  'workspace.css',
]

/** Exported so the comparison can be tested in both directions without a
 *  subprocess, the same shape `mutate.mjs` gives `classify` -- the part that
 *  can be wrong silently is pure, and the I/O around it is either right or
 *  obviously broken.
 *
 *  Non-`.css` entries are the caller's problem, not this function's: the
 *  directory also holds `color-scheme.browser.test.tsx` and a `__screenshots__`
 *  directory, and a freeze that fired on a new browser test would be forbidding
 *  exactly the kind of test this repository keeps asking for more of. */
export const compareStylesheets = (present, manifest) => ({
  added: present.filter((name) => !manifest.includes(name)).sort(),
  removed: manifest.filter((name) => !present.includes(name)).sort(),
})

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

/** Everything below runs only when this file is invoked as a CLI, so that
 *  `compareStylesheets` can be imported by a test without the walk, the
 *  `console.log` and the `process.exit` coming with it. Guard copied from
 *  `mutate.mjs`, which does the same for `classify`. */
const main = () => {
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

  const present = readdirSync(join(SRC, 'styles')).filter((name) => name.endsWith('.css'))
  const { added, removed } = compareStylesheets(present, STYLESHEETS)

  if (failures.length === 0 && added.length === 0 && removed.length === 0) {
    console.log(
      `Nothing has come back — ${String(RULES.length)} deletion rules hold, ` +
        `and ${String(STYLESHEETS.length)} stylesheets stay frozen.`,
    )
    process.exit(0)
  }

  for (const { rule, path, pattern } of failures) {
    console.error(`\n✗ src/${path} matches ${String(pattern)}`)
    console.error(`  Phase ${rule.phase} deleted ${rule.what}.`)
    console.error(`  ${rule.why}`)
  }

  for (const name of added) {
    console.error(`\n✗ src/styles/${name} is a stylesheet this project decided not to add.`)
    console.error(
      `  New and rewritten surfaces use Tailwind utilities against the \`@theme\` tokens, as` +
        ` \`DecisionBar.tsx\` and \`Approvals.tsx\` already do. The 22 stylesheets that remain are` +
        ` attached to markup the route merge rebuilds anyway; they are being deleted, never` +
        ` ported, and a 23rd is the accumulation that decision was made to stop.`,
    )
  }

  for (const name of removed) {
    console.error(`\n✗ src/styles/${name} is in the manifest and not on disk.`)
    console.error(
      `  If you deleted it: good, that is the direction — remove the line from \`STYLESHEETS\` in` +
        ` scripts/check-deleted.mjs in the same commit and this passes. The failure is not an` +
        ` objection, it is how a deletion gets recorded in a diff rather than happening quietly.` +
        ` If you did not delete it, something else did, which is the case this exists to catch.`,
    )
  }

  const total = failures.length + added.length + removed.length
  console.error(
    `\n${String(total)} thing(s) need a decision. If one of these is deliberate, edit the rule or` +
      ` the manifest in scripts/check-deleted.mjs in the same commit and say why.`,
  )
  process.exit(1)
}

if (process.argv[1]?.endsWith('check-deleted.mjs')) main()
