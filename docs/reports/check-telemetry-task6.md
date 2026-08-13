# Check telemetry, Task 6: the record

Prose only. No Python was changed; both ruff gates were run repository-wide
anyway and are clean (`All checks passed!`, `216 files already formatted`).

## What changed

**`docs/direction.md` §4, rewritten.** Retitled "Closing the loop on checks —
built" and opening with the defects section's own justification for keeping a
closed item: the general form outlived the work. It now states what exists
(`StageChecksEvaluated`, the `review_id` join, the fold, `/checks`), carries the
denominator lesson as the generalizable part, and lists what is measured and
what is not — no duration on the tool path, policy approvals beside the override
rate rather than inside it, standing gates marked rather than hidden. It closes
by pointing at B22 and B38 as still open.

Left in place under "Worth building" rather than moved. The section is ordered
by confidence and the entry is numbered; moving it would renumber items 5-8 and
break any reference to them, for no gain the "— built" title does not already
give. Flagged because a reader could reasonably want it under a different
heading.

**`BACKLOG.md` B22 and B38** each gained a short paragraph saying the numbers
now exist and that acting on them is untouched. Neither is closed; neither
entry's original text was edited.

**Three new entries, B44-B46.** Numbering continues from B43, the highest in
use. All three sit in "Code quality" after B38.

- **B44 — no HTTP route and no browser view, deliberately.** Carries the spec's
  reasoning and its trigger: someone wanting these numbers who is not editing
  `checks.py`. Adds one thing the spec does not: if the trigger fires, the
  surface must read through `summarise`, because the honesty constraints are
  guards in that function rather than notes in a docstring, and a view that
  recomputed from rows would not inherit them.
- **B45 — the misnamed test.** See below.
- **B46 — no end-to-end test to a rendered `/checks` table.** Written with the
  reason rather than the gap, per the brief. Judged worth an entry because the
  uncovered seam is the projection keeping up with a real store in a real
  composition, and Task 4 *measured* that a wrong `caught_up` there fails as a
  bare `TimeoutError` naming nothing — a gap whose failure mode is that
  unhelpful is worth recording. `check_telemetry_caught_up()` having no caller
  is noted in the same entry, since it is the same uncovered seam.

**`README.md`** does list REPL commands (a table at line 192). Added `/checks`
directly after `/health`, matching the ordering and the wording of the help text
in `repl.py:63`.

## Task 3's diagnosis: confirmed, and it is slightly worse than reported

Verified against the code rather than taken on report.

`tests/application/test_stage_runner.py:335` binds
`Check(check="shared.orphan", params={"artifact_type": "Intent"})`.
`OrphanParams` (`checks.py:518`) declares exactly `type` and `must_link_to`;
`Params` sets `extra="forbid"` (`checks.py:261`). `run_check` raises
`MalformedCheck` at `checks.py:354`, `review_stage` catches it at
`stage_exit.py:345` and yields one blocking finding. Task 3's account holds in
every particular.

The one detail worth adding, which makes the test weaker than "misnamed"
suggests: it passes because `StageReview.blocked` is
`bool(self.invariant_failures)` (`stage_exit.py:128-129`), so *any* non-invariant
finding satisfies both `assert condition.review.findings` and
`assert not condition.review.blocked`. The test does not merely test a blocking
finding where it meant an advisory one — its assertions cannot distinguish the
two, so the advisory case in its docstring is untested rather than
mis-exercised. B45 says this.

Also recorded there: the corrected parameters Task 3 suggests
(`{"type": "EvidenceSpec", "must_link_to": "Intent"}`) run over an empty domain
and find nothing, so a parameter fix alone leaves `assert
condition.review.findings` failing. Whoever picks it up needs a course fixture
that produces a real advisory finding, not a one-line edit. Task 3 called it a
"one-line fix"; it is not.

## Flagged rather than fixed

- **`direction.md` said "seventeen checks"; the spec says twenty-two.** The
  sentence containing it was rewritten out, so the discrepancy is gone from §4
  rather than resolved. I did not count the registry or audit the rest of the
  file for the same number.
- **B44's placement.** It is an interface decision filed under "Code quality",
  where B22 and B38 already are, so the check-telemetry entries stay together.
  A reader looking for it beside B17 (the browser's approve/reject gap) will not
  find it there.
- **Nothing verifies the README table against `repl.py`'s help text.** They are
  two hand-maintained lists of the same commands and I matched them by eye.
</content>
</invoke>
