# Increment C, slice 3a — MATERIAL's three static shelves, and why `research.css` cannot die from a MATERIAL slice

## The headline

**Neither stylesheet §2.3 names dies, and this time the reason is not the one
slices 1 and 2 found.** Slices 1 and 2 both failed to kill a stylesheet because
they re-parented markup rather than rewriting it. This slice _does_ rewrite
markup — 35 class names are genuinely deleted, 22 from `course.css` and 13 from
`research.css` — and the files live anyway, because **what remains in both is
QUEUE's, and QUEUE is not this slice's region.**

- `course.css` keeps four families: the rail, the worker roster, the extraction
  pane, the autonomy panel. All four are in QUEUE.
- `research.css` keeps the topic list (five components, ~40 names, in QUEUE),
  the seed form (in the queue header), and the graph (MATERIAL's, deliberately
  deferred — see scope).

So the correct statement is stronger than "the plan was optimistic": **no
MATERIAL-only slice can kill either file**, whatever it rewrites. `TopicList`
is the entanglement the brief pointed at, and it settles the question rather
than merely complicating it.

The second finding is a live defect this slice fixes, found by the enumeration
the brief asked for: **`Findings` has been rendering five undressed chips since
PR #169.** Third, an audit that landed mid-slice found four linkable facets
whose ids never reached a renderer; three of the four are in this slice's scope
and are threaded now.

## Scope, and why it is a half

The plan's §2.3 bundles five facets, a shared reader, three component
deletions and the death of `research.css`. Priced against the code:

| §2.3 asks for                                                            | What the code says                                                                                                                                                                                                                                                                                                 |
| ------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| "one reader, one selection model, one filter" for five facets            | The five share nothing but a scroller. Documents have a virtualizer and a text filter; artifacts are a declared list with provenance rows; findings are a severity table; the graph is a lazy canvas; topics are a queue with a status dialog. A common reader would be a switch statement wearing an abstraction. |
| delete `research/DocumentBrowser.tsx` "if the shared reader subsumes it" | It does not, so the file stays and is rewritten in place.                                                                                                                                                                                                                                                          |
| delete `course/Artifacts.tsx`'s page chrome                              | There is none left. Slice 0 took it; `Artifacts.tsx` is rows.                                                                                                                                                                                                                                                      |
| `research.css` dies "effectively whole"                                  | It cannot. See the headline.                                                                                                                                                                                                                                                                                       |
| `check-deleted.mjs` loses `'research.css'` from `STYLESHEETS`            | It does not. The array is still 22.                                                                                                                                                                                                                                                                                |

**This is two slices, and this is the first.** The boundary is _what MATERIAL
renders statically_: the Artifacts, Findings and Documents tabs. Left for 3b:

- **The graph.** The plan itself says "graph last", and it is 940 lines across
  four components whose correctness is a canvas measurement. Rewriting it in a
  slice that also rewrote three shelves would be the slice nobody can review.
- **The topic list.** QUEUE's, and pulling it in means `TopicList`, `TopicQueue`,
  `TopicStatusDialog`, `SubQuestions`, `TopicDocuments` and the §3.3
  demodalisation — a second slice's worth of work with a second slice's
  argument. Deferring it defers `research.css`'s death, which was going to be
  deferred regardless: the graph and the seed form are also still in it.
- **The rail, the roster, the extraction pane, the autonomy panel.** QUEUE's,
  and the reason `course.css` outlives this.

The half is coherent on its own terms: three tabs a reader can open today are
rewritten, dressed and linkable, and no region is left half-migrated.

## What the sweep enumerated, and how

Inverted, as the brief asked — walked out from `ProjectView`'s five `TabPanel`s
and from QUEUE's contents to what each component _writes_.

**§5.1's combinator hazard did not bite, and the reason is that slice 1 already
paid it.** The plan's §5.1 lists seven `>` selectors in `research.css`, all
`.research-rail > …` / `.research-workbench > …`, as slice 3's to invalidate.
There are **zero** `>` combinators in `research.css` today: slice 1 deleted all
of them in the same commit as `ResearchView`, along with their four
`responsive.css` counterparts, and the file's header comment records it. The
plan was measured at `f87443b`, which predates that. `course.css` has two left
and both are `.autonomy-disclosure[open] > …`, untouched here. `responsive.css`
names no artifact, finding or document selector at all. **Nothing this slice
rewrote was claimed by a combinator anywhere.**

What each remaining family writes, after this slice:

| Stylesheet     | Names before | Deleted here                                            | Left, and whose                                                                                                                                                      |
| -------------- | ------------ | ------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `course.css`   | ~98          | 22 (`Artifacts`, `ArtifactList`, `Findings`)            | `StageRail` 13 + `rail-${status}` + `chip-${tone}`; `WorkerList` 9 + `worker-dot-${kind}`; `ExtractionPane` 12; `AutonomyPanel` 16; the drawer block — **all QUEUE** |
| `research.css` | ~86          | 13 (`DocumentBrowser`, `DocumentRow`, `DocumentReader`) | topics ~40 (QUEUE), seeding 6 (queue header), graph ~35 (MATERIAL, deferred)                                                                                         |

The composed-name trap the brief warned about is live in what is left, not in
what went: `rail-${status}`, `worker-dot-${kind}`, `chip-${tone}` all still have
no literal to grep. What _this_ slice deleted was mostly literal, with two
exceptions that a grep would have got wrong in the other direction —
`finding-${severity}` (five rules, one template literal) and the four
`.chip-*` artifact tones, which are written by `Chip`'s `tone` prop and never
appear as a class in any component file.

## Where the plan did not match the code

1. **§2.3's stylesheet claim, and the reason it is structural.** Above.

2. **§5.1's `research.css` combinator inventory is already spent.** Seven
   selectors, zero remaining, deleted by slice 1. The hazard was real and was
   paid one slice earlier than the plan expected.

3. **`Findings` has been rendering five undressed chips since PR #169, and the
   fix for one orphan created another.** `course.css` was the wrong home for
   `.chip-invariant` and its four siblings, so they moved to `SEVERITY_DRESS` in
   `GateReview.tsx` — on the stated argument that `GateReview` was the only
   caller. It was not. `course/Findings.tsx` renders `<Chip tone={severity}>`
   for exactly those five strings, and has since been asking for classes no
   stylesheet declares: five severities collapsed into one grey, on the project
   page's Findings tab, with no error and no failing test. **This is the exact
   defect the move was made to prevent, reintroduced by the move.** The map is
   `common/findings-copy.ts` now and both callers read it.

   Worth naming the general shape, because it will happen again: _a rule
   rescued from a dying stylesheet has to be rescued for every writer of it, and
   "the only caller" is a claim that needs the same enumeration the sweep does._

4. **`.muted` is written by 14 elements and declared by no stylesheet.** Not
   `course.css`, not `base.css`, not anywhere in `src/styles/`. Four of the 14
   were in `Artifacts.tsx` and are `text-fg-dim` now, which is what the name
   meant and what the sibling `.artifact-type` already was — **a deliberate
   visual change, not a no-op, and it is the one place this slice changes how
   something looks on purpose.** The other ten are in `StageRail`, `WorkerList`
   and `RunPanel`, all QUEUE, all still rendering as undimmed body text. Left
   alone rather than swept: it is not this slice's markup, and the sweep for it
   belongs with whoever rewrites the rail.

5. **`.artifact-missing` was a class with no rule, kept as "the hook anything
   later would hang off".** It is `data-missing` now. A class with no
   declarations sitting in a file of classes with declarations cannot be told
   from one whose rule was lost, which is the whole failure `check-deleted.mjs`
   exists about.

6. **`Tooltip.stories.tsx` wrote `.prov-src` and `tone="inferred"`** — one
   already dead, one dying here. The story now carries the same utility strings
   the component does, copied rather than imported: a story that imported a
   component's private dressing constants would stop being a sample of the
   markup and start being a second renderer of it.

## The linkability audit, folded in

An audit landed while this slice was being written: four facets (`topic`,
`doc`, `artifact`, `finding`) parse an id, land on `selection`, reach the right
region — and are then mounted with `projectId` or `course` alone, each component
holding its open item in its own `useState`. This invalidates plan §1's "a
topic, a stage and an artifact are already linkable states … a precondition that
is met". Only the stage half was true.

**Three of the four are in this slice's scope and are threaded now.**

- **`doc`** — the one that was a _shipped broken link_.
  `presentation/ask/CitationList.tsx:44` emits `#/p/<id>/doc/<sourceId>` and its
  comment says the point is to keep the reader on the project page; following it
  opened the Documents tab with nothing read, so a reader who clicked a citation
  got an unfiltered corpus and had to find the source by hand. `useDocuments`
  takes the open document and an `onOpen` callback now; `ProjectView` writes the
  selection. The filter deliberately stays local state — a filter is _how_ you
  are looking and an open document is _what_ you are looking at.
- **`artifact`** — `ArtifactList` takes `open` and marks the row whose
  `slot.path` matches, with `aria-current` as well as a fill, because "the one
  you followed a link to" is a fact a screen reader needs.
- **`finding`** — matched on `finding.check`, which is the only stable id a
  finding has; the array index is not, because the list is recomputed against a
  growing course. Two findings from one check both mark, which is the honest
  answer for a link that names a check.

**`topic` is deferred with the rest of the topic list**, and is still `useState`
at `use-topic-queue.ts:31`. Nothing links to it today, so unlike `doc` it is a
gap rather than a broken link — but it is a gap, and slice 3b owns it.

Three tests were added and each fails if the threading is reverted, because none
of them clicks anything: two in `App.test.tsx` through the real route (asserting
`aria-current` on the row, for the reason the existing stage test asserts
`aria-expanded` — a prop cannot see a route that reached the page and not the
list), and one in `DocumentList.test.tsx` that renders with the document already
open. `App.test.tsx`'s `COURSE` fixture gained one artifact and one finding so
the ids have something to land on; every pre-existing assertion in that file is
about rail rows, tabs and regions and can see neither.

## Verification

**No gate was run locally, and no test was run locally.** A benchmark had this
machine and CPU time was not mine to spend, so `npm run verify`, `pytest`,
`ruff` and `npm run test:browser` were all left to CI. The only command run was
`npm run build`. **CI is the first thing to execute any assertion in this
slice.** `BACKLOG.md` B54 is the precedent for recording an unverified claim in
those words rather than in the words of a claim that was checked.

What _was_ checked, by reading rather than by running:

- **Every utility introduced emits a rule.** The built `index.css` was grepped
  for all 41 of them, including the arbitrary ones (`py-[8px]`,
  `outline-offset-[-2px]`, `border-[#24365a]`, `leading-[1.65]`, `[font:inherit]`,
  `basis-[340px]`). All present. This is what `check:tailwind` would have said,
  read off the same artifact it reads.
- **The single-side borders resolve in the right order.** `.border-0`
  (`border-width:0`) is emitted at byte 4989, `.border-b` at 5121, `.border-l-2`
  at 5271, `.border-solid` at 5346 — so the zero lands first, the one edge
  overrides it, and the style applies to all four sides where three have no
  width. Both halves present in all three places (`Artifacts`'s row,
  `Findings`'s `ROW`, `DocumentRow`).
- **`check-deleted`'s new rules match nothing live.** The seven patterns added
  under phase `C3` were run by hand over every comment-stripped file in
  `src/styles/`: zero hits, in both directions (the six `C1` patterns still
  match nothing either).
- **The bundle.** Measured by gzipping each built asset and the same asset at
  `HEAD`: **+0.24 kB total** (283.67 → 283.91 by this measurement's own
  compressor), of which `app.js` is +0.40 and `index.css` is −0.16. The `app`
  bucket, which is what the budget gates, is comfortably under its 80 kB. The
  shape is honest: 35 CSS rules left and the utility strings that replaced them
  are longer, so a rewrite of this kind is roughly size-neutral by construction
  rather than by luck.

### The browser test, and what it is for

`presentation/course/shelf-borders.browser.test.tsx` is new and asserts the
thing `CLAUDE.md` says no gate catches: that an artifact row draws a bottom edge
and no other, that the last row's bottom edge is correctly absent, and that a
finding row draws a 2px _left_ edge **in its severity colour**. jsdom answers
all four border widths with the initial value whatever the class attribute
holds, so this cannot live in the fast suite.

**It was not proved red.** Its docstring says so and says what would make it
red, which is the substitute available: dropping `border-0` takes
`borderTopWidth` from 0 to ~3px, dropping `border-solid` takes
`borderBottomWidth` from 1px to 0.

`DocumentBrowser.browser.test.tsx` was rewritten rather than replaced. The
measured focus-ring geometry in its table is the original and still stands — the
rules moved from `research.css` to a `RING_INWARD` constant and nothing about
the numbers changed. What moved is the two selectors, from class names to
`[data-document-scroll]` and `[data-document-row] > button`. Its docstring
records that this rewrite was not re-proved red.

## What is still not measured

- **Focus rings against §5.2's geometry, for the third slice running.** This
  slice did rewrite two row lists, and the document row's inward ring came with
  it intact — but `.topic-list` (`research.css:206`, `padding: 0`, rows falling
  through to the global outward ring) and `.extraction-merge-list`
  (`course.css`, same shape) are the two live exposures §5.2 names, and both are
  in QUEUE's markup, untouched. The artifact and finding rows this slice wrote
  are not focusable and so cannot reproduce it. The gap is unchanged rather than
  widened, again, and slice 3b inherits it again.
- **The three region widths.** `PROJECT_TRACKS`'s numbers are still chosen
  rather than measured. Slice 2 said slice 3 was "the honest place for it"; this
  is half of slice 3 and the measurement still wants a page with the graph on
  it.
- **Anything below `--bp-wide`.** Everything here is reasoned at 1440×900 and
  none of it was rendered at all.
- **Whether the `.muted` sweep changes anything visible in QUEUE.** Ten elements
  are asking for a class that does not exist. Nobody has looked at what they
  should be.
- **The `doc` half of `CitationList`'s link end to end.** The unit test proves
  the id reaches the reader; nobody has clicked a citation in a browser.
