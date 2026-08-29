# Working in this repository

What the code cannot tell you. Everything here was learned by getting it
wrong; each entry says what the mistake looked like, because the shape of the
failure is the part that makes it recognisable next time.

`README.md` is for people using this project. `BACKLOG.md` is for work
deliberately deferred, with enough detail to pick up. This file is for the
rules that hold across all of it.

## Verification

**There are four gates, and passing three is not passing.**

```
uv run ruff check .
uv run ruff format --check .
uv run pytest
cd frontend && npm run verify
```

They are separate CI jobs, and the two ruff commands run over the *whole
repository* rather than the files you touched. The failure mode is specific
and has happened more than once: a change is verified with `npm run verify`
and `pytest`, both pass, and CI fails on an unsorted import in a Python test.
`npm run verify` covers no Python, and `pytest` covers no formatting.

`npm run verify` chains format:check, lint, typecheck, test:coverage, build
and a bundle-size budget. Run it rather than the individual commands -- the
prettier check and the size budget are only in the chain, and they are the two
that fail in CI.

**The built console is not committed, and was until 2026-08-18.** If you are
reading a commit older than that, `research_team/interfaces/web/static` is
tracked, `.gitattributes` hands it to a `merge=ours` driver, and CI has a step
named `the committed build matches src/` that fails on a stale bundle. All
three are gone. What replaced them is a prerequisite: **`cd frontend && npm run
build` before the server will serve a console at all** — `create_app` mounts
nothing when `static/` is absent and `/` answers 503 naming the command
(`tests/interfaces/test_web_console.py`, which holds both states of `/`).

Why the swap: the reason for committing it was that `uv run web.py` then needed
no Node toolchain. The cost was paid on every merge — two branches that both
touched `frontend/src` produce two different bundles over the same handful of
stable filenames, and the conflict is over bytes nobody reads or reviews, whose
only correct resolution is to rebuild. That happened often enough to outweigh
the toolchain-free run.

**There is a fifth command. It is now a CI job, and it is still not in
`verify`.**

```
cd frontend && npm run test:browser
```

Headless Chromium via vitest's browser mode, over `src/**/*.browser.test.tsx`.
**Run it when you touch a stylesheet, a layout primitive, or anything whose
correctness is a computed style or a measurement.**

This entry used to say it was outside CI as well, and that changed on
2026-08-29 (CI job `browser`, its own runner, in parallel with the rest). What
changed the decision is that the cost of leaving it out stopped being a
prediction: B140 records #249 adding Toasts stories, passing all four gates,
merging, and leaving `a11y.browser.test.tsx` red for four merged commits with
every gate green -- found weeks later by the next person who ran the suite by
hand and had to work out which merge did it.

What did *not* change is why it is outside `verify`: it is a minute against a
second, and a Chromium download, and neither belongs in the loop you run
before every commit. The CI job is a net under the practice, not a replacement
for it -- push a stylesheet change without running it and you find out in two
minutes rather than in two weeks, which is better and is not the same as
knowing before you push.

The reason it exists: jsdom lays nothing out and applies no stylesheet, so
`scrollHeight` is 0 everywhere, `getComputedStyle` returns only what an inline
style said, and a selector that matches nothing is indistinguishable from one
that matches. Four findings in a row had their real assertion written as a
comment for that reason, and the fifth -- a chosen control drawing in the
unchosen colour, because a `Tooltip` and a `RadioGroup` both wrote
`data-state` to one element -- shipped past a fully green suite and was caught
by eye.

What it is not: a replacement for the jsdom suite (923 tests to its handful),
or a place for anything jsdom can already judge. Roles, focus order, keyboard
routing and rendered text belong in `*.test.tsx`, where they run in a second
rather than a minute.

Two things learned writing the first tests, both of which cost half an hour:
the viewport is set in `vite.config.ts` and a media query reads *that*, not
the width of the wrapper a test renders into; and `vitest.setup.browser.ts` is
a separate file from `vitest.setup.ts` on purpose, because the jsdom setup
pins `offsetWidth`/`offsetHeight` to constants and would blind the one suite
whose job is measuring.

**`border-solid` beside one directional width draws three unwanted sides.**
This build imports no Tailwind preflight, so the browser's own defaults are
what's left where Tailwind sets nothing. `.border-solid` is the shorthand —
`border-style: solid` on all four sides at once. Pair it with a directional
width like `border-t` and no `border-0`, and the three sides that get a
style but no explicit width fall back to the browser's `medium` (~3px)
rather than 0: a rule meant for one edge draws a box. The fix is both halves
together — `border-0` to zero the three sides you don't want, then the
directional width for the one you do. No gate catches it.

**A directional width *alone* is fine, and this entry used to say the
opposite.** It said `border-t` without `border-solid` "draws nothing at all,
because every side's style is still `none`". That is not true of this build,
and it is the half the repository had been acting on — `BACKLOG.md` B55 was
filed entirely on it and is now withdrawn. Tailwind v4 emits the style
longhand *with* the width (`border-b` → `border-bottom-style:
var(--tw-border-style); border-bottom-width: 1px`) and registers
`--tw-border-style` with `initial-value: solid`, so a directional width alone
resolves to solid and draws. `border-style:none` appears zero times in the
built `index.css`. **Verified against the built stylesheet on 2026-08-13, not
reasoned** — and the repository already held the measurement: `Drawer.tsx:162`
writes `border-l border-line` with no `border-solid`, and
`shell-reached-dressing.browser.test.tsx:157-158` asserts that element's
`borderLeftStyle === 'solid'`.

The remaining honesty: this entry said the defect was caught by eye in
Storybook "twice, in both directions", and only one direction is explained by
the current build. The other observation has not been re-taken.
`frontend/src/styles/border-style-default.browser.test.tsx` exists to settle
it and has not been run.

**And `border-0` beside a non-directional `border` is not the same fix; it is
a conflict.** The rule above is about a *directional* width: `border-0` zeroes
the three sides you did not ask for, then `border-t` draws the one you did.
Applied to an all-sides border it becomes `border-0 border`, which is two
`border-width` utilities on one element -- 0px on all four sides and 1px on
all four sides -- and which one wins is decided by their order in the built
stylesheet rather than by anything in the file you are reading. `border`
alone is correct there.

Found on the curriculum panes, where six elements carried the pair. Nothing
caught it: it typechecks, it lints, jsdom returns only what an inline style
said, and the rendered result happens to be the intended one in this build. It
surfaced because prettier's Tailwind class sort rewrote `border-0 border
border-line` as `border border-0 border-line`, which reads as obviously wrong
in a way the original did not.

**An unlayered rule in `tokens.css` beats any utility, so a utility meant to
override one is inert — and looks exactly like a utility that worked.** The
global `:focus-visible { outline: 2px solid var(--accent); outline-offset: 1px }`
(`tokens.css`, near the end) is written outside any `@layer`. Tailwind emits its
utilities into `@layer utilities`, and **an unlayered normal declaration beats a
layered one regardless of specificity** — so `focus-visible:outline-offset-[-2px]`
at (0,2,0) still loses to a bare `:focus-visible` at (0,1,0). The class is in the
attribute and the rule is in the bundle; only the computed value disagrees.

This is how the inward focus ring shipped broken. Slice 3a moved three working
stylesheet rules onto a `RING_INWARD` utility constant, reported the geometry as
carried across unchanged, and clipped the document row's ring on every row for a
whole slice; two agents rediscovered it independently a slice later, each by
measuring. Measured in Chromium at 1440×900: with the constant absent and with
the constant present, the ring's reach is **byte-identical**.

The fix is a named class in a stylesheet — `.lay-ring-inward` in `layout.css`,
(0,2,0) against the global's (0,1,0), both unlayered, so the comparison is one
the cascade will actually make. A trailing `!` also works, and was rejected: it
leaves every future inward ring one forgotten character from the same silent
failure, and there is nowhere for the measurement to live.

The general rule outlives the ring: **before overriding anything declared in
`tokens.css` with a utility, check whether the rule is layered.** If it is not,
the utility will not win, and no gate will tell you — jsdom returns only what an
inline style said, so the assertion has to be a browser measurement.

**The third instance was an element selector, and it was inert for everything
at once.** `tokens.css` gave a bare `button`, `input`, `textarea` and `select` a
background, a colour and `font: inherit`, unlayered — so those rules beat every
Tailwind utility on every such element in the console, since the day they were
written. `bg-transparent`, `bg-bg-panel-2`, `text-accent`, `text-fg-dim` and
`text-xs` on a `<button>` were all dead. `font: inherit` reaches furthest
because it is a *shorthand*: it sets `font-size`, so the size utilities went
silently along with the colour ones, and nothing about `text-xs` suggests it is
competing with a `font` declaration.

It surfaced on 2026-08-28 because `CourseCard` stretches its click target as
`<button class="absolute inset-0 … bg-[transparent]">` across the whole card:
the inert background painted `--bg` opaquely over the card's own art, title and
blurb, so every catalog card drew as an empty bordered box. Everywhere else it
had merely been drawing the wrong colour, invisibly — the catalog's *chosen*
filter tab had been rendering in the unchosen tone.

**Layer the rule, do not name a class, when the rule is a default.** Both of
those went into `@layer base`, which is the opposite of the ring's fix, and the
distinction is worth keeping: the global `:focus-visible` is a *decision* that
particular elements opt out of, so opting out earns a named class. A background
for an unclassed control is a *default*, and losing to anything more specific is
what a default is for. `theme.css` already declares `@layer theme, base,
components, utilities`.

**What this instance changes about the advice above:** checking whether the rule
you are fighting is layered is necessary and no longer sufficient, because the
rule may not be one you went looking for. An element selector is invisible to a
search for the class you are writing. `control-defaults.browser.test.tsx` is the
standing measurement — a utility on a form control has to actually win — and it
is a browser test for the usual reason: in jsdom the class is in the attribute,
the rule is in the bundle, and the two never meet, so there is nothing to assert
on.

**And check pixels, not the DOM, when a surface renders wrong.** This one was
first misdiagnosed from `getBoundingClientRect` and `getComputedStyle` on the
content: every box had the right size, the right colour and the right text, and
all of it was correct — the content was simply underneath an opaque sibling. The
question that located it in one call was `document.elementFromPoint(x, y)` at
the centre of the thing that would not show. Geometry says what was laid out;
only a screenshot or a hit test says what was painted.

**Do not run two `vitest` processes at once.** Concurrent runs fail
spuriously, usually with a coverage temp-file error that names nothing about
the real cause. If a frontend test fails, re-run it alone before investigating
it.

**A failure under load is not evidence until it reproduces alone.** Several
tests here are timing-sensitive, and a machine running another suite (or
another project's containers) produces failures that are absent on a quiet
one. Re-run the failing test in isolation first. Then re-run the *whole
suite*, because some failures only appear in company. Two consecutive
identical results is the bar for "this is real"; one run is a sample.

**But do not file everything under flakiness.** `BACKLOG.md` B4 records a test
that was called flaky for months and was actually broken -- it established its
precondition with a `sleep` and failed against correct code. The tell was
direction: it failed in a way load could not explain. If the failure does not
fit the story you are telling about it, the story is wrong.

**A formula correct on every case a test naturally reaches is
indistinguishable from one that is correct.** `SocraticPrompt.position` was
written as `(len(history) - 1) // 2` where the ask uses `len(history) // 2`,
and the reasoning was sound: a dialogue's history opens with an unanswered
question, where an ask's is pairs. The two formulas **agree exactly on every
odd-length history** -- and with the opening question present the history is
odd before every turn, which is every case anyone would think to write down.
They differ only on an even history, which happens when `opening_prompt` is
empty, a case schema evolution explicitly permits for streams written before
the field existed. There the deviation numbers the second exchange as the
first, collides with the first turn's grading key, and marks a reader against
a component they were never shown.

The first draft of the test used two turns of one ordinary dialogue. It passed
under both formulas and proved nothing, and it looked like the most obvious
test in the file. The defect shipped through a full review round on 2026-08-17
and was caught by comparing the two formulas rather than by any test.

**The general rule: when a test's inputs and the formula's branches are chosen
by the same person in the same hour, the test tends to sample the cases the
formula already handles.** Parametrise over the property that *distinguishes*
the candidate formulas -- here, history parity -- and not over what looks like
a representative example. If you cannot say which input would separate your
formula from the one you rejected, you have not tested the choice you made.

## Read models

**A read-model change verified only against a fresh database is unverified.**

Adding a field to a `ReadModel` does not add a column to a database that
already exists. `CREATE TABLE IF NOT EXISTS` does nothing to a table that is
already there, so the column is missing, every query against it fails, and the
endpoint answers 500 -- while every test passes, because tests build their
database from nothing.

`apply_schema` in `infrastructure/persistence/read_models.py` now reconciles
added columns, and
`test_a_database_written_before_a_field_existed_gains_its_column` fails if
anyone removes it. Both exist because this shipped once.

It reconciles two ways, and the split is the part to know before editing it.
The `ALTER`s come from the library's `generate_additive_migration`, which is
pure and refuses the whole set up front if any column is required with no
default -- so the table is never left half-widened. But it refuses that
*categorically*, where SQLite only refuses it on a table that has rows, and the
incident above is a required column added to a table that is usually empty. So
an empty table is dropped and recreated instead, and a populated one re-raises;
`/rebuild` is the answer there and a loud error is how anyone finds out.

The general rule outlives that fix: **when you change a projection or a read
model, run it against a database that predates the change.** A copy of a real
one is best. "It works on my fresh database" is the sound of this bug.

**A copy of a real one does not open where you put it.** Copy
`~/.research-team/sessions.db` anywhere else and nothing starts:

```
PositionForeignError: cannot order positions from
'sqlite:/home/you/.research-team/sessions.db' and 'sqlite:/tmp/copy.db'
```

`eventsource` derives a store's id from the database string it was handed --
`f"sqlite:{database}"` -- and every row in `projection_checkpoints` carries
that id inside its position token. A position from one store cannot be ordered
against a position from another, so the subscription fails to transition and
`start()` raises before a single event is replayed. The path is the only thing
that changed, and it is enough.

```
uv run python -m research_team.infrastructure.persistence.local_copy /tmp/probe.db
```

That copies the database (`VACUUM INTO`, from a read-only connection, so the
`-wal` comes with it and nothing can write to a database you are still using)
and rewrites the store id in each checkpoint to the copy's own path. It prints
the `AGENT_DB=` line to run against it.

**Deleting the checkpoints also gets it up, and quietly defeats the rule.** It
is the obvious fix -- an empty `projection_checkpoints` has no foreign position
to compare -- but a projection with no checkpoint replays the whole log and
rewrites every row, which is `/rebuild` by another name. The half of the bug
that survives `apply_schema` is the half it hides: `apply_schema` widens the
table but leaves the new column empty in the rows already there, and against a
real database the projection resumes near the end of the log and never
backfills them. That is what the endpoint is wrong about. Measured, on
2026-08-13, by emptying `session_summary_rows` in two copies of the real
database and starting each: the copy with its checkpoints cleared came back
with all four rows, the copy with them rebound came back with none. The rebound
one is the honest reproduction.

**A fixture that seeds through the same call the code under test depends on
cannot see that dependency go missing.** Found on the entity-definitions work:
the definition-reading path called `graphs.chunks(project)`, which requires the
chunk store built inside `graphs.open(project)` -- but the call site fetched
chunks *before* opening, so the first definition request for any newly-touched
project answered 503 and every request after it succeeded, because by then
some earlier call in the same test process had already opened the project.
Once per project, and indistinguishable from flakiness if you don't know to
look for it.

All six of that task's tests missed it, and the reason is the same test
shape in every one: the fixture that set up the test data called `graphs.open`
to seed it, which is the very call the request path had stopped making. From
the fixture's point of view the project was always open, so a code path that
forgot to open it first was invisible. It took a reviewer's throwaway probe --
issuing a request against a project the fixture had *not* touched -- to see
the 503. The general form: when a test's arrange phase invokes the same
collaborator method that is the thing under test is supposed to invoke,
that test cannot detect the invocation being dropped. Write at least one test
per code path that starts from a fixture that has *not* made the call the
code is responsible for making.

## Checkpoints over model output

**A checkpoint asserting on a shape no prompt demands refuses correct work,
and the suite cannot see it.** Course authoring's four phases each end in a
Python check over the files the phase left behind (`authoring_checkpoints.py`),
and every one of those checks greps for a literal. Three of them grepped for a
literal the prompt never asked for. The failure is always the same and always
the wrong way round: the model does exactly what it was told, the checkpoint
sees nothing, and the run dies naming a count.

It is invisible to tests for a reason worth naming separately, because it is
the CLAUDE.md fixture rule one level up: **the fixture supplies the contract
the prompt was supposed to state.** Whoever writes the checkpoint writes the
fixture in the same hour and hand-writes the shape into it, so the test proves
the checkpoint can read a document nobody asked the model to write.

The instances, in the order they were found:

- `## Enduring Understandings` / `## Essential Questions`, required by
  `check_stage_one`, named nowhere in `desired_results_prompt`. Found by
  review on 2026-08-24; latent, because the model happened to pick those
  headings unprompted on the run the next day.
- "performance task", counted case-insensitively by `check_stage_two`, with
  `evidence_prompt` saying nothing about how to mark a task. **Measured on
  2026-08-25**, on a live run over the `research-team` project's
  `agent-interaction-log` area: four correct tasks written as `**PT1 —**`
  through `**PT4 —**`, the phrase occurring twice (an intro sentence and a
  heading), and the run refused at `2 performance task(s) for 4
  understanding(s)`.
- `builds_toward` and the ```` ```component: ```` fence, named in the parent's
  prompt and -- after the fan-out that made `lesson-drafter` the only thing
  writing a lesson -- named to nothing that writes one. Found by auditing for
  the shape after the second, which is the only one of the three that cost
  nothing.

The fix in all three is one shape: **the literal is a constant, the prompt
interpolates it, and a test holds the pair**
(`test_every_marker_a_checkpoint_searches_for_is_named_in_its_prompt`). The
fix that was rejected each time is a looser pattern -- it guesses at the
model's formatting, which is precisely what went wrong, and the next model
picks a different format. Loosening also costs the checkpoint its job: a check
that matches anything cannot tell a phase that worked from one that stopped,
which is the whole reason the phases are separate.

The general rule, and it outlives course authoring: **anywhere Python asserts
on text a model produced, the assertion is half a contract.** Write the other
half into the prompt, from the same constant, or the assertion is a guess
about a stranger's formatting habits.

**This entry did not stop the fourth instance, which was written in the same
wave that wrote the entry.** Closing the "phase 4 cannot fail on its own work"
gap meant a new rule -- every lesson's component count must rise in phase 4 --
gating `quiz-writer`, the one subagent deliberately left without the component
syntax, from a prompt that stated no floor. Both halves of a fresh contract,
missing, hours after the paragraph above was written by the same person.

So the durable part is not the prose. It is
`test_every_marker_a_checkpoint_searches_for_is_named_in_its_prompt`,
parametrised from `CHECKPOINT_MARKERS` in `authoring_checkpoints.py`, plus
`test_the_marker_registry_covers_every_literal_constant`, which derives the
registry's coverage from the module's own constants by introspection so a
seventh marker fails at collection. The pairs were a hand-written list for
exactly one commit, and that is the commit the fourth instance entered in.
**A contract that has to be remembered is documentation; the test is the
contract.** Read this section when the test fails, not instead of it.

## Extraction

**The model files its answer where the schema's other fields live, not where
the field is declared.** `ExtractedEntity` has typed fields *and* a free
`properties` dict, and a domain schema's declared per-type properties
(`outcome`, `role`, `creator`, `definition`) all land in `properties`. So when
the prompt asks for a date "in that entity's `temporal_expression` field", the
model puts it in `properties` beside the others. Nothing in the prompt or the
schema distinguishes the one field that is not a property.

Measured on 2026-08-15, tracing the provider seam across every chunk of three
real Ancient Rome articles against qwen3.8-27b-mtp: **not one entity arrived
with `temporal_expression` set.** Every date was in `properties`:

```
{"temporal_expression": "AD 380", "outcome": "Nicene Christianity ..."}
```

`redstring`'s `_build_extent` reads only the typed field, so every date was
discarded before any parsing was attempted. That is the whole of the measured
0.3% temporal rate -- 2,525 entities, 8 with an extent -- and it is invisible
from every direction: nothing raises, nothing logs, the extraction succeeds,
and the timeline is simply empty. `redstring_adapter._DatingProvider` lifts
the key back out; `tests/infrastructure/test_temporal_extraction.py` pins it.

**The general rule is worth more than the instance.** A field that is optional
in the schema and absent in practice looks exactly like a field the model
declined to fill. Before concluding that a model will not answer something,
log what it actually returned. Three minutes of tracing the seam beat two
hours of reasoning about what the code downstream of it does with the answer.

**And a perfect reproduction of a real defect is not proof it is *the*
defect.** The first cause found here was `parse_temporal` fabricating a day
from `published_at` -- reproducible on demand, byte-identical to a value
sitting in the production database, and genuinely a bug. It was the second
bug. It was fixed first, and fixing it moved the rate almost not at all.

That fix was not wasted and should not be read as rework: `AD 80` -> 1980 and
`AD 64` -> 2064 are real fabrications that would have surfaced the moment the
`properties` lift started feeding the parser actual expressions. It was the
right fix in the wrong order.

## Events

Events already written are not rewritten, so a change to an event's shape has
to be readable against payloads an older build stored. `domain/events.py`
opens with the two supported cases and
`tests/infrastructure/test_schema_evolution.py` is what enforces them --
it writes old-shaped payloads straight into the events table and reads them
back.

Breaking that on purpose is allowed while the project is pre-release, and
`SessionStarted.project_id` is the one place it has been done. When you do it,
say so in the field's docstring, say what no longer loads, and update the
schema-evolution test to assert the *refusal* rather than deleting the case.
A deliberate break that is written down is a decision; a silent one is a bug
somebody meets years later.

**An event no projection handles counts as APPLIED, not rejected.**
`eventsource.replay`'s own docstring says it plainly: "An event that every
projection ignores still counts as applied -- it was delivered and nothing
rejected it." `strict=True` raises only when a projection's `handle()` itself
raises; it has no opinion about an event nothing subscribed to. That is the
right default for *adding* an event type -- an older build with no projection
for it keeps replaying cleanly, which is what "events are not rewritten" above
depends on. But it means *omitting* a projection produces a silently EMPTY
read model, not a refusal. Nothing crashes, nothing logs, the endpoint answers
200 with nothing in it.

The consequence for tests is specific: an assertion that "the project opened"
or "the request succeeded" passes with the projection removed entirely, and is
therefore worthless as a test of that projection. The assertion has to be that
the *data* is there -- a row exists, a field has the value the event carried --
not that the surrounding machinery didn't throw. This was found mid-build on
the entity-definitions work, where an earlier draft of that feature's design
document asserted the opposite (that a missing projection would be caught),
and it wasn't: a build with `EntityDefinitionRunner` never constructed in
`composition.py` served every definition request as an empty cache miss, and
the tests that "confirmed the endpoint worked" never noticed, because none of
them checked for a stored row.

**A port with one adapter and no test between them is two things that were
never checked against each other.** The co-mention channel shipped in #234 with
a `CoMentionPort`, a `ChunkCoMentions` adapter, a projection that consumed it,
two tuned constants and a section of a design document. It produced **nothing**
from the day it merged. The adapter read entity links off stored chunks; the
only thing that writes chunks is `index_documents`, which runs before
extraction and has no entity knowledge, so every chunk carried `entity_ids: []`.

Every piece was tested. The projection's tests passed literal `frozenset`s
straight to `project_areas`. The adapter had no test at all. So the port was
verified against a stub and the adapter against nothing, and the question
"does the real writer produce what the real reader expects" was never asked by
anything. Measured on 2026-08-22 over a real ingest: 36 chunks, 0 with links, 0
passages, and an area projection **byte-identical** with the channel present
and absent.

The general rule: **when a port has exactly one production adapter, the test
that matters is the one that drives both ends over real data.** A stub on one
side and a unit test on the other prove the two halves work; they cannot prove
they meet. Look for this shape wherever a `Protocol` in `application/` has a
single implementation in `infrastructure/` -- that is the whole population, and
it is small enough to audit.

**The number was on screen the entire time.** `DerivedFromLine` renders "*N*
shared passages", and it had been printing **0** on every projection since the
feature shipped. A surface that displays a health metric nobody reads is not
observability; it is the same silence with a number in front of it. If a value
is worth rendering because its absence would be a defect, something has to
assert on it -- `test_a_curriculum_built_over_a_real_ingest_counts_shared_passages`
is that assertion, and it postdates the defect by a whole feature.

**A library that hands back a count instead of the event it built has hidden
a write from your log.** redstring's `build_graph` embeds every entity, folds
the vectors into the `VectorStore` through `VectorProjection`, and returns
`GraphBuildReport.embedded` -- an integer. The `EntitiesEmbedded` it
constructed to do that is reachable only by passing `build_graph` an
`event_store`, which this project did not. So the vectors were computed, paid
for, written to an in-memory store, and dropped when the process ended, with
nothing on the log to replay them. Measured on 2026-08-22 against a copy of
the real database: **zero `EntitiesEmbedded` rows in a log holding 8
`DocumentExtracted` and 772 `EntitiesMerged`**, with embeddings on by default
the whole time.

Nothing about this is visible from the running system. Extraction succeeds,
the store answers every query, consolidation scores three features, and the
only symptom is that a restart silently drops to two -- which looks like
nothing at all. The general form: **when a library writes into a store you own
*and* returns a summary rather than the event, check which of the two it
considers the record.** If the event is not in your log, the store is not a
projection, whatever it is called.

**And a comment explaining an absence will turn a defect into a decision
nobody questions.** `project_graphs.py` carried this, in the same register as
every other reasoned comment in the tree:

> It does not live in `rebuild_graph`, which folds the log, because the vector
> store is not part of that fold -- this project never appends
> `EntitiesEmbedded`, so a `VectorProjection` would have nothing to replay.

Every clause is true. The conclusion is backwards: "we never append it" is the
bug, and the comment reads it as the premise. Written down that way it stopped
being a question -- it was cited in a design document, and then in a `BACKLOG`
entry, as an established fact about what this system can do. Three documents
agreeing, all descended from one comment that described a defect in the voice
of a choice.

The tell, worth looking for elsewhere: a comment that explains why something
is *absent* by pointing at another absence. "We don't fold X because nothing
writes X" is a loop, not a reason, and the question it forecloses is whether
anything *should* write X.

## The interaction log

**A second event store means no projection can span the two.** `eventsource`
derives a store's id from the database connection string and every checkpoint
position carries it, so a position from `interactions.db` cannot be ordered
against a position from `sessions.db` (`PositionForeignError` — the same
mechanism the Read models section above describes for two copies of one
store). This is not a limitation to work around; it is why the interaction log
is genuinely separate rather than separate by convention, and it is structural
enough that a future consumer correlating the two has to fall back to an
application-layer join on approximate wall-clock, not an ordered read. See
BACKLOG B109.

**A silent emitter makes "nothing happened" look exactly like success.** The
interaction log's React context defaults to an emitter that records nothing,
so the hundreds of existing component tests need no provider at all. The cost:
a test that renders without the provider and asserts no events were sent
passes whether the feature works, was reverted entirely, or was never wired up
in the first place. Measured on this branch: deleting the
`<InteractionLogProvider>` wrapper from `App.tsx` left all 15 `App.test.tsx`
tests and all 4 provider tests green, with the console silently collecting
nothing the whole time. The assertion has to be that a *recorded event reached
the sink* — never that nothing threw.

**Effect declaration order decides which route's ids an event carries.** A
`setContext` effect declared above a `dwell.enter(view)` effect rewrites the
context before `enter()` internally calls the previous view's `exit()`, so
every page's `ViewExited` was stamped with the ids of the page the user went
to *next* rather than the one just left. Silent — the dwell arithmetic stayed
correct throughout, only the attribution was wrong, so nothing about the
duration looked implausible. Swapping the two effects does not fix it; it just
moves the same defect onto `ViewEntered`. The fix is one effect doing exit,
then `setContext`, then enter, in that order.

**`useMemo` is not a caching guarantee.** React may discard a memoised value on
a remount, which for a per-page-load identity means minting a second id and
restarting a sequence counter mid-page — breaking an idempotency key that
depends on the pair staying stable together. A lazy `useState` initialiser
gives the guarantee a memo doesn't; a lazy `useRef` looks like it would but
doesn't survive this repo's lint, because the `react-hooks` plugin's refs rule
forbids reading `.current` during render.

**StrictMode's double-invoke can leave a cleaned-up resource dead.** An effect
cleanup that stops a flush interval, paired with a factory that only builds the
interval once, means a StrictMode remount gets an emitter whose timer is
already gone. Measured: 0 timed flushes in a 20-second fake-timer window under
StrictMode, 1 without. Production is unaffected — StrictMode's double-invoke is
dev-only — which is exactly what makes this invisible: it degrades only the
one environment where a person would hand-verify the feature by watching it
run.

## Web middleware

**`@app.middleware("http")` breaks the routes that hand work to a background
task, and the failure names nothing about middleware.** The decorator is
Starlette's `BaseHTTPMiddleware`, which runs the endpoint inside its own anyio
task group, and the routes here that schedule fire-and-forget work no longer
have it outlive the response. Measured on 2026-08-17: adding one
content-length check with that decorator turned four passing tests in
`tests/interfaces/test_extraction_routes.py` red -- queueing answered
`queued: false`, cancelling reported `cancelled: 0` -- and all four passed
again with the decorator removed and nothing else changed. Nothing in either
failure mentions middleware, and the route being wrapped was not one of the
four.

Write a plain ASGI callable and `app.add_middleware(...)` it instead;
`_InteractionBodyCap` in `interfaces/web/app.py` is the worked example. It
adds no task group and leaves every other route's execution exactly as it was.

## Two structures that must agree, in two places the merge cannot compare

**A per-branch gate cannot see a disagreement neither branch contains.** When
two structures must agree and nothing derives one from the other, each branch
holds one side, each branch is green, and git reports no conflict -- because
neither branch edited the *other* half. The disagreement is created by the
merge and is the one thing nothing in the process looks at. Three of these
landed on 2026-08-29, within one afternoon.

**`Application.close` against `_PARTIAL_BUILD_RESOURCES`** (`composition.py`,
B179, now closed). #328 rewrote `close()` into a named-step list. Two later
branches each added a resource to `close()`; neither added it to the
partial-build list, and neither *conflicted* on that list, having never touched
it. `close()` is edited often and so conflicts loudly; the tuple is edited
rarely and so merges silently -- which is exactly the wrong way round, because
the tuple is the half a rebasing reader is not thinking about. Nothing was red.
The symptom would have been a hung interpreter at exit (B5, B100), not a test.

**A duplicate `B161` in `BACKLOG.md`.** #325 renumbered an entry into B161;
#328 landed a different entry on B161 three minutes later, in the other half of
a 5,000-line file. Neither conflicted, both were green, and `main` merged red --
blocking every open PR. Then two agents *fixing* it collided again, because the
uniqueness test says which entry moves and says nothing about where it moves to.

**`Tenant` and the feed's routed/unrouted lists** -- the one a test caught, and
the reason it caught it is the whole lesson.
`test_every_aggregate_type_is_routed_or_deliberately_not` does not compare two
hand-written lists. It **derives the population** from the domain's own
aggregate types and requires each to appear in one list or the other, so a
branch that adds an aggregate type is red on its own branch, holding both sides
by construction. The failure arrives where the author is, before any merge.

**The remedy, in order of preference.**

1. **Derive one side from the other**, so there is only one thing to edit. The
   link is usually already in the tree and unnoticed: `Application(...)`'s
   keywords already map each attribute to the local that filled it, which is
   what `test_every_close_step_has_a_partial_build_resource` reads. This costs
   nothing at merge time and is the only remedy that removes the class rather
   than reporting it.
2. **Derive the population**, when the two sides are a partition rather than a
   copy -- every aggregate type is routed or deliberately not, every checkpoint
   marker is named in a prompt (`CHECKPOINT_MARKERS`). New members fail until
   somebody classifies them.
3. **Make the branches write *different* things on one line**, when nothing can
   be derived. One line every filing branch rewrites is not enough on its own,
   and this is the entry's own mistake, made and found the same day: `<!-- next
   id: N -->` shipped as a counter, and a counter is a value both branches
   *read the same* and therefore both **write the same**. Measured on
   2026-08-29 -- #345 and #340 each took 182, each wrote `next id: 183`, git
   merged two identical lines without a murmur, and the duplicate surfaced from
   `test_no_two_backlog_entries_share_an_id` on `main`. A counter narrows the
   window to branches that overlap; it does not close it, and the case it
   fails is the concurrent one it was written for.

   What conflicts is a line that carries something **only that branch can
   write**. The marker is now `<!-- next id: N; B<n> claimed by: <slug> -->`,
   where the slug is the filing entry's own heading: two branches filing two
   different entries cannot produce the same line. Simulated on 2026-08-29 with
   two branches off one base, each filing into a different section of the file
   as #325 and #328 did -- **counter-only merged clean with two `B183` headings
   in the result; counter-plus-claim conflicted, on merge and on rebase alike.**
   The cost is real and deliberate -- guaranteed friction on every concurrent
   branch, about a minute each -- and it is paid by the branch that is merging
   rather than by everybody whose PR the red `main` blocks.

   The general form worth carrying to the next instance: **a shared allocator
   read is not a conflict surface.** Ask what the two branches would each write
   there. If the answer is a function of what they both read, git will merge it.

   The honest residual is written up as B185: a conflict a person never reads.
   `-X ours` and `-X theirs` were then measured, and the fallback holds -- both
   entries land whatever the marker says, so the uniqueness test is red on the
   resolving branch rather than on `main`. What that measurement also killed is
   a plausible-sounding claim: keeping the *other* side's marker was expected to
   be caught by the slug check, and it is not, because after the merge both
   headings are present and either slug matches one. The slug's whole job is to
   make the line conflict; it is not a second net behind that. `rerere` is still
   unmeasured, and it is the one that can resolve the line with no conflict
   reported at all.

**What does not work, and reads as though it does:** a test that detects the
collision after both sides exist. `test_no_two_backlog_entries_share_an_id` is
correct, was green on both branches, and its first sight of the problem was on
`main`. A gate that can only run where both halves are present runs too late by
one merge.

**What to look for.** Two lists, sets or registries that must agree, where one
is in a file people edit constantly and the other is in a file they do not. Ask
which half a branch adding a feature will touch; if the answer is "one of
them", the other half is unprotected, and the failure will arrive during a
rebase -- when the person holding it has the least attention to spare for a
list they did not edit.

**Exemption sets need their own staleness test.** Every remedy above ends in a
short hand-written list of deliberate asymmetries (`PUBLIC_PATHS`,
`_CLOSE_STEPS_WITH_NO_PARTIAL_BUILD_RESOURCE`, `UNROUTED_AGGREGATE_TYPES`,
`DEFERRED_TO_THE_B2_SWEEP`). Two entries with written reasons beats twenty-four
names with none -- but only while something fails when an entry stops applying.
An exemption kept past its reason exempts whatever is written on that name next.

## Comments and commit messages

The standard here is higher than most repositories and is worth matching.

Comments explain **why**, not what. They state costs and trade-offs plainly
rather than only benefits, they name what a test would fail on, and they say
when something was measured rather than reasoned. A comment that restates the
code is worse than no comment, because it has to be maintained.

Commit messages carry the reasoning that does not fit in a comment: what was
considered and rejected, what the change costs, what is deliberately left
undone. `git log` is a design record here, so write for someone reading it in
a year with no memory of today.

If a test would pass with the change reverted, say so in its docstring rather
than leaving it as reassurance. Proving a test red before trusting it green is
the convention.

## Parallel work

**Work in a worktree when more than one thing is in flight.** Several changes
were nearly lost by one checkout being switched while another piece of work
was live in it -- uncommitted edits carry across a branch switch and end up
sitting on the wrong base, where they look modified and are not what they
seem.

If HEAD is somewhere you did not put it, or files you did not touch show as
modified: **stop and say so** rather than reconciling it. The reconciliation
is where the work gets lost.

## Dependencies

`eventsource-py` and `redstring` are both pre-1.0 with a stated no-shim
policy, so a *minor* is where breaking renames land -- 0.12.0 carried four.
Both are capped below the next minor, and the reasoning is written above the
pins in `pyproject.toml`.

They move together: `redstring` depends on `eventsource-py` within the same
window, so bumping one alone is unresolvable rather than merely unwise. Bump
the `tracing` extra in the same commit as the core dependency -- it pins
`eventsource-py` separately, and a default install resolving to a different
minor than an `--extra tracing` install is a difference nobody sees until a
tracing run behaves unlike every other run.
