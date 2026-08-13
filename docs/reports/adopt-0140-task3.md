# Task 3: the record

Prose only. No Python changed.

## `docs/direction.md` §1

Rewritten from two proposals into what happened, titled "— both landed" and
kept in place, following §4's precedent for a built item rather than being moved
or deleted. It carries three lessons.

- **The ergonomics prediction was wrong in a nameable direction.** Both halves
  of "it fails earlier and names the command type, which is the better message"
  are false against the release: the library's message names strictly more, and
  "earlier" was before `decide` versus after it with no I/O, no persistence and
  no applied event in between. The entry now says the bias, not just the error —
  the prediction overvalued the local version, the one whose message and timing
  were known in detail.
- **The read-model half adopted the other function.** `reconcile_read_model_schema`
  does the whole job and takes a SQLAlchemy connection nothing here owns; the
  pure generator slotted in unchanged.
- **The stricter upstream is a loss as well as a gain**, which is the one the
  spec got materially wrong. It called the categorical refusal pure gain. It is
  gain on a populated table and a loss on an empty one, and an empty one is the
  `SessionSummaryRow.project_id` case the mechanism exists for — which is why
  applying the plan verbatim broke the regression test `CLAUDE.md` names. The
  entry ends on the part that generalises: the difference only surfaced because
  a regression test held the old behaviour in place.

## `BACKLOG.md`

**Nothing to close.** Searched for `targeting.py`, `_column_definitions`,
`apply_schema`, `CorpusStore` and `executescript` across `BACKLOG.md`; no entry
names any of them. (The only hits repo-wide in these two documents were in
`direction.md` §1 itself.) So no entry was updated and none was closed — this
change closed no deferred work that was ever written down.

**One entry added: B47**, on Task 2's flag. It earns a place on the asymmetry
rather than on the bare gap: the refusal branch is pinned by
`test_a_refused_reconcile_leaves_the_table_untouched`, and the branch beside it
is the only one in the file that *drops a table*, reached incidentally by a test
that is about something else and guarded by a single `SELECT 1 ... LIMIT 1`
whose sense could invert with nothing turning red. The entry names the two cases
a test would need and where the branch came from.

## `CLAUDE.md`

The "Read models" section's description had gone stale — `apply_schema` no
longer merely "reconciles added columns", and its behaviour on a required column
with no default now differs from SQLite's. Added one paragraph after the
existing one describing the two branches and why the split exists. The incident,
the named regression test and the rule ("run it against a database that predates
the change") are untouched; they are why the section exists and none of them
changed.

## Gates

```
$ uv run ruff check .
All checks passed!
$ uv run ruff format --check .
216 files already formatted
```

Both repo-wide, run after the edits. No Python was touched, so this confirms
nothing drifted rather than checking this task's work.
