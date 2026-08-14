# Increment C, slice 2 — HOLDER un-nested, MATERIAL gains the workspace, and five stylesheets that were supposed to die

## The headline

**Not one of the five stylesheets §2.2 names dies, and the reason is structural
rather than incidental: this slice re-parents markup it does not rewrite.**
`conversation.css`, `timeline.css`, `composer.css`, `workspace.css` and
`scrub-bar.css` declare 131 class names between them, and **every one is still
reached** — by the same five components, rendering the same markup, in two
places instead of one. Slice 1 found roughly nine tenths of `course.css` alive
against the same claim; this is the same finding at the limit, ten tenths of
five files.

The second finding is smaller and is a live defect: **three shipped
single-side borders draw nothing**, one of them written by slice 1. Filed as
`BACKLOG.md` B55 rather than fixed here, because each is in a region this slice
does not own.

## What the sweep enumerated, and how

Inverted, as the brief asked — walked out from `ProjectView` and `SessionView`
to what they mount, then asked what each component *writes*. The grep direction
would have got most of `conversation.css` wrong: `` `msg-${role}` ``,
`` `seg-${kind}` `` and their neighbours are composed and have no literal to
find.

| Stylesheet | Names declared | Written by | After this slice |
|---|---|---|---|
| `workspace.css` | 23 | `FileList`, `FileView`, `Segments` (`pre.code`) | MATERIAL `Workspace` tab **and** `#/s/`'s workspace pane |
| `timeline.css` | 33 | `Timeline` | HOLDER's log section **and** `#/s/`'s timeline pane |
| `conversation.css` | 42 | `Conversation`, `Segments`, `Compaction` | HOLDER's transcript section **and** `#/s/`'s conversation pane |
| `composer.css` | 16 | `Composer` | pinned in HOLDER **and** `#/s/`'s pane footer |
| `scrub-bar.css` | 17 | `ScrubBar` | top of HOLDER **and** top of `#/s/` |

Every component in the middle column survives, unmodified, and each now has two
mounts rather than one. The slice moves *containers*; the contents are the same
five components they always were.

`check-deleted.mjs` is therefore unchanged in both directions: nothing left
`STYLESHEETS` (still 22) and no rule was added, because a rule forbidding
`/^\.files\b/m` — which §2.2 asks for — would forbid a class this slice keeps
writing. The 33 deletion rules hold.

### §5.1's combinator hazard, checked one by one

Ten `>` selectors across the five files, plus the four in `responsive.css` that
name markup here. None goes void:

- `timeline.css:80,265` (`.ev > .ev-cell:first-child`, `.head-marker > …`) —
  internal to `Timeline`'s rows, untouched.
- `conversation.css:56,60,64,194,200,203,340,348` — all `.msg-body > .md`,
  `.run > .disc-head`, `.discarded > .disc-head` and the `:has(> .md)`. §2.2
  calls these "claims about markup this slice moves" and singles the file out as
  the one to grep first. They are claims about markup *inside* `Segments`, which
  this slice does not open. All eight hold.
- `composer.css:92`, `workspace.css:54` — internal to `Composer` and to the
  `.files` wrapper, which `WorkspacePanel` still renders around `FileList`
  precisely so that `.files > [role='listbox']:focus-visible` keeps matching.
- `responsive.css:31,46` (`.lay-split[data-split='session'] > [data-pane=…]`) —
  these **narrow rather than break**. The session split still exists on `#/s/`,
  which is the route the middle-breakpoint arrangement was written for; what
  they stop reaching is the project page, which no longer has a session split
  and never wanted that arrangement. Nothing to delete.
- `responsive.css:112,113` (`ul.tree ul > li`) — the tree, untouched.

`responsive.css:66`'s `.files { max-height: 200px }` below 820px is worth
recording as the one rule whose *meaning* changed: it now caps the file list
inside a MATERIAL tab rather than inside a session pane. Still correct, still
matching, but it is a per-view rule in the shared breakpoint file that now
dresses a different view — §5.1's hazard in the form where the grep finds
nothing wrong.

## Where the plan did not match the code

1. **§2.2's "stylesheets that die" list is empty in practice.** See above. The
   plan's own hedge — "but only the ones whose markup this slice actually
   rewrites" — is the correct rule and the answer it gives is *none*. What the
   plan mispredicted is the shape of the slice: it assumed dissolving
   `SessionView`'s `Split` meant rewriting the session's contents, and it means
   moving them.

2. **§2.2's `check-deleted.mjs` additions would each forbid a live class.**
   `/^\.msg-body\b/m`, `/^\.run\s*>/m` and `/^\.files\b/m` are all written after
   this slice, the last of them by `WorkspacePanel`. Adding any of the three
   would fail `npm run verify` on the commit that added it.

3. **`regionOf('file')` moved to MATERIAL, and slice 1's argument for HOLDER was
   about storage rather than about reading.** The brief decided this and the
   code agrees for a reason the brief does not give: keeping it in HOLDER means
   a file list, a file viewer, a transcript and a composer stacked in one
   region's width — four scrollers where the brief asks for two. The docstring
   now argues MATERIAL rather than contradicting the code.

4. **`SessionView` was navigating off the project page, and the plan does not
   mention it.** `SessionView.tsx:85` wrote `sessionHref` for every scrub and
   every file open. Mounted inside HOLDER by slice 0, that meant clicking an
   event in a region rewrote the address to the standalone `#/s/` route —
   discarding QUEUE and MATERIAL to look at the event you just clicked. Nothing
   caught it because HOLDER *was* a whole session view, so leaving for another
   one looked like nothing. `useSessionScreen` takes `href` as a parameter now
   and the project page writes `projectHref(…, sessionSelection(…))`, which is a
   deliberate departure from the brief's "moves here unchanged": moving it
   unchanged would have shipped a HOLDER region that ejects the reader on first
   click.

   The consequence is a second rule worth knowing: on the project page a scrub
   and a file-open both write a `session` selection carrying `at` and `path`,
   because that is the only selection the route grammar gives those two fields.
   So `materialTab` treats a session selection with a non-null path as the
   `file` facet — without that, opening a file from the Workspace tab would
   close the tab it was opened from. `#/p/<id>/file/<path>` still arrives
   through the ordinary arm and is still a linkable entry point.

5. **`.view-session` is written by markup and declared by no stylesheet.**
   `SessionView.tsx` puts it on its root twice; nothing in `src/styles/` selects
   it. Left alone rather than swept, because it is not this slice's and removing
   it is a separate one-line commit with its own argument.

6. **Three single-side borders draw nothing** — `QueueHeader.tsx:75`,
   `Drawer.tsx:163`, `DecisionBar.tsx:44`, all `border-{b}` with no
   `border-style` anywhere, all invisible to every gate. `BACKLOG.md` B55, with
   the `check-tailwind.mjs` rule that would have caught all three.

## What this slice actually changed

- **`session/use-session-screen.ts` (new).** Every effect, callback and derived
  value from `SessionView.tsx:34-168`, with the docstrings verbatim where the
  code is unchanged. `sessionId` is nullable and every effect no-ops on null,
  because the project page calls it at the top of a component that may have no
  holding session.
- **`session/panels.tsx` (new).** `TimelinePanel`, `WorkspacePanel`,
  `ConversationPanel`, plus `TimelineFeed` and `ComposerPanel` — the last two
  separate because both arrangements pin them *outside* a scroller — and the
  three meta-string helpers.
- **`SessionView.tsx` keeps its `Split`**, and is now the arrangement and
  nothing else. `use-session-panes.ts` and the `session` preference group
  survive with it, per §3.2. `App.tsx:128` untouched.
- **HOLDER is a stacked column**: scrub bar, a log section, a transcript
  section, a pinned composer. No `Split`, no `Pane`, no new stylesheet,
  utilities only. Each section carries `aria-label` and a small `SectionHead`,
  because un-nesting would otherwise have silently cost two landmarks a
  screen-reader user had yesterday.
- **MATERIAL gains `Workspace`, second of five.** `DEFAULT_MATERIAL` stays
  `artifact`. The empty state for a project nobody is holding now has two
  halves, HOLDER's and the Workspace tab's.

## Verification

`npm run verify` green. `npm run test:browser` green at **15 files / 46 tests**
(slice 1: 14 / 42). `uv run ruff check .` and `uv run ruff format --check .`
green repo-wide. `pytest` not run — nothing here is Python.

Bundle **284.7 kB** of 512 gzipped, against slice 1's 283.3 kB: **+1.4 kB**, and
it is honest rather than surprising — the workspace pair now renders on two
pages and the hook and panel modules are new files, none of it deleted content.
`check-deleted` holds at 33 rules with 22 stylesheets frozen.

### Every browser assertion, proved red

The recorded failure text in each docstring is the real one. Four inversions:

| Inversion | Fails | At |
|---|---|---|
| HOLDER's `Pane` loses `scroll="regions"` | claim 1 | `expected 'block' to be 'flex'` |
| the log's scroll box loses `overflow-auto` | claim 1 | `expected 'visible' to be 'auto'` |
| the transcript section `flex-1` → `shrink-0` | claim 2 | `expected 491.140625 to be less than 40` |
| a second `Split` inside HOLDER | claims 2, 5 | `expected 637.9375 to be greater than 898`; `expected …(2) to have a length of 1 but got 2` |
| `use-project-panes.ts`'s `GROUP` → `'session'` | claim 3 | `expected [] to deeply equal [ 'queue' ]` |

**One assertion was thrown away for not discriminating, and it is the same one
slice 1 threw away.** Claim 1 first asserted `body.scrollHeight <=
body.clientHeight` — "the pane body does not scroll" — and dropping
`scroll="regions"` left it green. The fixture's empty log and empty transcript
do not fill 900px, so a body that *is* a scroller has nothing to overflow with
and measures identically to one that is not. It asserts the body's computed
`display` and `overflow-y` instead, which jsdom answers `''` to whatever the
markup says. Slice 1 recorded exactly this trap about exactly this fixture and
the lesson did not transfer until it happened again; that is worth more than the
assertion was.

**Claim 2 of the old file was deleted rather than rewritten.** It asserted two
grid templates on two `.lay-split` elements, neither overwriting the other.
There is one split on the page now, so the claim has no subject — the mechanism
it ruled out cannot occur. The new claim 5 asserts the count that makes that
true. The deletion is noted in the file itself.

**`ProjectView.test.tsx` gained an assertion that is not reassurance**:
`FACETS.filter(f => regionOf(f) === 'holder')` equals `['session']`. Reverted,
`file` rejoins it and the count is 2.

## What is still not measured

- **Focus rings against §5.2's geometry, again.** Slice 1 deferred this to
  "slice 2 or 3, whichever rewrites that markup". This slice rewrote no rows: the
  file list keeps `workspace.css:45`'s measured inward ring, the timeline keeps
  its inset `box-shadow`, and the topic and merge lists §5.2 names as live
  exposures are still in QUEUE's markup, untouched. The two *new* scrollers —
  HOLDER's log box and the Workspace tab panel — hold content whose own rings
  are already drawn inward. So the gap is unchanged rather than widened, and
  slice 3 inherits it.
- **The three region widths.** `PROJECT_TRACKS`'s numbers are still chosen
  rather than measured, and its docstring says the measurement waits for a page
  with real content. HOLDER now has real content and MATERIAL has one more tab;
  the number that matters — where each region stops being usable — is still not
  taken. Slice 3 finishes MATERIAL and is the honest place for it.
- **Anything below `--bp-wide`.** Every assertion here is at 1440×900, which is
  what `vite.config.ts` sets. HOLDER's stacked column has never been looked at
  in the 821–1180px band or below 820px, where `layout.css` stacks the panes and
  the column becomes a row of its own height.
