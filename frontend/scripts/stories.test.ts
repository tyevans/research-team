// `node:fs`'s sync API rather than `node:fs/promises`, matching
// `theme.test.ts`, `stacking.test.ts` and `check-deleted.test.ts`, and for the
// reason stated there: eslint type-checks this directory against a program
// that resolves `node:fs` but not the `node:fs/promises` subpath.
import { readFileSync, readdirSync, statSync } from 'node:fs'
import { dirname, join, relative, resolve } from 'node:path'
import { fileURLToPath, URL } from 'node:url'

import { describe, expect, it } from 'vitest'

/** That every reusable component still has a story, and that the ones which do
 *  not are a decision somebody made in a diff.
 *
 * **The premise, checked before this was written.** The project's standing
 * constraint -- presentational components take props and render, state lives
 * in headless hooks -- was believed to be enforced structurally, on the
 * argument that "a component that cannot be rendered from props alone cannot
 * have a story". Nothing enforced it. `.storybook/main.ts` says so in its own
 * words: `storybook build` is deliberately outside `npm run verify` on sound
 * grounds, no addon runs stories, and `stories` is a glob over whatever
 * happens to exist. So a component that cannot be rendered from props alone
 * does not fail anything; it simply never gets a story, and nothing notices.
 * The 21 stories were a gallery, not a gate.
 *
 * **What this adds, and what it deliberately does not.** It does not build
 * Storybook -- that decision is sound and stays, and this file is not an
 * argument against it. It asserts one structural fact that costs a directory
 * walk: within the reusable layer, a component file is imported by some story.
 *
 * **Why coverage is by import rather than by filename.** A rule looking for
 * `Foo.stories.tsx` beside `Foo.tsx` would be simpler and would be wrong here
 * five times today: `Topic.stories.tsx` covers `TopicRow.tsx` and
 * `TopicDetail.tsx`, `Tabs.stories.tsx` covers `Choices.tsx`,
 * `CoursePanes.stories.tsx` covers `StageList.tsx` and `ArtifactList.tsx`.
 * Grouping two densities of one entity, or two primitives that share a skin,
 * onto one page is *the point* of those stories -- the comparison is what the
 * workbench is for -- and a check that punished it would be a check pushing
 * authors to write worse stories. An earlier hand audit of this same question
 * used filenames and reported four of those five as unstoried; that audit is
 * why this paragraph exists.
 *
 * **Why the scope is three directories and not `presentation/`.** Run over the
 * whole layer, this fires on 54 files -- most of the console. The spec's §6
 * already says why, and says it better than a list would: "Not `SessionView`,
 * not `CourseView`, not `ProjectList`: a story for a component that fetches
 * its own data is a story about the mock." The reusable layer is §9's Tier-0
 * and Tier-1, and it is exactly `common`, `entity` and `layout` on disk. A
 * check that fired on `SessionView.tsx` would be firing on correct code, which
 * `check-deleted.mjs` argues at length is how a check earns being switched
 * off. Screens are out of scope on purpose, not by oversight.
 *
 * The narrowing has a real cost and it is not hidden: a *new* reusable
 * primitive put in `presentation/session` instead of `presentation/common` is
 * invisible to this. That is a code-review question -- the same hole
 * `check-deleted.mjs` records for its stylesheet freeze -- and stating it is
 * the most a directory-scoped rule can do about it.
 *
 * Proved red by deleting `ProjectCard.stories.tsx`, which fails the first case
 * naming `presentation/entity/project/ProjectCard.tsx`. The first attempt at
 * proving it red deleted `Split.stories.tsx` instead and the suite stayed
 * green -- `Shell.stories.tsx` and `CoursePanes.stories.tsx` both import
 * `Split.tsx`, so it is genuinely still covered. That is the by-import rule
 * behaving correctly and it is worth writing down, because under a
 * filename-matching rule the same deletion would have failed and the failure
 * would have been wrong.
 */

const SRC = fileURLToPath(new URL('../src', import.meta.url))

/** The reusable layer, as directories under `src/`. Prefixes rather than a
 *  single `presentation/` because the argument above is about which files the
 *  rule can be true of, and that distinction lives in the directory names this
 *  project already sorted its components into. */
const SCOPE = [
  'presentation/common',
  'presentation/entity',
  'presentation/layout',
  // Added once three of its five files had a story and the remaining two had
  // an argument rather than a gap -- which is the order B142 asks for.
  // Widening a scope and filling it in the same commit is what turns an
  // allowlist of arguments into an allowlist of excuses.
  'presentation/shell',
]

/** Reusable components that have no story, each with the argument for why not.
 *
 * The list is the honest half of this check. Turned on with no allowlist it
 * would have needed 54 stories written first, or three within the scope above;
 * two of those three were written in the commit that added this file because
 * they were cheap and the stories say something jsdom cannot. The third was
 * `VirtualList`, exempted on the argument that a story for it would be a story
 * about its caller.
 *
 * **The list is empty, and the entry that emptied it was wrong rather than
 * satisfied.** The exemption said the component had "no visual states to
 * enumerate" and that its three claims -- re-measured `scrollMargin`, per-row
 * measurement, `getItemKey` -- were measurements a test suite should own. The
 * second half is right and is why `VirtualList.browser.test.tsx` exists. The
 * first half is not: all three claims have a *picture*, and it is the picture
 * that makes them recognisable. A window displaced by a header, a wrapped row
 * drawn over the row beneath, a list that reserves the right scroll and draws
 * nothing -- none of those is a caller's markup wearing a different name.
 *
 * Keeping the entry costs nothing and is exactly how a good check goes quiet,
 * so this note stays in place of it: an argument that a component cannot be
 * shown should be re-read as an argument that nobody has tried, and the
 * `why` sentence this list demands is what makes that re-reading possible at
 * all.
 *
 * **Removing an entry is how a story gets recorded as written**, which is the
 * same trade `check-deleted.mjs` makes with its stylesheet manifest and for
 * the same stated reason: a list of strings drifts, so each entry carries a
 * sentence and losing one is a line in a diff rather than a silent edit. An
 * entry kept after its story exists fails the second test below, so the list
 * cannot rot in the direction that matters. */
const ALLOWED: readonly { readonly file: string; readonly why: string }[] = [
  {
    file: 'presentation/shell/DecisionBar.tsx',
    why:
      'It renders from `useApprovalFeed`, which is a query hook over live approvals, and it' +
      ' returns `null` whenever nothing is pending -- so a story is either a mock of the feed' +
      ' or a blank page. A story about a mock is a story about the mock, which is the' +
      ' argument `ProjectCard.stories.tsx` makes for slots: the components that were' +
      ' extractable were extracted, and what is left here fetches. Write the story if the' +
      ' pending approvals ever arrive as a prop, and delete this entry with it.',
  },
  {
    file: 'presentation/shell/StreamProvider.tsx',
    why:
      'It renders `children` and nothing else. There is no visual state to enumerate,' +
      ' because there is no visual output -- it exists to put the event stream in context' +
      ' and to reconnect. `ConnectionBadge`, in the file beside it, is the surface that has' +
      ' a picture, and it takes its state as a prop precisely so it can have one. If this' +
      ' ever draws something, that is the change that also earns it a story.',
  },
]

const walk = (dir: string): string[] =>
  readdirSync(dir).flatMap((entry) => {
    const path = join(dir, entry)
    return statSync(path).isDirectory() ? walk(path) : [path]
  })

const isStory = (path: string) => path.endsWith('.stories.tsx')
const isTest = (path: string) => /\.(?:browser\.)?test\.tsx$/.test(path)

/** What counts as a component, stated as a rule rather than as a judgement.
 *
 * A `.tsx` file that exports at least one PascalCase *value* -- `export const
 * Name =` or `export function Name(` -- and is neither a story nor a test.
 *
 * The three edge cases it was run against, because a rule is only as good as
 * what it declines:
 *
 * - **Hooks and helper modules fall out for free.** `useSessionForest` and
 *   `useStream` are camelCase, so `SessionTree.tsx` -- which exports nothing
 *   else -- is correctly not a component. That was a surprise: it is named
 *   like a component and is a hook module.
 * - **`export type` and `export interface` do not count.** `VirtualList.tsx`
 *   exports `RowPosition`, `primitives.tsx` exports `ButtonTone`; a file whose
 *   only PascalCase exports are types is not a component and is not asked for
 *   a story.
 * - **Multi-component files count once.** `primitives.tsx`, `content.tsx` and
 *   `widgets.tsx` each export several. The unit here is the *file*, because
 *   the unit a story imports is the file, and asking per-export would demand a
 *   separate story for `Loading` -- a one-line div -- which is the kind of
 *   busywork that gets a check deleted.
 *
 * `.tsx` and not `.ts` deliberately: JSX in this repository is only ever in a
 * `.tsx`, so the extension already draws the line between a component and a
 * module of pure functions without this having to parse anything. */
const COMPONENT_EXPORT = /^export (?:const|function) [A-Z][A-Za-z0-9]*\b/m

/** Every source file a story pulls in by path, resolved to absolute.
 *
 * Both spellings, because a check that missed one would fail on a story that
 * had done nothing wrong: relative (`./Foo.tsx`, which all 23 use today) and
 * the `@presentation` alias `vite.config.ts` defines, which nothing uses yet
 * and which the next author has no reason to avoid. */
const importsOf = (source: string, from: string): string[] => {
  const paths: string[] = []
  // `[1]!` rather than a destructured binding: the group is not optional in
  // either pattern, so `string | undefined` is the type system describing
  // `matchAll` in general rather than anything reachable here.
  for (const match of source.matchAll(/from '(\.[^']*\.tsx)'/g))
    paths.push(resolve(dirname(from), match[1]!))
  for (const match of source.matchAll(/from '@presentation\/([^']*\.tsx)'/g))
    paths.push(join(SRC, 'presentation', match[1]!))
  return paths
}

const files = walk(join(SRC, 'presentation'))

const covered = new Set(
  files.filter(isStory).flatMap((path) => importsOf(readFileSync(path, 'utf8'), path)),
)

const components = files
  .filter((path) => path.endsWith('.tsx') && !isStory(path) && !isTest(path))
  .filter((path) => COMPONENT_EXPORT.test(readFileSync(path, 'utf8')))

const inScope = components.filter((path) =>
  SCOPE.some((prefix) => relative(SRC, path).startsWith(prefix)),
)

describe('the story manifest', () => {
  it('has a story for every reusable component, or an argument for why not', () => {
    const allowed = new Set(ALLOWED.map(({ file }) => file))
    const missing = inScope
      .filter((path) => !covered.has(path))
      .map((path) => relative(SRC, path))
      .filter((name) => !allowed.has(name))
      .sort()

    // The message is the whole value of this assertion on the day it fires, so
    // it names the two ways out rather than only the failure. A check whose
    // output is "expected [] to equal ['presentation/common/Foo.tsx']" gets
    // read as an obstacle; one that says what to do gets read as a rule.
    expect(
      missing,
      `${String(missing.length)} reusable component(s) have no story. Either write one -- a` +
        ` \`.stories.tsx\` anywhere under \`src/presentation\` that imports the file is enough,` +
        ` and grouping several components onto one page is encouraged -- or add an entry to` +
        ` \`ALLOWED\` in scripts/stories.test.ts saying why this one cannot be rendered from` +
        ` props alone. Per docs/component-system-spec.md §6, a component that cannot get a` +
        ` story is telling you it is not a component yet.`,
    ).toEqual([])
  })

  it('holds no allowlist entry that a story has since covered', () => {
    // The direction that rots quietly. A missing story fails loudly; an
    // *unneeded* exemption fails nothing at all and quietly widens the hole for
    // the next component that lands beside it. This is what makes the list
    // shrink rather than merely stop growing.
    const stale = ALLOWED.filter(({ file }) => covered.has(join(SRC, file))).map(({ file }) => file)

    expect(
      stale,
      `These are exempted in \`ALLOWED\` and now have a story. Delete their entries from` +
        ` scripts/stories.test.ts: that deletion is how the gap gets recorded as closed.`,
    ).toEqual([])
  })

  it('holds no allowlist entry for a file that is gone or out of scope', () => {
    // Third failure direction, and the one a rename causes. An entry naming a
    // moved or deleted file exempts nothing, so it reads as a known gap that is
    // in fact fixed -- or, worse, keeps exempting a name a future file could
    // reuse.
    const names = new Set(inScope.map((path) => relative(SRC, path)))
    const orphaned = ALLOWED.filter(({ file }) => !names.has(file)).map(({ file }) => file)

    expect(
      orphaned,
      `These are exempted in \`ALLOWED\` and are not reusable components on disk -- deleted,` +
        ` renamed, or moved out of ${SCOPE.join(', ')}. Update or remove the entries.`,
    ).toEqual([])
  })

  it('every allowlist entry carries an argument rather than a name', () => {
    // The list is only worth having if its entries are readable as decisions,
    // which is `check-deleted.mjs`'s stated reason for pairing every rule with
    // a `why`. A one-word reason is how a list of arguments decays into a list
    // of names. Reverted, this test passes -- nothing else reads `why` -- and
    // that is precisely why it is here.
    for (const { file, why } of ALLOWED) expect(why.length, file).toBeGreaterThan(120)
  })

  it('finds the components it claims to be checking', () => {
    // A guard on the rule itself, not on the codebase. `COMPONENT_EXPORT` and
    // the walk are the parts that can be wrong silently: a regex that matched
    // nothing would report zero missing stories and look exactly like a green
    // gate. Proved red by breaking the regex, which drops this to 0.
    expect(inScope.length).toBeGreaterThan(10)
    expect(covered.size).toBeGreaterThan(10)
  })
})
