# Retiring two workarounds that landed upstream

`direction.md` §1 proposed two contributions to `eventsource-py`. Both are in
0.14.0. This is about adopting them, and in both cases the obvious adoption is
not the right one.

Depends on the 0.14.0 bump (`eventsource-py>=0.14.0,<0.15`), which is a separate
change.

## 1. `domain/targeting.py`

### It is redundant, and this was verified rather than assumed

`ChecksCommandTarget` rejects a command whose `target_field` names an aggregate
other than the one executing it. §1 said the library could close this "better at
`_stamp`, which sees the event's own `aggregate_id`". 0.14.0 does exactly that:
`_reject_foreign_aggregate_id` (`domain/aggregate.py:467`) is called from
`DeciderAggregate._stamp` (`domain/decider.py:108`), `apply_event` and
`create_event`.

The question that decides whether the mixin is redundant is whether a mistargeted
*command* produces a mistargeted *event*, because the library only sees the
event. It does. Every creation command stamps the id off the command, and says so
— `domain/corpus.py:166-168`:

```python
    # From the command, not the state: this is the creation
    # command, so on a fresh corpus `state.corpus_id` is None.
    aggregate_id=command.corpus_id,
```

So `Corpus(a).execute(StoreSourceDocument(corpus_id=b, ...))` produces an event
naming `b`, emitted from the aggregate `a`, and the library raises. That is the
exact scenario in `targeting.py`'s module docstring.

### Both claimed advantages are gone

`direction.md` §1 says to keep the mixin or not "on ergonomics alone — it fails
earlier and names the command type, which is the better message." Neither half
survives contact with 0.14.0.

**It does not name the command type more helpfully.** The library's message does
name it, and names three things besides
(`domain/exceptions.py:293-300`):

> `SourceDocumentStored names aggregate_id=<b> but is emitted from Corpus(<a>) while handling StoreSourceDocument. An event's aggregate_id is its stream key, so an event emitted here cannot belong to another aggregate. Drop the aggregate_id (the aggregate stamps it) or load <b> and emit from that aggregate.`

The mixin's message is `StoreSourceDocument targets <b>, but this Corpus is <a>`.
The library's is strictly better: it names the event class, both ids, the
command, and the two ways out.

**"Fails earlier" is true and does not matter.** The mixin checks before `decide`
runs; the library checks after `decide` returns and before any event is applied.
`decide` is a pure function over in-memory state — nothing is persisted, no event
is applied, and no I/O happens in between. The earlier failure buys no
observable difference.

### So the mixin goes, and the one real consequence is the exception type

`ChecksCommandTarget` raises `CommandRejectedError`. The library raises
`AggregateIdMismatchError`, which is not a subclass of it. Three places catch
`CommandRejectedError` and would stop catching this:
`infrastructure/agent/workflow_tools.py:37`, `interfaces/cli/repl.py:16`,
`interfaces/web/app.py:19`.

**This change is correct and is the point.** A mistargeted command is a
programming error, not a rejected request: no user input reaches a `target_field`
— every one of the five is an id the composition root or a use case is holding.
Rendering it as a clean 400 or a tidy REPL message says the caller asked for
something disallowed, when what happened is that the code is wrong. Letting it
surface as an unhandled error is the honest reporting.

Worth stating plainly because it is a behaviour change in the direction most
people would call a regression: an error that used to be caught is now not
caught. It is deliberate.

### What is deleted

`research_team/domain/targeting.py`, and the `ChecksCommandTarget` base and
`target_field` declaration on five aggregates: `Project` (`project.py:479`),
`CodingSession` (`session.py:348`), `AutoResearchRun` (`auto_research.py:480`),
`Corpus` (`corpus.py:277`), `Topic` (`topic.py:768`).

### What must be proved, not assumed

A test per aggregate is overkill and a test for none of them is a leap. **One
test per aggregate** is the right bar here anyway, and cheaply written: the five
are the whole population, the mixin was on all five, and "the library catches
this for `Corpus`" is not evidence about `Topic` — each has its own `decide` and
its own creation command, and the library's guarantee holds only where the event
actually carries the command's id. An aggregate whose `decide` quietly used
`state`'s id instead would lose the check silently when the mixin goes, which is
precisely the failure this whole item is about.

## 2. `apply_schema`

### The obvious adoption is the wrong one

The library offers two functions.
`reconcile_read_model_schema(conn, model_class)` does the whole job — but its
`conn` is a SQLAlchemy `AsyncConnection | AsyncEngine`
(`adapters/sql/readmodel_reconcile.py:61-63`), and every store here holds a raw
`aiosqlite.Connection`. Adopting it means threading a SQLAlchemy engine into
`SessionSummaryStore.open` and `TopicStore.open`, which today take a path and
open their own connection. That is real plumbing, and it buys a function whose
behaviour we already have.

`generate_additive_migration(model_class, existing_columns, dialect)` is the one
to take. It is **pure** — no I/O, no connection — takes the columns as a
collection and returns the `ALTER TABLE` statements
(`adapters/sql/readmodel_schema.py:260-263`), and `dialect` accepts `"sqlite"`.
It slots into `apply_schema` exactly where the local code already is, because we
already read the existing columns with `PRAGMA table_info`.

### What that deletes, and what it buys

**Deleted: `_column_definitions`** (`read_models.py:245-262`), which recovers
column definitions by regex over the generated DDL:

```python
body = re.search(r"CREATE TABLE[^(]*\((.*?)\n\);", model_schema(model), re.DOTALL)
```

Its docstring explains it parses the DDL rather than reading the model's fields
so there is one source of truth for the field→column mapping. That reasoning was
right and the upstream function satisfies it better: the generator now hands us
the statements directly, so there is no second parser to drift.

**Gained: the refusal happens before anything executes.** Today the loop issues
one `ALTER TABLE` per missing column and SQLite refuses a `NOT NULL` column with
no default partway through, leaving the earlier `ALTER`s applied — the local
comment calls that refusal "the right refusal", which it is, but it arrives
mid-loop. `generate_additive_migration` raises `ReadModelSchemaMismatchError`
before returning any statement, so a refusal leaves the table untouched.

That is the actual improvement in this half, and it is worth a test.

### `apply_schema` stays

It keeps its name, its signature and its `CREATE TABLE IF NOT EXISTS` first step,
because the library's pure function reconciles and does not create, and every
caller here needs create-or-reconcile in one call. Only the middle of it changes.

### One more call site, same bug

`CorpusStore.open` (`read_models.py:729-739`) still calls `executescript` with a
hand-written index and never reaches `apply_schema` — so a field added to
`CorpusDocumentRow` would not reach an existing database, which is the exact
defect `apply_schema` exists to prevent. `topics.py:430` already records
`apply_schema` as the required path. Fixed here: it is the same bug, one file
over, and leaving it while touching the function is choosing not to see it.

## Out of scope

- `replay(batch_size=...)`. `rebuild.py` passes no `batch_size` and now takes the
  1000 default, which is the fix working. Choosing a different number needs a
  measurement nobody has.
- Anything about redstring. 0.6.0's `resolve` alias-following and the
  `ConsolidationGraph` widening reach nothing here.
- The remaining `direction.md` §1 text. It becomes wrong when this lands and is
  updated as part of this change.

## Verification

All four gates. Beyond them:

- **A database that predates the change.** Both halves of `apply_schema` — the
  create path and the reconcile path — must be exercised against a database built
  before, not only one built from nothing.
  `test_a_database_written_before_a_field_existed_gains_its_column` already
  exists and must keep passing; the `CorpusStore` fix needs its own.
- **Five aggregates, five tests.** See above.
</content>
