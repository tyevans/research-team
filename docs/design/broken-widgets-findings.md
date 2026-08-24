# Broken lesson widgets: two defects

Read-only investigation, 2026-08-22, branch `batched-consolidation`. Nothing
in this repository was changed.

Every claim below is marked **traced** (followed through the code, with the
file and line, and deterministic — no layout, no network, no model involved),
**measured** (a value observed from a running system or a database), or
**inferred** (consistent with the symptom and with the code, but with a step
this investigation could not close). No claim here is measured: no course
artifact survives in `~/.research-team/sessions.db` to read (**measured**:
zero events in that log carry the substring `component:`), so the rendered
lesson the user is looking at could not be recovered.

---

## Defect 1 — a bare UUID where a name belongs

**Symptom.** A widget draws a raw entity id — `9f2c1a44-…` — as its heading,
its column head, or beside "not in this project's graph".

### Cause

The course-authoring prompt hands the model entity ids and tells it to copy
them into resolved components, and never tells it which field they go in. The
field it does not name is `entity_id`; the field the model can see in the one
worked example is not that one.

- `research_team/application/course_authoring.py:80-95` — `_anchor_lines`
  writes `- Constantine (Person, id \`9f2c…\`)` into every stage prompt, and
  its docstring states the reason: a resolved component "without an entity id
  is a widget that renders `unavailable` forever".
- `research_team/application/course_authoring.py:123-126` — "give them entity
  ids from the list above and they fetch the real material".
- `research_team/application/course_authoring.py:132-134` — "A resolved
  component takes **entity ids copied exactly** from the list you were given.
  An id you invented renders as unavailable, and nothing warns you."
- `research_team/application/course_authoring.py:106-136` — `COMPONENT_GUIDE`
  is the *whole* of the widget schema the lesson turn is given. Its one worked
  example is an `mcq`, which has no entity field at all. The strings `entity:`
  and `entity_id:` do not appear in it.
- `research_team/application/course_authoring.py:194` and `:228` — the lesson
  and assessment prompts interpolate `COMPONENT_GUIDE` and nothing else.

**Traced**: the lesson turn never receives `component_reference()`. The full
field schema — the text that names `entity` and `entity_id` and carries the
craft note "`entity_id` is for pinning a name two entities share. You will not
have one; leave it out" (`components.py:826-829`) — is given only to the
socratic agent (`socratic_agent.py:176`) and the ask agent
(`ask_agent.py:145`), and to workflow stages via `component_guidance`
(`composition.py:1611`). The course-authoring path is the one authoring
surface that gets ids without a schema.

Two of the three resolved types that take an entity have nowhere else to put
one, so this is not merely likely there — it is forced:

| type | fields it has | where an id can go |
|---|---|---|
| `definition` | `entity`, `entity_id` | `entity_id` (unnamed in the prompt) |
| `graph` | `entity`, `entity_id`, `depth` | `entity_id` (unnamed in the prompt) |
| `compare` | `entities: [string]` | **nowhere** |
| `timeline` | `entity_type`, `from`, `to`, `limit` | **nowhere** |
| `explorer` | `over`, `vary`, `prompt`, window | **nowhere** |

(`components.py:626-1085`, **traced**.) A model told to give a *resolved*
component the ids it was handed, looking at a `compare` whose only entity-ish
field is `entities:`, writes the ids into `entities:`.

### What renders

`entities` is `Spec(string_list(minimum=2))`; `string_list` calls `text()`,
and `text()` rejects only mappings, lists and `None` (`components.py:217-226`).
A UUID is a valid string, so the block validates with no error and no warning.
Then, **traced**, end to end:

1. `CompareWidget.tsx:47` maps `compare.entities` to `<Head name={uuid}>`.
2. `Head` calls `useEntityReference(projectId, {entity: uuid, entityId: null})`
   (`CompareWidget.tsx:83`).
3. `use-entity-reference.ts:63-67` — `entityId` is `null`, so no pin; the
   search runs `graphs.search(projectId, uuid)`, a substring name search.
4. No entity is *named* by its own uuid, so the search returns nothing and
   `matchEntities` answers `{state: 'missing'}` (`resolved.ts:96`).
5. `ResolvedFrame.tsx:151-160` draws
   `<span className="cmp-ref-name">{name}</span>` — the raw uuid — with
   "not in this project's graph" beside it.

The same five steps hold for `definition` and `graph` if the model puts the id
in `entity:` rather than `entity_id:`.

There is a second, quieter arm. If the model writes the id into **both**
fields (`entity: 9f2c… / entity_id: 9f2c…`), `use-entity-reference.ts:57-62`
short-circuits to `resolved` on a synthesised node whose `name` is the
author's string — the uuid. The widget then works: the definition fetches, the
neighbourhood draws, `ResolvedName` links correctly — and every label on it is
a uuid (`ResolvedFrame.tsx:82-89`, `GraphWidget.tsx:110`,
`DefinitionWidget.tsx:81`). **Traced.** This arm is worth naming because it
looks like a *rendering* bug in a way the first arm does not: the data is
right and only the label is wrong.

### Reproduction

A block that renders two uuids as column heads, no error panel, table intact:

```component:compare
id: two-emperors
entities:
  - "1f0e3dad-99908345-f7439f8f-fb52c58e"
  - "3a12ffcb-6dd2b6ba-9a4ee15a-6d0e7d2c"
rows:
  - label: Reign
    cells:
      - "284-305"
      - "306-337"
```

`parse_document` accepts it with zero errors and zero warnings (**traced**
through `string_list` → `text`, and through `_compare_collisions`, which only
looks for duplicates). The browser draws two `<th>`s reading the uuids, each
followed by "not in this project's graph".

And the resolved-but-mislabelled arm:

```component:definition
id: constantine
entity: 9f2c1a44-0000-4000-8000-000000000000
entity_id: 9f2c1a44-0000-4000-8000-000000000000
```

### Why tests did not catch it

Nothing about this is a rendering fault, and every test on the rendering path
is correct.

- `ResolvedFrame.test.tsx`, `CompareWidget.test.tsx`,
  `DefinitionWidget.test.tsx` all pass fixture names like `Diocletian`. **The
  test's inputs never reach the failing case**, because the failing case is a
  well-formed string that happens to be a uuid — indistinguishable from a name
  to every line of the frontend.
- On the server side, no test asserts anything about what
  `COMPONENT_GUIDE` tells the model, and no test can: the defect is that a
  prompt omits two field names, and the prompt is a string constant that no
  assertion compares against the registry it describes. **This is the same
  shape as CLAUDE.md's port-with-one-adapter entry** — the registry was tested
  against hand-built blocks, the prompt was tested against nothing, and the
  question "does the text we give the model describe the schema we validate
  against" was never asked by anything.

### Recommended fix

The convention this repository already follows for authoring defects is the
`warn` hook plus honest prompt text, not renderer defence.

1. **Name the fields in `COMPONENT_GUIDE`** (`course_authoring.py:106`). Say
   that `definition` and `graph` take `entity:` (the name, spelled as the
   sources spell it) and `entity_id:` (the id, copied exactly), and that
   `compare`, `timeline` and `explorer` take **no** id — `compare` takes names.
   This is the root cause and the only fix that stops the model writing it.
2. **Add a `warn` hook** flagging a uuid-shaped `entity`/`entities[i]`.
   `ComponentFeedback` is already wired unconditionally into every authoring
   agent (`composition.py:1534`, `component_feedback.py`), so a warning
   reaches the model in the tool result of the write that caused it. This
   follows `_compare_collisions` and `_explorer_over` exactly: warn, never
   reject, because the block still draws.
   *Trade-off:* a uuid regex will not catch every id shape, and a project
   whose entities are genuinely named by hex strings would get a false
   warning. Warnings are not errors, so the cost is a line of noise.
3. **Do not** teach the frontend to move a uuid from `entity` to `entityId`.
   `ResolvedFrame`'s contract is that the reference degrades to *the word the
   author wrote* (`ResolvedFrame.tsx:99-102`), and a client that silently
   reinterpreted the field would resolve the widget while still having no name
   to label it with — the second arm above, reached deliberately.

**Model authoring, not rendering.** Question 4 answered directly: yes. Widget
`id`s are model-chosen (`components.py:1353-1362`, derived when absent) but
they reach only `data-component` and never a visible surface, so CLAUDE.md's
"derive ids, don't let the model pick" is *not* the defect here. The inverse
is: the model is required to copy entity ids exactly and is not told where to
put them.

---

## Defect 2 — "(empty file)" inside a widget

**Symptom.** A widget draws a padded grey monospace block reading
`(empty file)` where content belongs.

### Cause

Every widget's prose goes through one component, and that component renders an
"empty file" notice for blank input.

- `widgets.tsx:15-17` — `Prose` is
  `<Markdown source={text ?? ''} className="cmp-prose" />`.
- `content.tsx:44-50` — `Markdown` returns
  `<div className="empty">(empty file)</div>` when `isEmptyMarkdown(source)`.
- `markdown.ts:136` — `isEmptyMarkdown` is `source.trim().length === 0`.

**Traced**, and deterministic: three pure functions, no layout, no fetch. Any
`Prose` handed `''`, `null`, or whitespace prints "(empty file)".
`states.css:4-11` gives `.empty` 22px of padding and the mono face, so it is
not a subtle artefact — inside a table cell it is a tall grey box.

The reachable call sites, all **traced**:

| site | how it goes blank |
|---|---|
| `CompareWidget.tsx:63` | `row.cells[column] ?? ''` — **every padded cell of every short row** |
| `Mcq.tsx:26`, `:50` | `prompt`/`option.text` written as `""` |
| `Flashcards.tsx:66` | `front`/`back` written as `""` |
| `EvidenceWidget.tsx:47` | `claim` written as `""` |
| `DefinitionWidget.tsx:105` | a stored definition whose text is whitespace |

`Checklist.tsx:52` is the exception and already does the right thing:
`{item.note ? <Prose …/> : null}`.

**The compare row is the one that needs no authoring mistake at all.** The
registry *invites* it: `cells` is `Spec(string_list(minimum=0))` with the
comment "short rows are fine: a label with nothing under it is a real thing to
write, and the renderer pads to the column count"
(`components.py:1053-1061`), and the craft note tells the model "A short row
is padded, so a dimension one entity has and another does not is fine to leave
blank — that blank is itself the comparison" (`components.py:1082-1084`). A
model following that instruction produces a table with "(empty file)" in it.

`required=True` does not close the other rows: `text()` accepts `""`
(`components.py:217-226`), so `prompt: ""` validates as present.

### Reproduction

```component:compare
id: two-emperors
entities: [Diocletian, Constantine]
rows:
  - label: Reign
    cells: ["284-305", "306-337"]
  - label: Religious policy
    cells: ["Persecution"]
```

Row 2 column 2 is padded to `''` and draws `(empty file)`. This is the
*existing fixture* in `CompareWidget.test.tsx:48-49`.

### Why tests did not catch it

`CompareWidget.test.tsx:122-131`, "pads a short row rather than shifting its
cells left", renders exactly the reproduction above and asserts

```
expect(within(row).getAllByRole('cell')).toHaveLength(2)
```

**The test asserts the cell count, never the cell's content.** It is green
with "(empty file)" in the padded cell and green with the cell blank; it
cannot tell the two apart. This is CLAUDE.md's "a test that would pass with
the change reverted" in miniature — the assertion was written against the
defect it was guarding (cells shifting left) and not against what the guard
actually draws. jsdom is not the reason here: the text is in the DOM and
`getByText('(empty file)')` would have found it.

`content.stories.tsx:106-113` documents the "(empty file)" state deliberately
— for a *file*, which is where it is right. Nothing connects that story to the
fact that widget prose runs through the same component.

### Recommended fix

The convention is already written down twice in this feature — name the
missing thing, never quote it as empty (`ExplorerWidget.tsx:76-81`, tested at
`ExplorerWidget.test.tsx:148`) — and once as a guard (`Checklist.tsx:52`).

1. **`Prose` returns `null` for blank text** (`widgets.tsx:15-17`). One change,
   one component, and it fixes all five sites; `Markdown` keeps its
   "(empty file)" for `FileView` and `TopicDocuments`, where a genuinely empty
   file *should* say so.
   *Trade-off, stated plainly:* a required prose field the model wrote as `""`
   then renders as nothing rather than as a visible complaint — a silent
   absence where there is currently a loud wrong one. That is the right trade
   for `compare` (an empty cell is the intended output, per the craft note)
   and the wrong one for `mcq.prompt` (a question with no text is a defect).
2. **So pair it with a server-side warning** for a required text field that is
   present and blank — again through `warn`/`ComponentFeedback`, which the
   authoring model already hears. That puts the complaint where it can be
   acted on instead of in front of a reader.
3. **Fix the test that covered this** (`CompareWidget.test.tsx:122`): assert
   the padded cell's *text* is empty, not that a cell exists. Prove it red
   against today's build first — it will be, with `(empty file)` as the actual.

**Not a server-side resolution failure.** `parse_document` never emits an
empty markdown block (`components.py:1411-1412`, `if chunk.strip():`), so the
"(empty file)" the user is seeing cannot come from the prose between widgets.
`_read_file` (`app.py:4442-4462`) does return `""` for a file entry with no
`content` key, and `FileView.tsx:211` / `TopicDocuments.tsx:202` would then
render "(empty file)" for the whole file — but that is the file-level notice
doing its job, and it looks different from a notice sitting *inside* a widget.
**Inferred**, from the symptom's description ("where content belongs" in a
widget) rather than from an observation of the user's screen.

---

## Are these two bugs, or one?

Two, independent, with different owners. Defect 1 is a prompt that omits two
field names; defect 2 is a shared prose component with the wrong empty state
for the container it is in. Neither fix touches the other's files. They share
only a cause of a third kind: **both are cases where a widget's degraded state
is drawn correctly and the thing being degraded is wrong**, which is why every
test on the degradation path is green.
