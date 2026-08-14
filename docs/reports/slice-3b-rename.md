# Slice 3b — `TopicStatusDialog` becomes `TopicManagePane`

The debt task B recorded as owed. A rename plus comment repair, no behaviour
change. Nothing committed.

---

## Mechanical summary

Two files moved with `git mv`, so history follows:

| From | To |
| --- | --- |
| `frontend/src/presentation/research/TopicStatusDialog.tsx` | `TopicManagePane.tsx` |
| `frontend/src/presentation/research/TopicStatusDialog.test.tsx` | `TopicManagePane.test.tsx` |

The export, the import in `TopicList.tsx`, every JSX use, and the test file's
ten `should never call …()` stub messages are renamed outright. The test
harness helper `renderDialog` is `renderPane` — a live identifier that named
the wrong thing, and not something `grep TopicStatusDialog` would have found.

The component's docstring paragraph beginning **"The name is now wrong and is
kept anyway"** is deleted rather than rewritten. It existed to record the debt
this task pays; keeping it would be the only false sentence left in the file.

**Other spellings checked and clean:** no `topic-status-dialog`, no
`data-` attribute, test id or CSS class carrying the old name, and no
reference in `frontend/scripts/check-deleted.mjs`. `grep -rni
"topicstatusdialog\|topic-status-dialog\|status dialog" frontend/src` now
returns nothing.

**Deliberately not touched: `docs/`.** Nine files there name
`TopicStatusDialog` — `component-system-spec.md`, `ui-foundations.md`,
`increment-c-plan.md`, the slice reports and the 2026-08-08 plan. Those are
dated design records and rewriting them would falsify the record. One
exception is worth a follow-up rather than a silent edit:
**`docs/features-research-view.md` §4 "The topic dialog"** is live reference
documentation, not a record, and is now stale in both its title and its file
path.

## Verification

- `npx tsc --noEmit` — clean.
- `npx vitest run src/presentation/research src/presentation/entity/topic
  src/presentation/common/Drawer.test.tsx
  src/presentation/session/FileHistory.test.tsx src/domain/entity` —
  **22 files, 174 tests, all pass.** Serialised under `flock
  /tmp/rt-vitest.lock`.
- `prettier --check` and `eslint` over every file touched — clean.
- `npm run verify`, `pytest` and `ruff` not run, per the brief.

---

## The comments rewritten rather than renamed

Nine. Each one is a place where substituting the new name into the old
sentence would have produced a confident false statement.

### 1. `common/Drawer.tsx:63` — "is the same omission **still live**"

> `TopicStatusDialog` is the same omission still live, and every `Drawer` in
> the workbench is a third.

The sentence is about drawer callers that forget to pad their body. The panel
is not a `Drawer` any more, so it is not a caller at all and cannot be an
omission, live or otherwise. A blind rename would have asserted that
`TopicManagePane` is a `Drawer` with a padding bug — a claim that would send
the next reader looking for a `flush` prop that does not exist. Rewritten to
past tense, naming what it became and when.

### 2. `common/Drawer.test.tsx:226` — the "three of four" count

> three of four did it and `TopicStatusDialog` did not

Same defect, in the test that holds the default. The count is a historical
census of `Drawer` callers, and the panel has left the population — so the
renamed sentence would be arithmetic about a set the component is not in. The
rewrite keeps the anecdote in the past and adds the sentence that makes the
test's own choice legible: the panel can no longer be the caller that forgets,
which is *why* the assertion holds the default rather than the anecdote.

### 3. `styles/tree.css:458` — "the fourth was"

> the fourth was `TopicStatusDialog`, which had the identical defect

The third instance of the same population claim, in the stylesheet comment
that records why `.confirm` lost its padding rule. Rewritten to name the
panel descriptively, with a parenthesis stating that it is `TopicManagePane`
now and no longer one of the four — because the count is load-bearing (it is
the whole argument that the default was wrong) and a reader who counts today
finds three.

### 4. `research/TopicList.test.tsx:153` — why `OverlayHost` is in the harness

> `OverlayHost` joined it when `TopicStatusDialog` became a `Drawer`. …
> the dialog it opens is an `Overlay` now

Both sentences are now false, and this is the one where the rename would have
done real damage: it would have said `TopicManagePane` is an `Overlay`, which
is the exact opposite of what slice 3b did to it. Worse, the stated reason for
the host had evaporated, so the next person to read it would reasonably delete
the host.

**It is still needed, for a reason nobody had written down.** `TopicRow`
renders the Manage verb inside a `Menu` and `TopicQueue` renders `Tooltip`s;
both portal into the host's container via `useLayer` and render `null` without
one. Every test here that opens Manage would fail without the host, and the
failure would name neither the menu nor the host. Rewritten to say that, and
to keep the `null`-not-`document.body` argument, which is still correct.

### 5. `entity/topic/TopicDetail.tsx:13-25` — two claims, both stale

Cites `TopicList.tsx:41` (the line has moved and the comment there no longer
says what is quoted), and asserts the panel renders the question as `<h3
className="drawer-title">`. Task B replaced that with utilities, so the class
does not appear in `frontend/src` outside these comments. Rewritten to past
tense, and I added the thing the comment was closest to saying and did not:
**nothing mounts `TopicDetail` at all** — it is imported by its own test and by
`Topic.stories.tsx` and by no component — so the R-F3.10 gap is closed in the
workbench and still open in the console.

### 6. `entity/topic/TopicDetail.test.tsx:12` and `:123`

The same two claims in the test file, plus two test names
(`renders the rationale the dialog fetches and never shows`). The names are
renamed; the `drawer-title` comment is rewritten to past tense and now states
what the assertion actually holds — the heading role and level — rather than
a class comparison neither side of which is still true.

### 7. `entity/topic/Topic.stories.tsx:12-13` — the same, in prose only

Says "in the status dialog" without the identifier, so `grep
TopicStatusDialog` misses it. Both halves of its two-markups comparison are
stale: the queue's class is `.ent-topic-question` now, not `.topic-question`.
Rewritten to past tense, keeping the argument (one entity, one markup) that
justifies the story.

### 8. `domain/entity/status.ts:4` — line numbers, and a tense

> is **currently** written three times as `status.replace('_', ' ')` —
> `TopicList.tsx:321`, `TopicStatusDialog.tsx:156` and `:173`

Present tense about a state this module abolished. `TopicList.tsx` is 67 lines
long, and the pane calls `statusLabel`. Rewritten to past tense with the line
numbers dropped, and the reason for dropping them stated: they were stale
within a slice, which is the argument against citing them at all.

### 9. `research/TopicList.test.tsx:205` — the trigger comment

> `TopicDetail`, which the Manage dialog shows, renders them.

`TopicManagePane` does not render `TopicDetail`, and neither does anything
else. This is the finding I would not have gone looking for: the test that
removed triggers from the row justified the removal by pointing at a place a
reader could still read them, and that place is not mounted. Rewritten to say
so plainly — the wording is genuinely lost in the console today, and the
component that would restore it exists and is unwired.

---

## Already-stale references found and **not** fixed

One cluster, deliberately left, because fixing it is a different job in files
other tasks are holding.

**The "three copies of `.replace('_', ' ')`" claim is written in the present
tense in five more places** and is false in all of them, the same way
`status.ts` was: `EntityStatus.tsx:48` ("is written three times … today"),
`TopicRow.tsx:87`, `TopicQueue.tsx:185`, `TopicRow.test.tsx:37` and
`TopicQueue.test.tsx:35`. None names `TopicStatusDialog`, so none is in this
rename's scope, and three of the five files are modified in this tree by other
slice-3b tasks. I fixed `status.ts` because it named the renamed file; the
result is that `status.ts` now speaks in the past tense while its siblings say
"today". **That inconsistency is visible and was pre-existing — worth a single
sweep, not five conflicting edits.**
