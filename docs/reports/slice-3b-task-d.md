# Slice 3b, task D — the seed form off `research.css`

`SeedForm.tsx` renders on utilities now. Files written: `SeedForm.tsx` and two
assertions in `SeedPanel.test.tsx`. `QueueHeader.tsx` was **not** touched — it
mounts `SeedPanel` and writes none of these class names, so nothing about the
rewrite reached it. `research.css` is untouched, as briefed; all six rules are
left behind for task E.

## The five rules, and what replaced each

| Rule (`research.css`) | Declared | Replaced by |
| --- | --- | --- |
| `.seed-panel` :528 | `display:flex; flex-direction:column; gap:8px` | `flex flex-col gap-[8px]` |
| `.seed-form` :534 | `display:flex; align-items:center; gap:8px` | `flex items-center gap-[8px]` |
| `.seed-form label` :540 | `font-size:var(--t-xs); color:var(--fg-dim)` | `text-xs text-fg-dim`, on the `<label>` |
| `.seed-input` :545 | `flex:1` | `flex-1` (`1 1 0%`, which is what the `flex:1` shorthand expands to) |
| `.seed-status` :549 | `margin:0; font-size:var(--t-xs); color:var(--fg-dim)` | `m-0 text-xs text-fg-dim`, hoisted to a `STATUS_LINE` constant shared by the running line and the last-run line |
| `.seed-failed` :555 | `color:var(--k-failure)` | `text-k-failure`, composed over `STATUS_LINE` with `clsx` |

Six rules, not five: `.seed-form label` is a descendant selector the brief's
count folded into `.seed-form`.

`.seed-failed` was checked rather than assumed: it is a colour override only,
`--k-failure` (`tokens.css:97`, `#f4736b`), and `text-k-failure` is the same
token — the identical substitution `DocumentBrowser`'s dropped-document line
already makes. `--fg-faint` was not reached for anywhere; the dim tone stays
`--fg-dim`, which is what both status rules declared.

No borders were introduced, so `CLAUDE.md`'s `border-0`-plus-directional rule
had nothing to apply to here. `input` stays a class — it is the shared field
style from `composer.css`, the same call `DocumentBrowser` made in 3a.

## What could not be preserved as-is

`.seed-form label` was a descendant rule: it dressed *any* label put inside the
form. As a utility it dresses this one label. Nothing else is in the form
today, so the rendering is identical; the difference is that a second label
added later inherits nothing. Said here rather than discovered later.

## Tests

`SeedForm.test.tsx` asserted no class names at all (roles, labels and rendered
text throughout) and needed no edit. `SeedPanel.test.tsx:203` and `:222` both
asserted `toHaveClass('seed-failed')`; both now assert
`toHaveAttribute('data-failed', 'true')` against a new `data-failed` on the
last-run line. The attribute carries the state and the utility draws it, so the
test no longer breaks when the dressing is restyled. **Neither assertion would
pass with this change reverted** — the old markup emits no `data-failed`.

Nothing here is a computed style: `data-failed` is an attribute jsdom sees, and
the layout rules (`flex`, `gap`, `flex-1`) were not asserted before this change
and are not asserted now. No `*.browser.test.tsx` was added, and no measurement
is claimed.

```
cd frontend && flock /tmp/rt-vitest.lock npx vitest run \
  src/presentation/research/SeedForm.test.tsx src/presentation/research/SeedPanel.test.tsx
 Test Files  2 passed (2)
      Tests  13 passed (13)
```

`npm run verify` was not run — task F owns it.

## No `seed-*` class name remains

```
$ grep -rn "seed-" frontend/src/
src/styles/research.css:528:.seed-panel {
src/styles/research.css:534:.seed-form {
src/styles/research.css:540:.seed-form label {
src/styles/research.css:545:.seed-input {
src/styles/research.css:549:.seed-status {
src/styles/research.css:555:.seed-failed {
src/styles/tokens.css:280:   underneath. Any field without a class of its own -- `.seed-input` sets only
src/presentation/research/SeedPanel.test.tsx:203:  // `data-failed` and not the colour class: the tone moved from `.seed-failed`
src/presentation/research/SeedForm.tsx:55:        {/* The label's dressing was a descendant rule (`.seed-form label`) and
src/presentation/research/SeedForm.tsx:64:            this slice's to dissolve. `flex-1` is what `.seed-input` set — the
src/presentation/research/SeedForm.tsx:93:/** What `.seed-status` set. `m-0` because this build imports no preflight and
src/presentation/research/SeedForm.tsx:98:/** `text-k-failure` and not `text-fg-dim`: `.seed-failed` overrode the dim
src/presentation/research/SeedForm.tsx:104: * duty: `SeedPanel.test.tsx` used to assert `seed-failed`, and a test that
```

Every hit outside `research.css` is prose in a comment. No `className` in
`frontend/src` writes a `seed-*` name.

## One thing for task E

`tokens.css:280` uses `.seed-input` as its worked example of "a field without a
class of its own": *"`.seed-input` sets only `flex`, and a bare `<input>` sets
nothing"*. That sentence goes stale the moment `research.css` is deleted. Not
edited here — `tokens.css` is task E's file (it already owes the `--z-sticky`
comment at :168–170 an update), and two agents editing it is the merge the plan
avoided. The example still holds if it names the utility instead: the field
carries `input flex-1`, and `flex-1` alone would still leave it unreadable.
