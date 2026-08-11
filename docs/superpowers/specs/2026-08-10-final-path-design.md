# The final path

`component-system-spec.md` §11 planned seven phases. Five of them have shipped
or been overtaken, and the two that remain cost something quite different from
what that document priced. This is the revised path, written against the tree
as it stands on 2026-08-10 rather than against the tree §11 was written for.

## Why the spec needed revising

Two of its premises are no longer true.

**The Radix premise was replaced, and the replacement worked.** §3.1 argued for
buying behaviour and owning appearance. What shipped instead is first-party:
`OverlayHost`, `Drawer`, `Confirm`, `Disclosure`, `VirtualList`, and the
timeline's grid semantics. No `@radix-ui` package is installed. This was not a
decision anybody wrote down — it happened one component at a time — but the
result is well-tested and there is no defect behind rewriting it. The place the
Radix argument survives intact is the *floating* layer, where positioning and
collision detection are the parts that are genuinely hard to hand-roll, and
where the spec's prediction that we would get it wrong is still credible.

**Phase 5 was priced as if Phase 7 were distant.** It is 5,976 lines across 22
stylesheets, attached to markup that Phase 7 rebuilds. Porting that CSS to
utilities and then deleting the screens it styles is work done twice. Phase 5
is therefore dissolved rather than scheduled — see the rule below.

Three phases in a row turned out partly pre-done during the last session,
because §11 was written against a tree snapshot that no longer exists. That is
the failure this document exists to stop repeating: **verify against the tree,
not against the plan.**

## The increments

Five, each shippable alone and worth having if the next never happens.

### A — The decision bar

`unified-ui-proposal.md` §9, unchanged. It is first because it is true under
every version of the merge and under no version of it: an approval must reach a
person regardless of how many pages there are. Its stated prerequisite — tests
in `presentation/session/`, which had one test file for twelve components — is
already paid.

Four changes, in dependency order:

1. `approvalDto` gains `allowed_decisions: z.array(z.string()).default([])` and
   an optional `context`. Both are already serialised at
   `interfaces/web/approvals.py:51,54`, on the REST route *and* the
   `ApprovalRequested` SSE frame.
2. `Approval` gains `allowedDecisions` and `context`; `ApprovalDecision` widens
   to four values, offered only where `allowedDecisions` names them.
   `send_back`/`halt` render **named-and-unavailable with the reason**, not
   hidden. R-F6.9 — empty is not the same as unavailable — is the same mistake
   in a different component, and hiding them makes the console's capabilities
   depend invisibly on server state.
3. `GateReview` renders `gate_context`: stage, `blocked`, findings grouped by
   severity through the *existing* `severityLabel`
   (`domain/project/course.ts:113`), citations, `Findings.tsx`'s
   unimplemented-check warning, `findings_artifact` as a link, and
   `artifact_paths` as links **guarded for empty** — the hand-driven tool path
   passes none and the files genuinely are not there, which `gate_context`'s
   own docstring says.
4. `Approvals` moves from three call sites — session view, worker drawer, and
   the course page through the drawer — to one shell-level bar, with
   `AutonomyAllowAll` beside it. The component itself does not change.

Cost: zero new requests. The one genuinely new piece of plumbing is a
shell-level `approvalRequested`/`approvalSettled` subscription **not scoped by
session**, on the existing single `EventSource`. The approvals feed already
seeds new listeners with pending approvals (`approvals.py:137`), so a browser
that connects a moment after a call was gated still sees it.

### B — The floating layer, on Radix

`@radix-ui/react-tooltip`, `-popover`, `-dropdown-menu`, `-tabs`. Closes S-D3,
the largest block of keyboard-inaccessible content in the console: roughly
twenty explanations that exist only as `title` attributes, reachable by neither
keyboard nor touch.

**The cost this incurs, stated plainly:** two overlay models will coexist —
`OverlayHost` owning modals, Radix's dismissable-layer stack owning floating
content — and Escape must have exactly one answer. The proposal is that Radix
layers register with `OverlayHost` through the `useLayer` hook extracted in
#123, so the existing stack stays authoritative and Radix supplies only
positioning. The first commit is that bridge plus one component, so a test
settles the Escape question before three more components depend on the answer.
**If the bridge does not hold, B stays first-party and this document is wrong**
— that is a cheaper discovery than four components deep.

### C — The route merge

`unified-ui-proposal.md` §3.1's routes, §3.2's `use-panes.ts` layout, §3.3's
three regions. Sliced by **region** rather than by page: a half-migrated region
is visibly broken and a half-migrated page set is not, and the loud failure is
the one worth having. Order: QUEUE, then HOLDER, then MATERIAL's six facets.

Breaks URLs, stored pane preferences, some behaviour, and needs §6.3's one
backend change. All acceptable — the project is pre-release with no real data,
and no migration is owed.

**Phase 5 lives here, dissolved.** The rule: *new and rewritten surfaces use
Tailwind utilities; existing stylesheets are never ported, only deleted.* Each
slice deletes the stylesheets whose selectors no longer match anything, and
adds a `check-deleted.mjs` rule per deleted file so it cannot come back. The
rule is enforced by the build rather than by discipline because that mechanism
has now worked three times and discipline has not been tested.

**The known hazard.** Migrating markup silently invalidates combinator
selectors. `.extraction-failed > .extraction-summary` stopped matching when a
`<details>` became a `Disclosure` — the summary went from child to grandchild —
and nothing failed: no test, no error, just a failed extraction that quietly
stopped being red (#115). Across 22 stylesheets this will happen repeatedly.
Mitigation: before touching a screen's markup, grep its stylesheet for `>` and
`+` combinators and treat each as a claim to re-verify, not as CSS to port.

### D — The browser runner

`@storybook/addon-vitest` with browser mode, one CI job. Scoped to axe's
colour-contrast rules and S-D4's focus ring. Deliberately **after** C: contrast
and layout assertions written against screens that are about to be replaced are
assertions written twice. This is not a general migration of the vitest suite,
which would be a second project wearing this one's name.

### E — Virtualizing the timeline

Resolves #26. Virtualizing breaks the timeline's roving tabindex, because the
focused row unmounts when it scrolls out of the drawn window: the tab stop
vanishes, `aria-activedescendant` points at nothing, and `scrollIntoView`
silently stops working.

**Decision: move the tab stop to the grid container and drive the cursor with
`aria-activedescendant`.** Not the least work of the three candidates — it is
the most. It is chosen because it is the only one where the focused element is
guaranteed to exist, and because `FileList` already uses that pattern in this
codebase, so it is a second instance rather than a second convention. The two
alternatives keep roving tabindex alive by special-casing the selected row,
which makes that row behave unlike every other row; that is an invisible mode,
and S-D7 is the record of what an invisible mode costs here. #119 already put
`aria-activedescendant` on the timeline row for the column cursor, so half the
shape exists.

Last, because C settles the layout that decides how much of the timeline is
drawn at all.

## What this document does not cover

The four `/course` artifacts stranded in session `08f37266` are independent of
all five increments and gate none of them. What is recoverable will be
established by reading before anything proposes a write to
`~/.research-team/sessions.db`.

## Verification

Unchanged and non-negotiable: `uv run ruff check .`, `uv run ruff format
--check .`, `uv run pytest`, and `cd frontend && npm run verify`. All four, on
every increment. `npm run verify` chains build *after* tests, so a run that
dies partway leaves everything downstream of the failure unverified — including
the committed console, which has shipped stale once for exactly this reason.
