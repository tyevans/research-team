# Task C — the record (items 1 and 3)

Touched `BACKLOG.md` and `docs/increment-c-plan.md`. No code, no tests.
Item 2 not started, as instructed.

## Item 1 — B54

**Not already corrected.** The first B54 (`BACKLOG.md:23`) still carried its
original heading ("...so it draws nothing") and body verbatim, with no dated
note anywhere in the entry. Grepped the surrounding text and the whole file for
a withdrawal marker before editing; the only one is B55's, at :1210.

Marked in place, following B55's convention exactly: heading rewritten to
"Premise withdrawn — the three components below draw their borders", followed by
a bold dated attributed paragraph. The entry body is preserved unedited. The
note names B55 as the source of the evidence rather than restating the built
stylesheet reading, and cites `border-style-default.browser.test.tsx:53-71` for
the measurement.

The inverse trap is explicitly **not** retracted — a paragraph says so, cites
`border-style-default.browser.test.tsx:73`, and adds that none of the three
sites is an instance of it.

Line citations fixed after verifying each by grep:
`GateReview.tsx:143`, `AutonomyAllowAll.tsx:101` and `:118`,
`DecisionBar.tsx:44` (unchanged, confirmed correct).

The second B54 (the 122px hole, :1131+) was left alone.

## Item 3 — no increment D

Written as a new **§8 in `docs/increment-c-plan.md`**, appended after §7.

Why there rather than `unified-ui-proposal.md`: the proposal is the design
argument, dated and already annotated from outside by this plan's §1 — adding a
"what comes after" section to it would put a 2026-08-14 fact inside a document
the corpus treats as frozen. The plan is the document a reader finishes when
increment C is done, and "what now?" is asked at its end. §7 ("What this plan
does not decide") is the nearest neighbour, so §8 sits beside it.

The section states the corpus stops at C, says explicitly not to invent a D,
flags the `ui-foundations.md:1014,1021` Phase D/E decoy, and names the residue
without scoping it.

Verified before writing each item down:

- `CitationList.tsx:44` — confirmed; links a citation id to the `doc` facet.
- `Breadcrumbs.tsx` — the two crumbs are at **:90 and :92**, not a 90-92 range;
  written as `:90,92`.
- `ui-foundations.md:1014,1021` — confirmed, "Phase D"/"Phase E".
- `Workers.tsx` — **audit 5's framing is superseded and the section says so.**
  The poll's docstring (`Workers.tsx:11-42`) records that a frame-driven refresh
  cannot work, with a measurement run 2026-08-14
  (`tests/integration/test_turn_visibility.py`). B59 carries the same argument.
  Recorded as a cost, not a defect.
- B56, B57, B58, B59 and §4 — all read; B58/B59/§4 grouped as one backend budget
  because B59's own text already says so.

---

# Item 2, and the two new entries

Written after reading `docs/reports/measured-task-a.md` (including both fix
rounds) and `docs/reports/measured-task-b.md` in full. Still no code and no
tests; only `BACKLOG.md` and `docs/increment-c-plan.md`.

## §6 question 3 — marked ANSWERED

Appended to the question itself rather than replacing it, so the five deferrals
stay legible beside the answer. The note is dated, gives 337/506/337 at 1181 and
the 351px tab strip that did not fit in 337, records the new floors
`344 / 342 / 352`, states that 1440 is pixel-identical and that reweighting was
rejected, and says plainly that the question's own framing is answered
**sideways**: the weights were never what was wrong and are still unmeasured.
Points at both reports and at B57 for what stays open.

## B57 — closed as answered, kept as open

**Not deleted, and not written as discharged.** The heading now reads "Measured
on 2026-08-14 — the widths were a shipped defect, and two bands of this entry
remain open", and a bolded list names the three things that were not done:
nothing below 821px was measured, the 46vh cap is inherited from the session
view rather than derived (with its guard vacuous against an empty fixture), and
the weights remain reasoned. The original entry is preserved beneath.

The 821–1180 band is written into the same entry, since B57's own closing line
("nothing on this page has been rendered below `--bp-wide`") is the sentence
task A answered — half of it.

## B56 — closed with the decision and the measurement

Heading rewritten to "Settled 2026-08-14 — the three utilities are deleted, not
repaired", with the three computed values, the fact that deleting them changed
nothing, and why deleting beat repairing.

**Deliberately not deleted, against this file's own "closed entries are deleted"
convention**, and the entry says so in its first paragraph. Two pieces of
tracked code cite B56 by name — `TruncatedText.tsx:134` and
`TruncatedText.browser.test.tsx:87` — and the convention's escape clause is to
say where the reasoning went before deleting. Deleting would have left both
citations pointing at nothing, and editing those comments is outside this task's
files. If someone later removes the citations, the entry can go.

## Two new entries: B60 and B61

Filed after B59 (highest existing id was B59; ids are handles, not a taxonomy),
in the section B58/B59 already sit in.

- **B60 — the session block's both-flanks-collapsed bug** (`responsive.css:40-45`).
  Written as **pre-existing**, with the reachability argument
  (`toggleCollapsed`, `split-tracks.ts:98`, refuses only when every pane would
  close) and the rail-form consequence (`Pane.tsx:126`). The point the entry
  leads with is the one the lead flagged: the two `responsive.css` blocks now
  carry a *difference*, so a merge done on the assumption they are the same
  shape keeps the bug. Cites task A's fix-round-1 red proof (a folded QUEUE at
  966px where a rail is 34).
- **B61 — the graph canvas's stale frame after a resize.** Filed as an
  **observation, explicitly not a defect**, with task B's numbers (`411 in 352`,
  seven boxes, settling in a few frames). The half given the most weight is the
  testing consequence: it is why the overflow claim polls, and a single read
  there fails against correct code — the failure `CLAUDE.md` warns gets filed as
  flakiness, failing in a direction load cannot explain.

## §8 residue list — updated to past tense

B57 and B56 are struck through with their outcomes; B57 keeps a "partly residue
still" clause naming the three gaps, so it does not read as discharged. A new
bullet names B60 and B61 as freshly filed and unowned — the residue list grew by
two while shrinking by one and a half, which is the honest arithmetic of the
slice.
