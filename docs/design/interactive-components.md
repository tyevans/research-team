# Interactive components


A course artifact is a markdown file, and a markdown file can carry a widget: a
fenced block whose info string names a component and whose body is YAML.

````markdown
```component:mcq
id: sev-classification-1
prompt: |
  Checkout returns 500s for 4% of requests; retries succeed.
  What severity should the Incident Commander declare?
options:
  - text: "SEV-1"
    correct: false
    feedback: "No total loss and no data loss."
  - text: "SEV-2"
    correct: true
    feedback: "Major degradation with a workaround is the textbook SEV-2."
rationale: |
  Severity is a communication decision, not a technical one.
```
````

Four types are registered — `flashcards`, `mcq`, `cloze`, `checklist`. The
syntax is fenced YAML because the author is a language model and that is the
shape it hits most reliably; the cost is that fences do not nest, so components
reference each other by `id` rather than containing each other.

Parsing happens on the server (`application/components.py`), which buys three
things a browser-side parser could not. Malformed components are reported back
to the model **in the result of the write that produced them**, so authoring
corrects itself without depending on the model choosing to call a validator.
`GET /api/sessions/{id}/files/parsed?path=&at=&view=author|learner` serves the
document as blocks, and the `learner` projection removes the answer key
structurally before it is serialised. Because it is gone, the browser cannot
grade: `POST /api/sessions/{id}/attempts` marks an answer where the key is, and
returns the feedback for the option the learner actually chose plus the
rationale, once the attempt is spent.

The honest caveat, which the UI repeats: the raw file is still readable at
`/api/sessions/{id}/files?path=` and the source toggle shows it. Until file
reads are permissioned by role, withholding keeps answers off the learner's
screen rather than out of a determined reader's reach.

Degradation is per block. An unknown type renders as a labelled code block —
the same thing an unrecognised fence has always rendered as — and a component
with a bad body renders its own source next to a panel naming the fields. A
lesson that shows eleven widgets and one error panel is worth far more than a
stack trace, so nothing in the parse path raises.

**How the agent knows to use them.** Not from a general instruction — from its
own stage. A stage's guidance is derived from the artifact types it declares,
so `addie.d2.assessment_design`, which writes an `EvidenceSpec (assessment_item)`,
is told an assessment item is made of `mcq` and `cloze`, and shown the syntax
for those two only; `addie.v1.build` gets the whole registry, because ADDIE's
Development phase is where components are authored. Ten of the hybrid preset's
fifteen stages are told nothing at all, which is the point: an intake stage
writing source claims has no use for widget syntax, and a prompt that carries
it anyway teaches the model that most of its instructions do not apply to it.
The mapping is `COMPONENTS_FOR`, from the design's §3.8 table.

Two consequences worth knowing. A session driving no preset gets no component
guidance — components are how a *course artifact* becomes something a learner
can do, and a session with no workflow is not writing one. And subagents get
their own scoped prompt, which never carries this guidance, so a stage that
authors components is told to restate the requirement **in the task it writes**.
Deriving it into the delegation prompt instead would make that prompt stop being
static and charge every delegation for guidance most have no use for; telling
the caller is also what `delegation.py` already asks for in its own words —
"give it everything it needs; it cannot see this conversation".

**What a learner does is kept.** An attempt used to be graded and forgotten.
`LearnerProgress` (`domain/learner.py`) is the record: one stream per session,
keyed `(path, component_id)`, with the xAPI verbs `answered` and `completed` as
its event names so an LRS bridge is a projection rather than a redesign.
`GET /api/sessions/{id}/progress?path=` is what the browser reads on opening a
document, and `persist: true` on a checklist now means what it says —
`POST .../progress/checklist` records the ticks, and the UI says "saved as you
go" instead of apologising.

Two decisions inside it. Answering an item three times is *three attempts*, not
one item in a final state: the count is the pedagogically interesting part, and
`correct` is sticky so revisiting a completed question to check something cannot
lose the completion. And every attempt stores the digest of the body it was
answered against, because `(path, component_id)` survives an edit that keeps the
id but nothing survives an author rewriting the item — so a rewrite under a
learner is *recorded* rather than silently resolved. Whether a reworded
distractor invalidates an earlier attempt is a pedagogical call, not a domain
rule, and the log is what that call would need.

Design notes are in `docs/research/course-design/markdown-components.md`;
