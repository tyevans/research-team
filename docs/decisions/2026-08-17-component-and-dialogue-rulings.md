# Decisions taken while building the components and the dialogue

2026-08-17/18. The rulings and corrections made across six execution ledgers,
preserved here because those ledgers live under a gitignored path and would
otherwise be lost with the scratch directory.

Each entry says what was decided and why. Where it was recorded, it also says
what the decision costs if it turns out wrong — that line is the one to read if
you are deciding whether to undo something.

Two kinds of entry appear. **Ruling** is a decision taken on the user's behalf
because the work could not continue without one. **CORRECTION** is a place where
something I or an implementer had asserted turned out to be false; they are kept
because a claim that was wrong once is worth knowing about, and three of them
were negative claims about the tree that nobody had re-run.


## Wave A — five data-bound components

- Task 6: Ruling: carried into Task 7 - `resolvedWidgetQuery`'s `staleTime`,
  `refetchOnMount` and `refetchOnWindowFocus` are pinned by nothing (only `retry`
  is). One unit test on the constant's shape, not four copied widget tests. The
  reviewer judged the cross-widget retry coverage adequate rather than
  under-tested, so this is the cheap residual guard only.

- Task 6: Ruling: `limit` reaching the timeline route bounds the RESPONSE, not the
  server's work — the two full passes over the tenant's entity set precede the
  interval, so an author writing `limit: 20` to make a heavy widget cheap gets
  nothing, and nothing tells them. Narrowing the window does not help either.
  Task 8 owns prompt craft, so the craft note must say this plainly. Cost if
  wrong: authors optimise a widget with a field that does nothing for cost.

- Task 6: Ruling: carried into Task 7 — `resolvedWidgetQuery` now changes retry
  behaviour for `GraphWidget`, `EvidenceWidget` and `useEntityReference`, which
  Task 6 did not own, and only the timeline test pins it (the others' suites use
  `retry: false` clients and would not notice a regression). Task 7 adds a
  shape-level test. Cost if wrong: a shared retry policy with one witness.

- Task 5: Ruling: three Task 5 minors carried into Task 6 rather than a fix round,
  because Task 6 writes a browser test and a widget query of the same shape, so
  they land at the shape level in one reviewed dispatch. (a) The `.cmp-passage`
  geometry assertions are filed inside `GraphWidget.browser.test.tsx`, so deleting
  the graph widget would silently delete Task 4's only geometry measurement — move
  them to their own file. (b) Widget queries inherit the app's global `retry: 1`,
  so a known-permanent 404 is fetched twice before prose appears; set the retry
  policy once for resolved widgets. (c) The graph box height is measured only at
  640px, so the narrow-column `min-height` floor is asserted by nothing.
  Cost if wrong: they land one task later than they could have.

- Task 4: Ruling: two of Task 4's minors are carried into Task 5's dispatch rather
  than a fix round of their own — Task 5 already touches `components.css` and adds
  a browser test, so reviewing them there costs one dispatch instead of two.
  (a) `ask-fixtures.ts`'s header still says "for the stories and tests on this
  page" though `componentBlock` is now shared lesson/ask, with three more
  importers coming. (b) `.cmp-passage`'s four CSS rules have no browser
  measurement, and CLAUDE.md is explicit that no gate catches border geometry.
  Cost if wrong: they land one task later than they could have.

- Task 3: Ruling: `picked` persisting across a later search result is a property of
  the SHAPE (`ResolvedFrame`), not of `definition`, so it gets fixed once there
  rather than five times. Assigned to Task 5, the next `ResolvedFrame` consumer,
  as an explicit prerequisite. Cost if wrong: an unreachable state change made in
  a task that did not strictly need it.

- Task 3: Ruling: `Defined`'s `projectId as ProjectId` cast is replaced by narrowing
  inside `ResolvedFrame`'s render prop, NOT by changing `ResolvedFrame`'s
  signature. Keeps the Task 2 interface untouched so Tasks 4-7 copy a narrow
  rather than a cast; the null arm is unreachable because the hook returns
  `unavailable` when there is no project. Cost if wrong: an unreachable branch.

- Task 3: Ruling: the course-prompt leak COMPOUNDS once per task (five widgets
  advertised to a course prompt that can never resolve them, by Task 7), not once.
  Still Task 8's to fix rather than each widget's. Cost if wrong: the course
  prompt advertises five dead widgets for the duration of the plan.

- Task 3: Ruling: Task 4's brief must add the shared `component:` block fixture to
  `ask-fixtures.ts` rather than let each widget's browser test declare one inline.
  Decided at the second copy rather than the fourth. Cost if wrong: a fixture
  touched once more than needed.

- Ruling: carry to Task 8 and widen its scope — `COMPONENTS_FOR` should decide
  whether resolved types are offered where no project can exist, rather than
  inheriting the whole registry. Cost if wrong: course prompts advertise five
  widgets that can never resolve in a lesson.

- Task 2: Ruling: the plan-mandated `ask-resolved-context.browser.test.tsx` asserts
  nothing this commit can break — accepted as-is rather than fixed. Its docstring
  says so at the standard CLAUDE.md asks for and names what Task 3 widens it to.
  Cost if wrong: the provider risk it was meant to cover stays uncovered until
  Task 3, and if Task 3 forgets, a missing provider takes a whole answer down.
  Mitigated by carrying the instruction into Task 3's dispatch.

- Task 2: Ruling: promoted two Minor findings into fix round 1 — unstyled
  `.cmp-ref-missing`/`.cmp-ref-quiet` classes, and `matchEntities` ignoring
  `truncated` (a substring match can yield a 200-button picker). Both are a few
  lines and five widgets inherit them. Cost if wrong: one extra fix round.

- Task 7: Ruling: carried into Task 8 — `<tr key={row.label}>` collides when a
  model writes two rows with the same label, and the registry does not forbid
  duplicates. It renders correctly with a React key warning rather than wrongly.
  Whether duplicate labels are an authoring error is a REGISTRY decision, not a
  widget one, and Task 8 owns the registry's authoring surface. Cost if wrong: a
  console warning on a malformed authored table.

- Task 7: Ruling: the spec gap "nothing links" is fixed by ADDING the link, not by
  dropping the claim from the registry summary — resolution-plus-linking is the
  whole of what `compare` adds over a plain markdown table. And it is fixed at the
  SHAPE level in `ResolvedFrame`, not in `CompareWidget`, because no resolved
  widget currently links and fixing one would be a new inconsistency; this makes
  definition, graph and compare agree. Reuse `GraphDetail`'s existing console href
  rather than inventing a URL shape. Fallback if that drags console state into the
  frame: drop "links" from the summary instead. Cost if wrong: a shape-level
  change late in the plan, touching three widgets' suites.

- Task 8: CORRECTION to my own Task 6 ruling. I told Task 8 that narrowing the
  timeline's from/to window prunes no server work because the two passes precede
  the interval. Task 8 checked and found the bounds ARE passed into redstring's
  TemporalQuery, so my claim was unverified. It verified only what it could see
  (two passes, `limit` applied last as `bands[:capped]`, uncached) and left the
  window out of the craft note rather than writing an unmeasured claim into a
  prompt. Correct call. If the window claim is ever wanted in the prompt it needs
  a measurement nobody has taken.


## Wave B — the explorer

- Ruling: `over` is `Spec(text, required=True)` plus a whole-body `warn` hook, NOT
  `one_of`. The spec wants an unsupported `over:` to warn AND still render as
  prose; `one_of` makes it an error, which routes the block to
  `BrokenComponent` and leaves no widget to render anything. `one_of` is the
  obvious implementation and it is wrong. Every dispatch and review must carry
  this, because a reviewer "simplifying" it to `one_of` turns the prose test red
  for a reason that is not obvious from the failure.
  Cost if wrong: an unsupported backing read renders as a broken-component panel
  instead of prose, against spec §1's degradation rule.

- Ruling: two queries sharing one key builder — display query = full parameter
  set, vocabulary query = same window with `entityType: null`, enabled only when
  `entity_type` is in `vary`. Identical keys dedupe to ONE request when the
  author fixed no type; TWO on mount when they did. The cost test asserts the
  number rather than tolerating it. This resolves §1 ("one read gives view and
  vocabulary") against §7 ("each control varies the query"), which cannot both
  be literally true — a filtered response cannot enumerate what it filtered out.
  Cost if wrong: one extra request per mount on a route that is two full passes
  over the tenant's entity set.

- Ruling: `limit` is NOT an offered `vary` axis, and the validator rejects it by
  name. It bounds the response, not the server's work, so a reader given that
  control changes the picture without changing the cost and learns the wrong
  thing about which knob is expensive.
  Cost if wrong: readers cannot cap a long result themselves.

- Ruling: `vary` REJECTS an unknown axis while `over` WARNS. Deliberate asymmetry:
  an unknown `over` names a coherent intent this build cannot serve and should
  degrade; an unknown axis names a control that simply would not be drawn.

- Task 1: Ruling: `ASK_COMPONENT_PROMPT`'s "The other five" enumeration omitting
  `explorer` is THIS TASK's defect, not pre-existing — it was true before 0f2f9b5
  and false after. Same class as a wrong measurement, not lesser: it is prompt
  text a model reads every authoring turn, giving it a false inventory of what it
  may write, and the generated half of the same prompt contradicted it.
  Cost if wrong: a fix round spent on prose.

- Task 1: Ruling: prevent recurrence with a TEST, not by generating the
  enumeration. The surrounding prose does work a generated list cannot — the
  graded/resolved split, the "degrades to plain words" promise, the explorer
  clause — so the hand-written paragraph stays hand-written and only the
  INVENTORY agreement is asserted. The test splits at the first fence, because
  searching the whole string would pass on the exact defect (the missing name is
  present in the generated half). Proved red by reverting the paragraph to its
  0f2f9b5 wording. Cost if wrong: the paragraph can still describe six correct
  names wrongly, and only reading it catches that — stated in its docstring.

- Task 3: Ruling: `staleTime: Infinity` on the EXPLORER's two queries only, NOT on
  the shared `resolvedWidgetQuery`. The shared 5-minute policy is right for
  definition/graph/timeline, whose data genuinely changes under them as
  extraction runs; the explorer is the odd one out. Spec §4's "cached for the
  session" means the sitting, not five minutes. Cost, to be stated in the
  comment rather than only the benefit: a reader leaving the widget mounted for
  an hour sees bands that no longer reflect the corpus, with no refresh
  affordance. Cost if wrong: a long-lived explorer shows stale bands.

- Task 3: Ruling: add the missing cost case rather than narrowing the comment —
  the comment makes the right promise (a window commit with a fixed type costs
  TWO reads, not one) and only lacked the assertion behind it.

- Task 3: Ruling: carry to wave B's FINAL REVIEW to triage, do not expand Task 3 —
  the shared `resolvedWidgetQuery`'s `staleTime: 5 * 60_000` sits against a
  default `gcTime` of the same five minutes, so definition/graph/timeline entries
  are evicted at roughly the moment they go stale, and its comment therefore
  overclaims for any widget that unmounts and remounts. Impact is modest (a widget
  stays mounted while an answer is read), but the comment should not promise more
  than it delivers. Cost if wrong: a shared comment overclaims for one more wave.

- Task 4: Ruling: sent back for the red proofs the implementer had skipped "given
  the effort budget" (2 of 11). Not optional here — the file is full of absence
  assertions, and CLAUDE.md says a selector matching nothing is indistinguishable
  from one that matches, so an unproven absence assertion is the classic vacuous
  jsdom test. All 11 subsequently proved red by temporary widget mutations, each
  reverted, with `git diff --stat` empty after every revert. None failed to go
  red. Tree byte-identical afterwards, so no re-review dispatched — the artifact
  is the proof log, not a diff. Cost if wrong: one extra round on a green suite.

- Task 5: Ruling: KEEP `flex-basis: 100%` though the ordering assertion cannot fail
  for it — measured, both runs: note top 187.94 vs last-field bottom 175.94 with
  AND without the rule, because the note's sentence (395.09px) plus three fields
  (336px) already overflows the row's 564px content box, so it wraps regardless.
  The declaration is load-bearing only at a width or sentence length this suite
  does not have, and the note's wording is authored prose in the widget, so a
  shorter sentence would change the answer. The implementer kept the ordering
  assertion as a statement of intent with a comment saying it cannot fail for
  this rule, and added the one that IS red on revert: the note's width against
  the row's content box, 564 vs 395.09. Cost if wrong: one declaration whose
  only witness is a width assertion at a single viewport.

- Final: Ruling: Important 2 — `gcTime: Infinity` leaks across widgets because
  `ExplorerWidget` and `TimelineWidget` share `queryKeys.timeline`, and `gcTime`
  resolves per cache ENTRY as the max across observers. Fixed the COMMENT, not
  the keys: scoping the explorer's keys would split the cache and cost a second
  identical request whenever an answer carries both, which is worse than the
  leak. Cost if wrong: a shared entry is retained longer than the timeline widget
  asked for — one held response, no behaviour change.


## Socratic, Plan 1 — domain and persistence

- Ruling: OVERTURNED the plan-author's field ownership. `prompt` is the SYSTEM's
  utterance and `reply` is the READER's — the intuitive reading. Its citations
  argument did not decide the question: both fields sit on the same event either
  way, so the argument only proves citations belong on that event, which was
  never in doubt. What decides it is that a socratic dialogue leads by
  questioning, so naming the reader's text `prompt` inverts the word's ordinary
  sense in the one surface whose premise is that the direction is reversed. It
  should NOT map 1:1 onto `AskTurnRecorded`'s question/answer; that inversion is
  the feature, and a layout hiding it is how someone later writes a socratic turn
  that behaves like an ask turn. Pinned twice (aggregate and storage), because a
  swap produces a transcript that still reads as a conversation — just one where
  the reader asks all the questions.
  Cost if wrong: every layer touched, and the plan-author had to redo a design.

- CORRECTION to my own record: I first wrote that plan-b's answer convinced me
  "a turn is a completed question-and-answer pair, so the newest question belongs
  to no turn". That was its WRONG step and the thing that produced `next_prompt`.
  The naming ruling fixes who owns each FIELD; it does not fix which utterances a
  TURN pairs. `SocraticPrompt` and `pending_prompt` are still the right names, but
  on the naming ruling alone, not on that argument.

- Ruling: REJECTED the `next_prompt` field the overturn initially forced, and the
  plan-author then found a better answer than either alternative I offered. The
  naming ruling fixed who owns each FIELD, not which utterances a TURN pairs;
  conflating the two made a turn `(question, answer-to-it)` and needed a third
  field for the question that followed, storing every system utterance twice
  where the copies could drift on a rebuild. The fix is to re-pair: a turn is
  `(reply, prompt)` — the reader's answer and the response it drew — so the log
  reads Q1 A1 Q2 A2 Q3 with nothing stored twice, and it is exactly one executor
  call per event (reply in, prompt out). The opening question lives on
  `SocraticDialogueStarted.opening_prompt`, since the framing and the first
  question are one decision the model makes from the topic. The terminal case
  needs no special field: the last turn's `prompt` is whatever the dialogue said
  as it concluded, and `SocraticDialogueConcluded` is what says it ended.
  `pending_prompt` survives only as a projection-DERIVED row field, not as state
  — state nothing reads is state that can disagree with the log.
  Rejected my own two alternatives: an empty trailing turn stores a turn that
  never happened, and an explicit opening event duplicates what
  `SocraticDialogueStarted` already has room for.
  My condition (assert turn N's next_prompt equals turn N+1's prompt) could not
  be written afterwards, because the duplication it was meant to pin no longer
  exists — the better outcome. It was applied instead to the one genuinely
  derived value left: `SocraticDialogueRow.pending_prompt`, the newest turn's
  `prompt` precomputed so a client need not fetch every turn to learn what it is
  answering. `test_a_rebuild_reproduces_the_positions_and_the_derived_question`
  asserts the invariant on both sides of a rebuild, which is where a projection
  that wrote it on start and forgot to overwrite it per turn would surface — a
  dialogue whose transcript reads perfectly and whose "what am I answering?" is a
  question from three exchanges ago.
  Cost if wrong: a resumed dialogue's first utterance is the one thing living
  outside the turns table, so a turns-only rehydrate produces a history starting
  with the reader answering something nobody asked. That is now the resumption
  test's fourth enumerated failure mode, and `SocraticTurnRow`'s docstring warns
  Plan 3 that a client rendering only the turns table draws a transcript starting
  with the reader.

- Task 1: Ruling: the deliberately-red resumption test must not abort collection.
  Original shape was a module-level import raising ModuleNotFoundError, which
  takes the WHOLE suite down until Task 3 — and CI runs a bare pytest, so the
  branch would be unreadable for two tasks. Rejected carrying
  `--continue-on-collection-errors`. Chosen: imports moved inside the functions
  plus `@pytest.mark.xfail(strict=True)`. That gets three properties at once —
  the suite collects and stays green, the test is still genuinely red (xfail
  records a known failure rather than passing), and `strict=True` makes the suite
  go RED on an unexpected pass, so Task 3 must delete the marker deliberately
  rather than leave a permanently-excused test. Verified empirically, not
  assumed: a throwaway strict-xfail that passes reports FAILED [XPASS(strict)],
  and pyproject sets no `xfail_strict`, so the explicit flag is the authority.
  Assertions confirmed unchanged by the move: 13 vs 13, zero differences.
  Cost if wrong: a red test that looks green. Mitigated by strict=True.

- Task 1: Ruling: reorder the `decide` arms rather than narrow the comment — the
  error message was simply wrong for one command ("already started" against a
  concluded dialogue), and the ordering is what a fifth command inherits.
  Verified safe: a `new` state can never be concluded, so the arm that must win
  is unaffected, and the new test asserts `match="already concluded"` so it
  genuinely distinguishes the orderings rather than merely asserting a raise.

- Task 2: Ruling: commit the throwaway probe as a real test rather than leave the
  measurement as prose in a report. It is the only demonstration that a dropped
  handler yields a silently empty read model rather than a failure, and it is
  what justifies every assertion in that file being "a row exists with the value
  the event carried". The reviewer added a refinement worth keeping: with
  `@handles` removed the event is never DELIVERED (filtering — `SubscriptionConfig`
  leaves `event_types=None`, `EventFilter.from_subscriber` derives the filter from
  the `@handles` set), which is a different mechanism from CLAUDE.md's "delivered
  but nothing rejected it counts as APPLIED". Both are true; identical silence.
  Cost if wrong: a one-second fixed settle means a slow machine passes the test
  for the wrong reason — tolerable only because the assertion is is-None, so a
  false pass proves nothing rather than shipping a defect. Stated in its docstring.

- Ruling: NOTHING in Plans 1 or 2 writes `SocraticDialogueConcluded`, so a dialogue
  ends only when the reader stops — which makes it the ask with a different
  prompt, against the spec's opening premise that it "stops when the reader has
  demonstrated something rather than when they stop typing". Plans 1+2 still ship
  (a durable, resumable, gradeable dialogue is real progress) but the gap becomes
  **Plan 4, "concluding a dialogue"**, planned after Plan 3 — NOT folded into
  Plan 2 and NOT merged into Plan 3. Two reasons: it is agent judgement where
  Plan 3 is a frontend slice, so merging means one review pass covering a parser
  and a stylesheet; and the second parse's failure mode is SILENT ("not
  concluded" rather than raising), which needs its own red proofs rather than
  riding along at the end of another plan. Plan 2 must make the gap loud where
  someone meets it: header scope section, plus a comment on the
  `concluded`/`observation` defaults naming Plan 4 and saying the terminal status
  Task 1 built is unreachable until then — a terminal state nothing can reach is
  what a later reader assumes is dead code and deletes.
  Cost if wrong: the headline behaviour ships one slice later than the surface.

- Ruling: the Plan 1 Task 5 / Plan 2 Task 5 collision on `create_app(dialogues=)`
  resolves by ordering — Plan 1 Task 5 runs next, before any of Plan 2. The
  plan-author's defensive "add it if absent and say so in the commit" step stays
  anyway; it costs nothing and is right if the order ever changes.

- Ruling: the scoped re-review of Task 5's fix round is folded into the Plan 1
  final whole-branch review rather than dispatched separately — the final
  reviewer sees the same diff and verifying four small findings there costs one
  dispatch instead of two. Cost if wrong: a fix round reviewed once, by a
  reviewer with more context rather than less.


## Socratic, Plan 2 — the agent and its routes

- Ruling: nothing in Plans 1 or 2 writes `SocraticDialogueConcluded`, so a dialogue
  ends only when the reader stops. That is PLAN 4's job, deferred rather than
  folded in because it is agent judgement (Plan 3 is frontend) and because the
  parse fails SILENTLY — "not concluded" rather than raising — so it needs its own
  red proofs. Plan 2 states the gap in three places, including that the terminal
  status and the `decide` branches behind it are unreachable through any live path
  and are NOT dead code: deleting them is the obvious tidy-up and would delete the
  thing Plan 4 is built on.

- Task 1: Ruling: carry into the Task 4 AND Task 5 briefs — nothing forces those
  tasks to call `dialogue_document` rather than inlining
  `project(parse_document(...), view=...)`, and if either inlines it the learner
  default silently stops being written down in one place. That is the ASK_PROMPT
  failure mode one level down and it looks like working software. The guard the
  implementer proposed is better than the helper it protects: assert an `mcq`
  through the REAL route whose frame contains no `correct`. It bites whether or
  not the helper is used, and it cannot be written from Task 1.
  Cost if wrong: one duplicated assertion across two tasks.

- Task 2: Ruling: carry into Task 3's brief — (a) the framing prompt's three-key
  YAML contract (goal / stopping_condition / opening_prompt) exists only as
  prose, so Task 3's parser must be derived from it or the two drift; (b)
  `SOCRATIC_TOOLS_PROMPT` duplicates the ask agent's tool claims by hand, as
  specified, so it is a second thing to keep true with no test catching a missed
  edit; (c) two Task 1 test docstrings cite `ask_agent.py:142` where the
  rebinding is at :147 — a one-line correction Task 3 can make in passing.

- Task 4: Ruling: I verified the fix round MYSELF rather than dispatch a third
  re-reviewer, after two agents idled without reporting. Checked directly:
  `asyncio.sleep` gone from the 409 precondition, replaced by
  `entered = asyncio.Event()` + `await asyncio.wait_for(entered.wait(),
  timeout=5)`; `test_a_framing_the_model_botched_is_a_502_and_not_a_400` present
  with a docstring saying it is the only thing keeping it that way and that it is
  red against `status_code=400` AND against no except clause at all;
  `_socratic_frame(note) -> str | None` with the remark carrying `kind: "remark"`.
  Cost if wrong: one fix round verified by the controller rather than a fresh
  reviewer — acceptable for a 12KB diff whose three claims are greppable.

- Task 5: Ruling: FIX the ask-surface leak rather than backlog it. `read_ask` ships
  `"answer": turn.answer` raw beside its projected blocks — the identical leak —
  and BACKLOG B106 states that route withholds the key, while the test it rests
  on asserts only that the block's `kind` is "component" while its fixture answer
  contains `correct: true`. No plan in this sequence owns it. A leak plus a
  written claim that there is no leak is worse than an unrecorded leak, because
  the claim is why nobody looks. Fixed as its own commit, separable from the
  socratic work. Cost if wrong: one commit of scope beyond the three waves.

- CORRECTION TO MY OWN COMMIT: 64dc172's message says "No other duplicate id in
  the file, checked rather than assumed." That is FALSE. I grepped only
  `^### B1[0-9][0-9]` — the B1xx range — and reported the result as if I had
  checked the file. There are ten other duplicate ids, all predating this work:
  B36, B54, B58, B59, B60, B62, B63, B79, B80, B81, each appearing twice with two
  unrelated subjects. This is precisely the defect class this sequence has spent
  the day fixing: a written claim of no problem is the reason nobody looks.
  Recorded as B116 (40edb9b) in the file the message is wrong about, since the
  message itself cannot be edited. The entry explains why the ten were not
  renumbered — ids are cited by number in unrewritable commit messages, and
  picking which of each pair keeps its number risks REDIRECTING a citation rather
  than merely duplicating it, which is worse — and gives the per-pair route
  (`git log -S'B<n>'` to see which side is cited) plus the cheaper prize, a check
  that refuses a duplicate id on the way in. Nothing lints documentation today,
  so there is no gate to hang that on and none was added.


## Socratic, Plan 3 — the console

- Ruling: Task 6 is a Python task inside a frontend plan and stays here. B114's
  reasoning decides it — "answers survive a refresh" is the whole argument for
  this surface being its own principal, and a console that ships without it ships
  the claim without the thing. Its header says it is the odd one out so its
  reviewer meets that before the file list.

- Ruling: build a THIRD `progress_view` shape rather than widening the shared
  presenter. Widening is the smaller diff and the wider blast radius — a
  presenter shared by two surfaces, widened so a third can reuse it, is how
  surfaces couple without anyone deciding to. Cost recorded: a third thing to
  keep true, and a change to how progress is reported now has three call sites.

- Ruling: the delta-stream leak was a Plan 2 follow-up done BEFORE Plan 3 executes,
  not folded in and not deferred — the bytes were on the wire, and writing this
  plan's stream tests against a leaking stream would have baked the wrong
  baseline into them.

- Task 4: Ruling: CHRONOLOGICAL ordering — the brief was WRONG and the implementer
  caught it by reading the server rather than the brief. A turn is
  `(reply, blocks)` = the reader's answer and the question it PRODUCED, so the
  true chronology is Q1 -> A1 -> Q2 -> A2 -> Q3. The brief's shape (question
  above answer) puts every question above the answer that CAUSED it rather than
  the one that responds to it, giving a reader Q2, A1, Q3, A2, Q2 — the
  outstanding question buried mid-page and the pending block a stale duplicate.
  `app.py:3117-3120` is the citation: `pendingBlocks` is "the question being
  answered, not the one about to be asked".
  The brief's eight tests all passed against the wrong shape because each fixture
  hand-paired its own `blocks` and `reply` — the FOURTH instance in this sequence
  of a fixture built by the same person in the same hour as the thing it tests,
  sampling only the cases the implementation already handles. That is now a
  CLAUDE.md entry.
  Decided: the page takes `openingBlocks` (Plan 1 Task 5 put it on the route
  views precisely because the opening question lives on the row and on no turn),
  and DROPS `pendingBlocks` from its props rather than reading it in one branch —
  a prop read conditionally is the next thing someone wires wrongly.
  And the pending rule is restated as the invariant it was actually protecting:
  not "there is a `.dlg-pending` element after the last turn" but **"the page
  never ends on the reader's own words with nothing asking them anything"**,
  which under this shape holds structurally because the last exchange ends with
  its own `blocks`. One assertion, checked in both the empty and non-empty cases.
  Cost if wrong: two of the brief's eight tests inverted and one prop dropped.

- Task 4: Ruling: attempts are half-wired (option 2) — a `use-dialogue-attempts.ts`
  mirroring the ask's, submitting through `dialogues.submitDialogueAttempt`,
  which is Plan 2 work that had no consumer until now. Adding that file is
  approved though it is outside the brief's list.
  IMPORTANT: the chronological ruling NARROWED this gap, and the implementer's
  two problems had one cause. Under option A the outstanding question IS the last
  turn's `blocks`, and a turn HAS a position — so the question the reader is
  actually answering is gradeable. It was only ungradeable under the brief's
  shape, where the outstanding question was the positionless `pendingBlocks`.
  The one remaining hole: the OPENING question of a dialogue with no turns yet.
  `openingBlocks` belongs to no turn, so there is no position to submit against,
  and inventing one would 404 because the attempts route matches against a
  `SocraticTurnRow` and no row 0 exists until the reader has answered.
  Filed with two candidate fixes, recommending the cheaper: (a) a synthetic
  position, needing a server change and a row that does not exist; or (b) A CRAFT
  NOTE telling the model not to author components in the opening question at all
  — the opening question is framing, and a graded widget there asks the reader to
  answer before the conversation has started. (b) costs one prompt sentence and
  REMOVES the case rather than plumbing it.
  Rejected option 1 (inert both): an `mcq` that renders, accepts a click and does
  not even highlight is a broken control a reader cannot distinguish from a bug
  in their own browser. Rejected option 3 as a Task 4 change: it is Task 3's file
  and now mostly unnecessary.

- Task 4: Ruling: the tests must gain a real `ContainerProvider` rather than the
  hook being guarded to dodge it. A `hasComponents` guard added for a fixture's
  benefit is the shape that hides a missing provider until the first answer that
  happens to carry a widget — and this repo already shipped a browser test
  written so it could not fail for exactly that provider risk.

- Task 4: Ruling: CARRY TO TASK 5 — the page now takes `openingBlocks` and no
  longer takes `pendingBlocks`, but Task 3's store exposes only `pendingBlocks`.
  **Put `openingBlocks` on the STORE, alongside `goal` and `stoppingCondition`,
  not captured in the view.** It is the same category of thing — the dialogue's
  framing rather than a turn — and Task 3's store already keeps framing off the
  transcript for exactly that reason. A view capturing it would need its own ref
  or state and would lose it on remount, which is the bug the store's existing
  framing fields exist to avoid. Capture the FIRST `dialogue` frame's blocks and
  stop overwriting them. It will not typecheck if ignored, so it cannot ship
  silently. Cost if wrong: one more field on a store that already holds two of
  the same kind.

- Task 4: Ruling: carry two minors into Task 5 —
  (a) a CONCLUDED dialogue still renders its last question with `.dlg-pending`,
      glowing as awaiting a reply, while the composer is replaced by "This
      dialogue has reached its goal". Nothing waits on the reader there. Task 5's
      browser test is where it would be seen, which is why it goes there.
  (b) `use-dialogue-attempts.ts` has `dialogueId!` inside the `submit` port —
      safe today because the returned `submit` short-circuits on null, but the
      assertion and its guard are in two places and a future caller of the inner
      port would not be protected. A null early return inside the port carries
      its own proof.

- Task 5: Ruling: TASK 6 TAKES CONCERN 3, the largest remaining hole. A freshly
  framed dialogue DRAWS NOTHING: `POST /dialogues` (app.py:3241) returns only
  `{"dialogueId"}` — despite its docstring claiming the goal arrives there — so
  goal, stoppingCondition and openingBlocks are all empty until the reader
  answers a question they cannot see. `GET /api/projects/{id}/dialogues/{id}`
  (app.py:3600) already serves all three; `DialogueRepository` has no read method
  for it. It is the same shape as Task 6's progress read route (a read the
  console needs) and Task 6 already touches the repository and the store.
  Also fix the POST's docstring, which claims something untrue.

- Task 5: Ruling: TASK 6 ALSO ADDS AN ENTRY POINT. `facet: 'dialogue'` has ZERO
  `projectHref` call sites where `facet: 'ask'` has three, so the surface is
  reachable only by typing `#/p/<id>/dialogue`. Placement: alongside the ask,
  because a dialogue is the same kind of thing — a conversation about the project
  — and that is where a reader looks for one. A facet with no entry point is not
  shipped. Cost if wrong: one link in the wrong place, trivially moved.


## Socratic, Plan 4 — concluding

- Ruling: judge on EVERY TURN (option A), not behind a threshold. A threshold
  defining when evidence "suggests" the condition is met would be **a second
  stopping condition — unwritten and untestable — sitting in front of the one the
  author wrote down**, and a hidden numeric gate in front of it undoes the
  argument the aggregate exists to make. Option A's real cost is contamination
  rather than tokens: asked "what next" and "are we done" together, the model
  picks the verdict that justifies the question it just wrote. Handled by
  ORDERING — `concluded` comes first in the fenced block, so the verdict is
  committed before the question exists — and by allowing an EMPTY `prompt`, so
  "nothing further to ask" is expressible rather than fabricated. Requiring a
  closing question would contradict `SOCRATIC_METHOD_PROMPT`'s own instruction
  not to ask one more to be sure.

- Ruling: Task 6 lets a reader END a dialogue — reader action only, NO IDLE SWEEP.
  A sweep needs precisely the threshold rejected above, applied to the reader's
  attention instead of their understanding; rejecting it in one place and
  accepting it in the other would be incoherent. And leaving `"abandoned"`
  unreachable leaves a second unreachable enum branch of exactly the shape this
  plan exists to remove, after real effort was spent keeping those branches from
  being tidied away as dead code. Framed as ENDING, not abandoning:
  `reason="abandoned"` is stored because it is accurate about why it ended;
  nothing the reader sees calls them a quitter.

- Task 1: Ruling: TASKS 1 AND 2 SHIP TOGETHER. From 83ee1b2 until Task 2 lands, a
  real build is told to answer in YAML and NOTHING PARSES IT —
  `DeepAgentSocraticExecutor` defaults to `SOCRATIC_PROMPT` and
  `composition.py:1988` passes no override, so a live dialogue turn would render
  the raw fenced judgement block to the reader as their next question. No test
  catches it because none drives a real model. The window is contained: nothing
  merges without asking, and Task 2 was dispatched immediately. **The branch must
  not be merged between these two commits.**

- Task 4: CORRECTION TO MY OWN DISPATCH. I told it (relaying the plan) that "no
  read route carries why a dialogue ended — `_dialogue_view` has `status`, not
  the reason". FALSE: `_dialogue_view` (app.py:3650) already returns BOTH
  `status` and `concludedReason`, verified against the tree. The real gap is
  entirely client-side — no port calls the read route, and `DialoguePage.tsx:72`
  derives `concluded` from the last transcript turn. It filed the true framing
  rather than the one I gave it, which is exactly right: an entry asserting
  something the code contradicts is worse than none, and I would have shipped one.
  Third false negative claim about the tree in this sequence, and the first that
  originated with me rather than an implementer.
