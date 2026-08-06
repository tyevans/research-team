# Markdown-Expressible Interactive Components

Research report for `research-team`. Covers (1) what the repo's file-rendering surface
is today, (2) prior art in markdown extension mechanisms and e-learning interchange
formats, and (3) a concrete proposed design: **a markdown component system where the
document *is* the component state**.

Anything I could not confirm from source or docs is marked **UNVERIFIED**.

---

## 1. What this repo does today

### 1.1 Files are events, and files are plain `{content: str}`

`research_team/infrastructure/agent/backend.py` subclasses deepagents'
`StateBackend` and overrides exactly two seams — `_read_files()` and
`_send_files_update()`. Every write/edit/delete becomes a domain command
(`WriteFile`, `EditFile`, `DeleteFile`) executed against the `CodingSession`
aggregate. `edit()` is additionally wrapped to capture *edit intent*
(`old_string`, `new_string`, `replace_all`) so `FileEdited` carries the reason
alongside the resulting content.

State shape (`research_team/domain/session.py:70`):

```python
files: dict[str, dict[str, Any]]     # path -> file_data, where file_data["content"] is the text
```

The reducer replaces whole entries (`session.py:305`) — there is no per-file
metadata slot today beyond whatever `file_data` happens to carry. That matters:
a component system that wants derived/parsed data has a natural home here, but
adding one is a domain change, not a UI change.

### 1.2 The HTTP surface

`research_team/interfaces/web/app.py`:

- `GET /api/sessions/{id}/files?path=&at=` → `{"path", "content", "at"}` — raw text.
  Reads at HEAD or at a historical event index (time travel is a first-class
  requirement: it must be able to serve a file that no longer exists at HEAD).
- `GET /api/sessions/{id}/files/history?path=` → per-event rows including
  `content` and the edit intent (`presenters.py:160`).
- `session_view` (`presenters.py:150`) lists files as `{path, size, revisions}` —
  size is `len(content)`, revisions is a count of touching events.
- `GET /api/stream` is an SSE multiplexer (events, approvals, turn activity).

**There is no server-side markdown processing anywhere.** The server ships text.

### 1.3 The client renderer

`research_team/interfaces/web/static/app.js:273-430` contains a hand-written
markdown renderer. Its own comment states the design constraint precisely:

> "It builds DOM nodes directly rather than assembling HTML, so file contents —
> which are written by tools and models, not by us — can never become markup.
> ... anything it does not recognise falls through as literal text, which is the
> safe failure for a *viewer*."

Concretely:

- `isMarkdownPath()` (`app.js:280`) gates on `.md|.markdown|.mdown|.mkd`.
- Supported blocks: fenced code (``` and `~~~`, with `pre.dataset.lang` captured
  from the info string — **the hook a component system needs already exists**),
  ATX headings, `hr`, blockquote, pipe tables, nested lists, paragraphs, plus an
  inline pass (`mdInline`).
- The file viewer offers a `rendered | source` toggle for markdown files
  (`state.fileRender`, `app.js:522`, `app.js:1829-1866`).
- Assistant chat turns are rendered through the same `renderMarkdown`
  (`app.js:2072-2079`).
- No `innerHTML`, no `marked`, no DOMPurify, no third-party JS at all. `h()`
  (`app.js:24`) sets `textContent`, never HTML.

**Assessment.** The surface is unusually well-positioned for this project. The
renderer is ours, it is a builder (not a string concatenator), fenced-block info
strings are already parsed and preserved, and there is already a rendered/source
toggle — which is exactly the affordance a "reveal the answers" debate needs to
reckon with. The two real gaps: (a) nothing parses frontmatter, (b) nothing
persists learner interaction, because files are the only writable state and they
are written by the agent, not the learner.

---

## 2. Prior art

### 2.1 MDX — powerful, wrong fit here

MDX lets markdown embed JSX and arbitrary JS expressions. For an LLM-authored,
non-JS-executing viewer it fails on three counts:

1. **It is code execution.** MDX expressions can embed arbitrary JavaScript, and
   LLM-generated MDX is a documented prompt-injection/exfiltration vector; the
   recommended mitigation is to strip all expressions, imports, and exports
   outright ([mdx2md llm-sanitization
   notes](https://github.com/icyJoseph/mdx2md/blob/main/docs/llm-sanitization.md)).
   Sandboxing JS is not a solved problem — `vm2` alone has a long history of
   escape CVEs ([Endor Labs on
   CVE-2026-22709](https://www.endorlabs.com/learn/cve-2026-22709-critical-sandbox-escape-in-vm2-enables-arbitrary-code-execution)).
   Our current renderer's whole security posture is "never produce markup from
   model output." MDX inverts that.
2. **It needs a build step.** MDX compiles to a component tree; you cannot render
   an arbitrary MDX file the way you render a `.md` file the agent just wrote,
   mid-session, in the browser.
3. **It degrades badly.** An MDX file in a dumb renderer (git diff, `cat`, PDF
   export, another agent reading it) shows JSX noise.

**Verdict: reject.** Borrow only the *idea* of a named component with typed props.

### 2.2 Generic directives (`:::name{attrs}`)

The CommonMark "generic directives/plugins syntax" proposal
([talk.commonmark.org thread
#444](https://talk.commonmark.org/t/generic-directives-plugins-syntax/444)) defines
three levels — inline (`:name[content]{attrs}`), leaf (`::name`), and container
(`:::name`). It is implemented by
[`remark-directive`](https://github.com/remarkjs/remark-directive), and is
closely related to Pandoc's **fenced divs** (`::: {.class key=val}` … `:::`) and
bracketed spans ([Pandoc 8.18 Divs and
Spans](https://pandoc.org/demo/example33/8.18-divs-and-spans.html)); Pandoc has an
open issue about converging the two syntaxes
([jgm/pandoc#7480](https://github.com/jgm/pandoc/issues/7480)).

Strengths: composable (a directive body is markdown, so a component can contain
other components), spec'd, three levels of granularity. Weaknesses for us:
nesting requires *increasing colon counts* (`::::` around `:::`), which is
precisely the kind of counting an LLM gets wrong; and attribute syntax
(`{#id .class key="v"}`) is a second mini-language with its own quoting rules.

### 2.3 The "mermaid pattern": fenced code with a language tag

GitHub renders fenced blocks tagged `mermaid`, `geojson`, `topojson`, and `stl`
as interactive diagrams/maps/3D models, in Markdown files, issues, PRs, wikis and
discussions ([GitHub docs: Creating
diagrams](https://docs.github.com/en/get-started/writing-on-github/working-with-advanced-formatting/creating-diagrams);
[changelog,
2022-03-17](https://github.blog/changelog/2022-03-17-mermaid-topojson-geojson-and-ascii-stl-diagrams-are-now-supported-in-markdown-and-as-files/)).

This is the single most important precedent, because it demonstrates the whole
thesis: **a fenced block's info string is a component name, its body is the
component's serialized state, and an unaware renderer shows the body as a code
block instead of breaking.** The same pattern appears across the ecosystem:

- **MyST / Jupyter Book** — ```` ```{directive} ```` with a YAML-ish `:option:`
  block, and `:::{directive}` as the colon-fence equivalent
  ([MyST roles and
  directives](https://myst-parser.readthedocs.io/en/latest/syntax/roles-and-directives.html)).
- **Quarto** — callouts as fenced divs `::: {.callout-note}`. **UNVERIFIED** in
  detail; not fetched.
- **Obsidian** — fenced `dataview`, `mermaid`, plus `> [!note]` callouts.
- **Docusaurus** — admonitions via `:::note` … `:::`.
- **Notion / Slack** — closed formats; not markdown component systems, only
  markdown-*flavored* input. Not useful precedent.

### 2.4 MyST — the most mature spec'd extension mechanism

MyST is a CommonMark superset with **directives** (block extension points) and
**roles** (inline extension points), formally spec'd via
[`myst-spec`](https://github.com/executablebooks/myst-spec) and documented at
[mystmd.org/spec](https://mystmd.org/spec). Directly relevant: MyST ships
**exercise / solution directives**, where a solution is a separate labeled
directive that can be referenced (`{ref}`) and can be collapsed with
`:class: dropdown` ([MyST: Exercises and
Solutions](https://mystmd.org/guide/exercises)).

Two lessons worth stealing verbatim:

1. **Directive + option-block + body** is a shape LLMs already emit well, because
   it is heavily represented in training data (Sphinx/RST, MyST, Jupyter Book).
2. **MyST's answer-hiding is a UI affordance (`dropdown`), not a security
   boundary.** They do not pretend otherwise. Neither should we.

### 2.5 Existing quiz / flashcard markdown formats

- **Obsidian Spaced Repetition** — flashcards written inline in notes:
  `Question::Answer` (one-line), `Question:::Answer` (reversed), multi-line with
  `?` / `??` separators, and clozes as `==highlight==`, `**bold**`, or
  Anki-style `{{c1::text::hint}}`
  ([docs](https://stephenmwangi.com/obsidian-spaced-repetition/flashcards/cloze-cards/);
  [repo](https://github.com/st3v3nmw/obsidian-spaced-repetition)). Lesson: the
  *terse* inline forms are ambiguity-prone (the plugin has open bugs about blank
  lines changing card boundaries —
  [#450](https://github.com/st3v3nmw/obsidian-spaced-repetition/issues/450)).
  Terse sigil syntax is bad for an LLM author.
- **Anki markdown pipelines** (e.g. `mdanki`) — markdown → `.apkg`. **UNVERIFIED**
  in detail. Relevant mainly as an *export* target.
- **GIFT** (Moodle) — plain-text question format: `Question {=correct ~wrong
  ~wrong#feedback}`, delimited by blank lines, covering MC, T/F, short answer,
  matching, missing word, numeric ([MoodleDocs: GIFT
  format](https://docs.moodle.org/502/en/GIFT_format)). Compact, sigil-dense,
  *not* nestable, and unreadable in a plain renderer. Good export target, bad
  authoring format for us.
- **Moodle XML / QTI** — verbose XML interchange. See §2.6.
- **H5P** — the richest *catalog* of interactive learning content types:
  Interactive Video, Branching Scenario, Drag and Drop, Drag the Words, Dialog
  Cards, Flashcards, Image Hotspots, Timeline, Memory Game, Image Sequencing,
  Mark the Words, Fill in the Blanks, Question Set, Summary, Dictation, Essay,
  Accordion, Column, Documentation Tool ([H5P content
  types](https://h5p.org/content-types-and-applications); [Branching
  Scenario](https://h5p.org/branching-scenario)). H5P's *packaging* (a JS bundle
  per content type) is the opposite of what we want, but its *taxonomy* is the
  best available checklist for a component catalog.
- **markdown-it plugins / `markdown-it-container`** — the generic mechanism most
  JS markdown stacks use for `:::` blocks. **UNVERIFIED** in detail.

### 2.6 Standards worth borrowing from — plainly

| Standard | What it is | Verdict for us |
|---|---|---|
| **QTI 3.0** (1EdTech) | Data model for items/tests/results; UML model with XML binding; native Portable Custom Interactions; explicit interaction taxonomy ([overview](https://www.imsglobal.org/spec/qti/v3p0/oview)) | **Borrow vocabulary, don't implement.** Steal `choiceInteraction`, `orderInteraction`, `associateInteraction`, `textEntryInteraction`, `matchInteraction`, `hottext` as our component-type names, and steal the item/section/test nesting. Implementing the XML binding is overkill until someone actually needs LMS import — then write an *exporter*. |
| **xAPI** | Actor-verb-object statements POSTed to an LRS over HTTP | **Align now, cheaply.** Our learner-interaction events are already actor-verb-object shaped. Naming domain events after xAPI verbs (`attempted`, `answered`, `completed`, `passed`, `failed`) costs nothing and buys a future LRS bridge. |
| **cmi5** | An xAPI profile that re-adds SCORM's launch/completion/pass-fail semantics; the recommended default for new content in 2026 ([comparison](https://xapi.com/cmi5/comparison-of-scorm-xapi-and-cmi5/); [iCAN](https://icantech.ai/insights/xapi-vs-scorm-vs-cmi5-learning-standards-comparison)) | **The right export target** if/when courses need to land in an LMS. Not a v1 concern. |
| **SCORM 1.2 / 2004** | JS API against an LMS window; legacy | **Overkill / legacy.** Only if a customer's LMS demands it. |
| **LTI** | Tool launch + grade passback between platform and tool | **Not now.** Relevant only if the renderer becomes a hosted tool an LMS launches. |
| **Open Badges** | Verifiable credential assertions | **Out of scope.** |
| **Common Cartridge** | Course packaging (content + QTI + links) | **Out of scope**, but note that a CC export is "QTI export + a manifest", so a QTI exporter is the load-bearing piece. |

**Short version:** borrow QTI's *nouns*, xAPI's *verbs*, ignore the rest until
there is a named LMS to integrate with.

### 2.7 Answer-hiding: the honest analysis

Three mechanisms, in increasing strength and cost:

1. **Client-side withholding** — ship the full markdown, hide answers in the DOM.
   **Trivially defeatable**: the file is served verbatim at
   `/api/sessions/{id}/files?path=`, the source toggle in our own UI
   (`state.fileRender === 'source'`) reveals it, and view-source/devtools reveal
   it. This is what MyST's `:class: dropdown` does, and MyST is honest that it is
   a presentation affordance.
2. **Server-side stripping** — parse on the server, serve a *learner projection*
   with `answer`/`rationale` fields removed, and grade via a POST that never
   returns the key until the attempt is closed. This is a real boundary, and it
   is the only one worth building if grades matter.
3. **Cryptographic commitment** — publish `H(answer || salt)` so the client can
   verify a submitted answer offline without learning the answer. Works for exact
   match, defeats nothing against a brute-forceable answer space (4 MCQ options =
   4 hashes to try). **Useless for MCQ**, mildly useful for free text, and mostly
   a distraction.

**Recommendation:** build (1) for v1 and *say so in the UI* — this is
self-study/authoring, the learner and the author are frequently the same person,
and the artifact is meant to be readable as a document. Design the parse so that
(2) is a projection-level change (one function that drops fields) rather than a
rewrite. Never claim (1) is security.

---

## 3. A Markdown Component System for `research-team`

### 3.1 Design constraints, ranked

1. **An LLM must author it correctly on the first try.** This outranks
   expressiveness, terseness, and elegance.
2. **It must degrade to something a human can read** in `cat`, in a git diff, in
   GitHub, and in our own source view.
3. **It must not require executing model-authored code.** Preserve the current
   "model output never becomes markup" invariant.
4. **It must be losslessly round-trippable** — the file is the source of truth;
   the aggregate already treats it that way.
5. **Unknown component types must not break the document.**

### 3.2 Syntax choice: fenced code block, name in the info string, YAML body

**Recommendation:**

````markdown
```component:mcq
id: risk-matrix-1
prompt: ...
```
````

Or, equivalently and preferred for brevity, a bare type name in a registered set:

````markdown
```mcq
id: risk-matrix-1
...
```
````

Use the `component:` prefix. It costs nine characters and buys an unambiguous
namespace: an info string of `mcq` could plausibly be a language tag someone
adds later, `component:mcq` cannot. The current renderer already stores the info
string in `pre.dataset.lang` (`app.js:306`), so the dispatch hook exists.

**Body is YAML.** Not TOML, not JSON, not a bespoke sigil language.

Why this wins:

| Property | Fenced + YAML | `:::directive{attrs}` | MyST `{dir}` + `:opt:` | MDX | GIFT-style sigils |
|---|---|---|---|---|---|
| LLM authors it reliably | **Yes** — models emit fenced YAML constantly | Medium — attribute quoting, colon-count nesting | Medium-high | Low (JSX) | Low (sigil soup) |
| Degrades readably | **Yes** — shows as a labeled code block | Shows stray `:::` lines | Shows stray fences | Shows JSX | Shows garbage |
| No markup from model output | **Yes** | Yes | Yes | **No** | Yes |
| Nesting components | **No** (deliberate) | Yes (colon counting) | Yes | Yes | No |
| Existing renderer hook | **Already there** | New block parser | New block parser | N/A | N/A |
| Machine-validatable | **Yes** — one schema per type | Ad hoc | Ad hoc | No | Regex |

**Rejected alternatives and why:**

- **Generic directives (`:::mcq{...}`)** — the strongest runner-up, and the right
  choice if arbitrary *markdown-inside-component* nesting were a hard
  requirement. It is not: every component in §3.4 has a fixed field structure,
  and YAML block scalars (`|`) carry multi-paragraph markdown fine. The
  colon-count nesting rule is a real reliability tax on LLM authoring, and
  directive attribute syntax is a second grammar to validate.
- **MyST directives** — same shape as fenced-YAML but with `:key: value` option
  lines that don't nest, forcing lists into the body. YAML strictly dominates
  for our field shapes. We should still borrow MyST's *naming* where it overlaps
  (`exercise`, `solution`).
- **MDX** — see §2.1.
- **HTML/custom elements (`<mcq-item>`)** — breaks constraint 3 outright, and is
  unreadable in a plain renderer.
- **Frontmatter-only (whole file is one component)** — too coarse; a lesson
  document needs prose interleaved with a dozen widgets.
- **A sidecar JSON file per component** — breaks constraint 2 and 4; two files
  to keep in sync is exactly the failure mode LLM authoring produces most.

**Frontmatter's role.** YAML frontmatter at the top of the file carries
*document-level* metadata, not component data:

```markdown
---
type: lesson
course: incident-response-fundamentals
module: 3
objectives:
  - Classify an incident by severity using the org's matrix
  - Draft a stakeholder comms update within 15 minutes of declaration
framework: ubd            # ubd | addie | tyler
stage: 3                  # UbD Stage 3 — Learning Plan
---
```

### 3.3 Component schema, registry, and graceful degradation

**Registry.** A component type is declared server-side as a
name + version + JSON Schema + a learner-projection rule:

```python
# ILLUSTRATIVE ONLY -- not production code
ComponentType(
    name="mcq",
    version=1,
    schema={...},                       # JSON Schema, draft 2020-12
    secret_fields=["options[].correct", "options[].feedback", "rationale"],
    renderer="mcq",                     # client-side renderer key
)
```

**Every component carries three universal fields:**

- `id` — stable within the document; the key for learner state. If omitted,
  derive a deterministic id from `sha256(path + component_index)` so state does
  not detach on a re-render, but *warn*: a content edit above will not move it,
  an insert will. Requiring explicit `id` is better and LLMs comply readily.
- `type` — implied by the info string; may be restated in the body for
  robustness.
- `v` — schema version, defaulting to 1.

**Validation** happens at parse time (server, §3.5) and produces one of three
outcomes:

1. **Valid** — component node in the JSON handoff.
2. **Known type, invalid body** — component node with `errors: [...]`; renderer
   shows the raw block plus an inline error panel. **The document still renders.**
3. **Unknown type** — no error. Emit a plain `code` node with `lang` preserved.
   The learner sees a labeled code block; the author sees exactly what they
   wrote. This is the mermaid pattern's degradation contract and it must be
   preserved literally.

Never fail a whole document because one widget is malformed. The agent is going
to get things wrong, and a lesson that renders 11 of 12 components plus one
error box is enormously more useful than a stack trace.

### 3.4 Component catalog

Worked examples below are drawn from a plausible course, **"Incident Response
Fundamentals"** — an internal engineering course. All examples are complete and
copy-pasteable into a spec.

#### 3.4.1 `flashcards` — flashcard deck

````markdown
```component:flashcards
id: sev-vocabulary
title: Severity Vocabulary
shuffle: true
cards:
  - front: "SEV-1"
    back: "Complete loss of a customer-facing service, or confirmed data loss. Pages the on-call director. 15-minute comms cadence."
  - front: "SEV-2"
    back: "Major degradation with a workaround, or a single-tenant outage. Pages the on-call engineer. 30-minute comms cadence."
  - front: "SEV-3"
    back: "Minor degradation, no customer impact reported. Handled in business hours. No comms cadence."
  - front: "Incident Commander (IC)"
    back: "The single decision-maker for the incident. Owns severity, owns the call to page, owns the declaration that the incident is over. Does not debug."
  - front: "Comms Lead"
    back: "Owns all outbound updates -- status page, customer email, internal channel. Reports to the IC, never sets severity."
```
````

#### 3.4.2 `mcq` — multiple choice

````markdown
```component:mcq
id: sev-classification-1
prompt: |
  At 02:14 the checkout API begins returning 500s for approximately 4% of
  requests. A retry succeeds for most users. No data has been lost. The
  on-call engineer has a rollback ready but has not executed it.

  What severity should the Incident Commander declare?
multiple: false
shuffle: true
options:
  - text: "SEV-1"
    correct: false
    feedback: "No complete loss of service and no data loss. Over-declaring burns the org's alerting credibility -- the escalation cost is real."
  - text: "SEV-2"
    correct: true
    feedback: "Major degradation with a working workaround (retries succeed) is the textbook SEV-2. Rollback readiness does not lower the severity; it shortens the incident."
  - text: "SEV-3"
    correct: false
    feedback: "Customer-facing 500s are customer impact by definition. SEV-3 requires no reported customer impact."
  - text: "Wait for more data before declaring"
    correct: false
    feedback: "Declaring is reversible and cheap; waiting is not. The IC downgrades later if the picture improves."
rationale: |
  Severity is a *communication* decision, not a *technical* one. It answers
  "who needs to wake up and how often do they hear from us," which is why the
  presence of a fix in hand does not change it.
objective: "Classify an incident by severity using the org's matrix"
```
````

#### 3.4.3 `cloze` — cloze deletion

````markdown
```component:cloze
id: comms-cadence-cloze
text: |
  A {{SEV-1}} incident requires a stakeholder update every {{15 minutes::how often?}},
  issued by the {{Comms Lead}}, who takes direction from the {{Incident Commander}}.
  The incident is not over until the {{IC::who declares it?}} says so in the
  incident channel.
mode: one-at-a-time     # one-at-a-time | all-at-once
```
````

Syntax note: `{{answer}}` or `{{answer::hint}}` — borrowed from Anki/Obsidian
because it is the most widely represented cloze syntax in training data. Do
**not** support `==highlight==` clozes; overloading a formatting mark with
semantics is exactly the ambiguity that has cost the Obsidian plugin bug reports.

#### 3.4.4 `matching` — match pairs

````markdown
```component:matching
id: role-responsibility-match
prompt: "Match each incident role to the decision it owns."
shuffle_right: true
pairs:
  - left: "Incident Commander"
    right: "Whether to declare, and at what severity"
  - left: "Comms Lead"
    right: "What the status page says and when"
  - left: "Ops Lead"
    right: "Which mitigation to attempt first"
  - left: "Scribe"
    right: "What the timeline records as having happened"
distractors_right:
  - "Which engineer is assigned to the postmortem"
rationale: "Every role owns exactly one decision. Overlap is what produces two people rolling back at once."
```
````

#### 3.4.5 `ordering` — sequencing

````markdown
```component:ordering
id: declaration-sequence
prompt: "Put the first five minutes of a SEV-2 declaration in order."
items:
  - "Page the on-call engineer via the alerting tool"
  - "Open the incident channel and pin the incident doc"
  - "Assume or assign the Incident Commander role"
  - "Post the initial severity and a one-line impact statement"
  - "Assign Comms Lead and Scribe"
strict: true
rationale: |
  The IC exists before anything else, because every later step needs an owner.
  The most common real-world failure is step 4 happening before step 3, which
  produces a channel full of updates nobody is accountable for.
```
````

#### 3.4.6 `jeopardy` — game board

````markdown
```component:jeopardy
id: ir-review-board
title: "Incident Response Review"
categories:
  - name: "Severity"
    clues:
      - value: 100
        clue: "The severity that pages the on-call director."
        answer: "What is SEV-1?"
      - value: 200
        clue: "The comms cadence for a SEV-2."
        answer: "What is every 30 minutes?"
      - value: 300
        clue: "The one thing that automatically makes any incident a SEV-1 regardless of user impact."
        answer: "What is confirmed data loss?"
  - name: "Roles"
    clues:
      - value: 100
        clue: "The only role permitted to change severity."
        answer: "What is the Incident Commander?"
      - value: 200
        clue: "The role that must never also be debugging."
        answer: "What is the Incident Commander?"
      - value: 300
        clue: "The role whose artifact the postmortem is written from."
        answer: "What is the Scribe?"
  - name: "Postmortem"
    clues:
      - value: 100
        clue: "The number of business days within which a SEV-1 postmortem is due."
        answer: "What is five?"
      - value: 200
        clue: "The section a blameless postmortem must never contain."
        answer: "What is an assignment of individual fault?"
      - value: 300
        clue: "The two questions every action item must answer."
        answer: "What are 'who owns it' and 'by when'?"
```
````

#### 3.4.7 `scenario` — branching scenario

````markdown
```component:scenario
id: checkout-degradation-drill
title: "Drill: 02:14 Checkout Degradation"
start: alert
nodes:
  - id: alert
    text: |
      You are on call. Your phone goes off at 02:14: checkout API error rate
      4%, sustained for six minutes. You have not opened a laptop yet.
    choices:
      - text: "Open the incident channel and declare SEV-2 before investigating"
        goto: declared
      - text: "Investigate for ten minutes first, then decide"
        goto: delayed
      - text: "Roll back the most recent deploy immediately"
        goto: blind-rollback
  - id: declared
    text: |
      You declare at 02:17. Two engineers join within four minutes. One
      identifies a bad config push; the other prepares the rollback. The
      Comms Lead posts a status page update at 02:24.
    outcome: good
    feedback: "Declaring first is almost always right. Declaration is reversible; a silent 40-minute outage is not."
    choices:
      - text: "Continue"
        goto: resolved
  - id: delayed
    text: |
      At 02:27 you understand the cause -- but error rate has climbed to 11%
      and support has three tickets. You now declare, and spend the first
      five minutes of the incident explaining what happened in the last ten.
    outcome: mixed
    feedback: "You lost 13 minutes of parallel work. The investigation was not wasted; keeping it private was."
    choices:
      - text: "Continue"
        goto: resolved
  - id: blind-rollback
    text: |
      The rollback completes at 02:22. Error rate is unchanged -- the cause
      was a downstream dependency, not your deploy. You have now introduced a
      second variable and still have no incident channel.
    outcome: bad
    feedback: "Mitigation without declaration means nobody can see what you changed. When it doesn't work, the next responder inherits an unknown state."
    choices:
      - text: "Declare now"
        goto: declared
  - id: resolved
    text: "Error rate returns to baseline at 02:41. The IC declares the incident over at 02:55 after a 15-minute soak."
    outcome: end
```
````

#### 3.4.8 `rubric` — assessment rubric

````markdown
```component:rubric
id: postmortem-rubric
title: "Postmortem Quality Rubric"
task: "Write a blameless postmortem for an incident you participated in."
scale: [Beginning, Developing, Proficient, Exemplary]
criteria:
  - name: "Timeline accuracy"
    weight: 25
    levels:
      Beginning: "Timeline is a narrative with no timestamps."
      Developing: "Timestamps present but reconstructed from memory; gaps unmarked."
      Proficient: "Timestamps sourced from logs and the incident channel; gaps explicitly marked as unknown."
      Exemplary: "As Proficient, plus each entry cites its source, and disagreements between sources are called out."
  - name: "Blamelessness"
    weight: 25
    levels:
      Beginning: "Names an individual as the cause."
      Developing: "Avoids names but describes 'human error' as a root cause."
      Proficient: "Describes what the system made easy to do wrong."
      Exemplary: "Identifies the specific affordance that produced the action, and proposes a change to it."
  - name: "Contributing factors"
    weight: 25
    levels:
      Beginning: "Single root cause asserted."
      Developing: "Multiple factors listed without relationships."
      Proficient: "Factors identified with how they combined."
      Exemplary: "Counterfactual analysis: which factors, if absent, would have prevented or shortened the incident."
  - name: "Action items"
    weight: 25
    levels:
      Beginning: "No action items, or aspirational statements."
      Developing: "Action items without owners or dates."
      Proficient: "Every item has an owner and a due date."
      Exemplary: "Every item has an owner, a date, and a stated way to tell whether it worked."
self_assess: true
```
````

#### 3.4.9 `code_exercise` — code exercise

````markdown
```component:code_exercise
id: severity-classifier
language: python
prompt: |
  Implement `classify(error_rate, data_loss, workaround_exists)` returning
  the severity string. Encode the matrix from the lesson, not your intuition.
starter: |
  def classify(error_rate: float, data_loss: bool, workaround_exists: bool) -> str:
      ...
solution: |
  def classify(error_rate: float, data_loss: bool, workaround_exists: bool) -> str:
      if data_loss or error_rate >= 0.5:
          return "SEV-1"
      if error_rate > 0.0:
          return "SEV-2" if workaround_exists else "SEV-1"
      return "SEV-3"
tests:
  - call: "classify(0.04, False, True)"
    expect: "SEV-2"
  - call: "classify(0.0, True, True)"
    expect: "SEV-1"
  - call: "classify(0.0, False, True)"
    expect: "SEV-3"
  - call: "classify(0.04, False, False)"
    expect: "SEV-1"
execute: false
hints:
  - "Data loss short-circuits everything else."
  - "The absence of a workaround escalates, it never de-escalates."
```
````

`execute: false` is the default and should stay the default. Running
learner-authored code is a sandbox problem, not a rendering problem — see §3.9.

#### 3.4.10 `diagram` — interactive/annotated diagram

````markdown
```component:diagram
id: escalation-path
title: "Escalation Path"
format: mermaid
source: |
  flowchart TD
    A[Alert fires] --> B{Customer impact?}
    B -- No --> C[SEV-3: business hours]
    B -- Yes --> D{Workaround exists?}
    D -- Yes --> E[SEV-2: page on-call engineer]
    D -- No --> F[SEV-1: page on-call director]
    E --> G[30-min comms cadence]
    F --> H[15-min comms cadence]
hotspots:
  - target: B
    note: "This is the only question that distinguishes an incident from a bug. Answer it from customer reports, not from dashboards."
  - target: D
    note: "'Workaround' means something the customer can do, not something you can do. A retry that succeeds counts; an internal failover does not."
```
````

#### 3.4.11 `timeline` — annotated timeline

````markdown
```component:timeline
id: checkout-incident-timeline
title: "SEV-2 2026-03-11: Checkout Degradation"
reveal: sequential          # all | sequential
events:
  - at: "02:14"
    label: "Alert fires"
    detail: "Error-rate SLO burn alert, checkout API."
  - at: "02:17"
    label: "Declared SEV-2"
    detail: "On-call engineer assumes IC. Channel opened."
    annotation: "Three minutes from page to declaration is the target. Measure this."
  - at: "02:24"
    label: "First status page update"
    detail: "Comms Lead posts 'investigating'."
  - at: "02:31"
    label: "Cause identified"
    detail: "Downstream payment provider timeout increase."
    annotation: "Note that this is 14 minutes *after* declaration -- the parallel work only exists because the channel did."
  - at: "02:41"
    label: "Error rate at baseline"
    detail: "Timeout raised on our side; retries absorbing the rest."
  - at: "02:55"
    label: "Incident closed"
    detail: "IC declares over after 15-minute soak."
```
````

#### 3.4.12 `srs_deck` — spaced-repetition deck

````markdown
```component:srs_deck
id: ir-core-deck
title: "Incident Response Core"
algorithm: sm2
new_per_day: 10
cards:
  - id: sev1-def
    front: "What makes an incident SEV-1?"
    back: "Complete loss of a customer-facing service, OR confirmed data loss, OR customer impact with no workaround."
    tags: [severity]
  - id: ic-single
    front: "How many people can change the severity of an incident?"
    back: "Exactly one: the Incident Commander."
    tags: [roles]
  - id: declare-first
    front: "Declare first or investigate first, and why?"
    back: "Declare first. Declaration is cheap and reversible; it buys parallel responders. Investigation is not lost by declaring."
    tags: [process, judgment]
```
````

Scheduling state is *learner state*, not document state — see §3.6. The document
declares the deck; it does not carry anyone's review intervals.

#### 3.4.13 `poll` — ungraded poll

````markdown
```component:poll
id: confidence-check-m3
prompt: "Before this module: how confident are you that you could act as IC tonight?"
options:
  - "Not at all -- I'd escalate immediately"
  - "I could run it with someone shadowing"
  - "I could run it alone for a SEV-2"
  - "I could run it alone for a SEV-1"
anonymous: true
show_results: after_response
```
````

#### 3.4.14 `reflection` — reflection prompt

````markdown
```component:reflection
id: near-miss-reflection
prompt: |
  Describe an incident or near-miss you were part of where the severity was
  wrong at the start. What information would have changed the call, and who
  had it?
min_words: 120
private: true
scaffold:
  - "What was declared, and what should it have been?"
  - "Who first knew the thing that would have changed the call?"
  - "What stopped that information from reaching the IC?"
```
````

#### 3.4.15 `checklist` — procedural checklist

````markdown
```component:checklist
id: ic-first-five
title: "IC: First Five Minutes"
persist: true
items:
  - text: "Assume the IC role out loud in the channel"
    required: true
  - text: "State severity and a one-line impact statement"
    required: true
  - text: "Assign a Comms Lead"
    required: true
  - text: "Assign a Scribe"
    required: false
    note: "Optional for SEV-3; mandatory for SEV-1 and SEV-2."
  - text: "Set a timer for the next comms update"
    required: true
  - text: "Confirm nobody is making changes outside the channel"
    required: true
```
````

Two more worth registering but not worth full examples here: `exercise` /
`solution` (a MyST-compatible pair, useful for prose-heavy practice items) and
`objectives` (a structured restatement of the frontmatter objectives that can be
cross-referenced by `objective:` fields on assessment components — this is what
makes UbD alignment checkable).

### 3.5 Render pipeline

**Parse on the server.** Reasons, in order:

1. Validation must produce *authoring feedback for the agent*, and the agent runs
   server-side. A browser-only parser cannot tell the model it wrote bad YAML.
2. Answer-withholding as a real boundary (§2.7 option 2) requires a server-side
   projection. Parsing in the browser forecloses that permanently.
3. YAML parsing in the browser means shipping a YAML library; the current client
   has zero third-party JS and that is a property worth keeping.
4. Server-side parse results can be cached against the event index — files are
   immutable per event, so `(session_id, path, at)` is a perfect cache key.

**Pipeline:**

```
FileWritten event
  -> content (str)
  -> block scanner: split into markdown segments and component blocks
       (reuses the same fence rules the client already implements)
  -> per block: yaml.safe_load  -> schema validate -> normalize
  -> DocumentAST { blocks: [...] }
  -> projection: author view (everything) | learner view (secrets stripped)
  -> JSON over HTTP
```

**New endpoint**, leaving the existing raw-text route untouched:

```
GET /api/sessions/{id}/files/parsed?path=&at=&view=author|learner
```

**Handoff shape:**

```json
{
  "path": "modules/03-severity.md",
  "at": 412,
  "frontmatter": {"type": "lesson", "framework": "ubd", "stage": 3},
  "blocks": [
    {"kind": "markdown", "text": "## Declaring\n\n..."},
    {"kind": "component", "type": "mcq", "v": 1, "id": "sev-classification-1",
     "data": {"prompt": "...", "options": [{"text": "SEV-1"}, {"text": "SEV-2"}]},
     "withheld": ["options[].correct", "options[].feedback", "rationale"],
     "errors": []},
    {"kind": "component", "type": "widget-we-dont-know", "unknown": true,
     "raw": "...", "lang": "component:widget-we-dont-know"},
    {"kind": "component", "type": "mcq", "id": "bad-one",
     "errors": [{"path": "options", "message": "required field missing"}],
     "raw": "..."}
  ]
}
```

The client keeps its existing `renderMarkdown` for `kind: "markdown"` blocks and
gains a component dispatch table keyed on `type`. Unknown → render as a code
block with the info string as the label (exactly today's behavior). Errors →
render raw plus an error panel. **No `innerHTML` anywhere**; component renderers
build DOM the same way `h()` does today, and any markdown *inside* component
fields goes back through `renderMarkdown`.

**Grading.** For v1, client-side against the withheld-but-present key is
tempting; don't. If `view=learner` strips the key, the client cannot grade. So:

```
POST /api/sessions/{id}/files/{path}/components/{component_id}/attempt
     {"response": ...}
  -> {"correct": true, "feedback": "...", "rationale": "...", "attempts_remaining": 0}
```

The server holds the key, grades, and returns feedback *and only then* the
rationale. This is a genuine boundary and it is not much more work than the fake
one. **The honest caveat, which must be stated in the UI and the docs:** the raw
file is still fetchable at `/api/sessions/{id}/files?path=` by anyone with
session access, and the source toggle shows it. Until file reads are
permissioned by role (author vs learner), the withholding is a *ceremony*, not a
control. Say that plainly rather than implying a security property that isn't
there.

### 3.6 Learner state

**Learner state does not belong in the document.** The document is authored by
the agent and is the agent's artifact; interleaving Alice's review intervals into
it would make every learner interaction a `FileEdited` event and would make the
artifact un-shareable.

Model it as a **separate aggregate** in the same event-sourced style:

```
LearnerProgress(learner_id, session_id | project_id)
  events:
    ComponentAttempted(component_ref, response, at)
    ComponentAnswered(component_ref, response, correct, score, at)
    ComponentCompleted(component_ref, at)
    CardReviewed(component_ref, card_id, grade, next_due, at)
    ChecklistItemToggled(component_ref, item_index, checked, at)
    ReflectionSubmitted(component_ref, text, at)
```

where `component_ref = (session_id, path, component_id)`. Note the event names
are deliberately xAPI verbs (`attempted`, `answered`, `completed`) — that makes
an xAPI/LRS bridge a projection rather than a redesign (§2.6).

This fits the existing architecture cleanly: the repo already has a session
aggregate with an event log, `state_at(session_id, at)` time travel, and an SSE
feed. A second aggregate with the same machinery costs little and keeps the
learner's data out of the author's artifact. It also gives you the interesting
analytics for free — the *sequence* of attempts on one item is the pedagogically
interesting object, and an event log is the right shape for it.

**Component identity across edits** is the hard part. `component_id` is stable
only if the agent keeps it stable across rewrites. Mitigations: (a) the
`validate_component` tool warns when a rewrite drops an id that has attempts
against it; (b) `LearnerProgress` keys on `(path, component_id)` so a content
edit that preserves the id preserves the history; (c) accept that a
substantively rewritten item *should* orphan its history — that is arguably
correct, since the item is now a different item.

### 3.7 Authoring affordances for the agent

Three things, in priority order:

1. **A `validate_component` tool.** Signature: `validate_component(source: str)
   -> {valid, errors, normalized}`. The agent calls it before writing, or the
   system calls it after. This is clearly warranted — YAML is forgiving but not
   *that* forgiving (unquoted colons inside `prompt:` values will be the single
   most common failure, which is why every prose field in §3.4 uses a `|` block
   scalar; the prompt guidance must say so explicitly).
2. **Post-write validation feedback.** Cheaper and more reliable than trusting the
   agent to call a tool: hook the parse into the write path, and when a written
   `.md` contains an invalid component, return the validation errors as part of
   the write tool's result string. deepagents' file tools already return strings
   the model reads; appending `"warning: component 'sev-classification-1' —
   options: required field missing"` closes the loop with zero new tool
   surface. **Do this first.**
3. **A component reference in the system prompt**, generated from the registry —
   name, one-line purpose, and one minimal example each. Generated, not
   hand-written, so it cannot drift from the schemas.

A `preview_component` tool (render → describe) is **not** warranted for v1. The
agent cannot see the render, and a textual description of a rendered MCQ tells it
nothing the schema didn't. Revisit only if a vision-capable review loop exists.

**Prompt guidance that will actually matter**, empirically likely (**UNVERIFIED** —
worth measuring):

- Always use `|` block scalars for any field containing prose.
- Always supply an explicit `id`, kebab-case, unique in the document.
- Never nest a component inside another component's field.
- Prefer four options for MCQ, with *plausible* distractors, each with feedback
  that says why it is wrong rather than that it is wrong.
- Tag assessment components with `objective:` matching a frontmatter objective.

### 3.8 Fit with the instructional-design workflows

| Framework / stage | Naturally produces |
|---|---|
| **UbD Stage 1** (desired results) | frontmatter `objectives`, `objectives` component, `poll` (pre-assessment of prior knowledge) |
| **UbD Stage 2** (evidence) | `rubric` (the performance task's criteria), `scenario` (the authentic performance task itself), `mcq`/`cloze` as supplementary evidence, `reflection` (self-assessment) |
| **UbD Stage 3** (learning plan) | `flashcards`, `srs_deck`, `diagram`, `timeline`, `code_exercise`, `checklist`, `matching`, `ordering` |
| **ADDIE — Analysis** | `poll` (audience/needs data), `reflection` |
| **ADDIE — Design** | `objectives`, `rubric` (assessment blueprint before content) |
| **ADDIE — Development** | the whole catalog; this is where components get authored |
| **ADDIE — Implementation** | `checklist` (facilitator run-of-show), `jeopardy` (live session activity) |
| **ADDIE — Evaluation** | `poll`, `reflection`, and the `LearnerProgress` event log as Kirkpatrick L1/L2 data |
| **Tyler — Objectives** | frontmatter `objectives` |
| **Tyler — Selecting experiences** | `scenario`, `code_exercise`, `diagram` |
| **Tyler — Organizing experiences** | `timeline`, `ordering`, module-level `type: lesson` sequencing |
| **Tyler — Evaluation** | `mcq`, `cloze`, `matching`, `rubric` — the assessment components proper |

The `objective:` field on assessment components is the mechanism that makes any
of this checkable: an alignment report ("which objectives have no assessment
evidence?") is a trivial query over the parsed AST, and it is exactly the
critique a UbD or Tyler workflow wants to make of its own output. That single
field is probably the highest-leverage thing in this whole design.

### 3.9 Cross-cutting concerns

**Versioning & extensibility.** Every component carries `v` (default 1). The
registry keys on `(name, v)`. Adding an optional field is not a version bump;
removing/renaming/re-typing one is. A component whose `v` exceeds what the
renderer knows degrades to the unknown-type path (raw block) rather than
mis-rendering — fail visible, not wrong. New component types are registry
entries plus a client renderer; nothing else changes.

**Accessibility.** Non-negotiable, and cheap if done from the start:

- Every interactive component is keyboard-operable with no pointer. Ordering and
  matching need a keyboard path (arrow-key move, or a select-then-place model) —
  drag-and-drop must never be the *only* affordance. This is where naive
  implementations fail WCAG 2.1 SC 2.1.1 and it is the most likely thing to be
  skipped.
- Radio/checkbox semantics via real `input` elements for `mcq`/`poll`; native
  focus and native screen-reader announcement come free.
- Feedback and grading results announced via `aria-live="polite"`.
- `role="group"` + `aria-labelledby` on each component, so a screen reader user
  can tell where a widget starts and ends.
- Don't encode correctness in color alone (WCAG 1.4.1) — pair with text/icon.
- Reduced motion honored for card flips and reveals.
- `diagram` needs a text alternative; mermaid's SVG output is not adequately
  described on its own, so require an `alt:` field on `diagram` (add it to the
  schema as required — the §3.4.10 example above should carry one).

**Printability / export.** The parsed AST makes all of these mechanical
transforms rather than special cases:

- **Print / PDF** — render `view=author` with all answers inline in an answer-key
  section, or `view=learner` for a worksheet. Two CSS print stylesheets.
- **Anki** — `flashcards` and `srs_deck` → `.apkg` or a TSV import. Cloze maps
  directly since we already use `{{...}}` syntax.
- **QTI 3.0** — `mcq` → `choiceInteraction`, `ordering` → `orderInteraction`,
  `matching` → `matchInteraction` / `associateInteraction`, `cloze` →
  `textEntryInteraction`. This mapping is why §2.6 recommends borrowing QTI's
  nouns for component names: it makes the exporter nearly a rename.
- **cmi5/SCORM package** — a static bundle of the rendered HTML plus a manifest,
  with `LearnerProgress` events forwarded as xAPI statements. Real work, but
  well-defined, and only worth doing against a named LMS.

**Code execution.** `code_exercise.execute` should stay `false` until there is a
real sandbox story. deepagents ships sandbox integrations
([LangChain deepagents sandboxes](https://docs.langchain.com/oss/python/deepagents/sandboxes)),
which is the path if execution becomes a requirement — but note the threat model
changes completely: today's untrusted input is *agent-authored*, and execution
adds *learner-authored* input to the mix.

### 3.10 Trade-offs, and what to build first

**The three real trade-offs:**

1. **No component nesting.** Fenced blocks can't nest, so a `scenario` node can't
   contain an `mcq`. Mitigation: components reference each other by id
   (`goto: another-component-id` style) rather than containing each other. This
   is a genuine expressiveness loss versus `:::` directives, and it is the price
   of authoring reliability. I think it's the right trade; if nesting becomes
   load-bearing, the escape hatch is to allow `:::` containers *only* for a small
   fixed set of layout components, keeping leaf components fenced.
2. **Server-side parsing adds a round trip and a cache.** Worth it for the
   validation-feedback loop alone.
3. **Client-side answer hiding is not security.** Accepted knowingly for v1;
   §3.5 keeps the door open for the real boundary.

**v1 — the minimum that proves the thesis (build this):**

- Fenced `component:<type>` + YAML parsing, server-side, with a registry of
  **four** types: `flashcards`, `mcq`, `cloze`, `checklist`.
- Unknown-type and invalid-body degradation, both exercised by tests.
- `GET .../files/parsed` with `view=author|learner`.
- Client dispatch table; four renderers; keyboard-operable; `aria-live` feedback.
- Validation warnings appended to the write tool's result string (§3.7 item 2).
- **No** learner-state aggregate yet — in-memory, per-session-view state. Prove
  the authoring loop works before persisting anything.

**v1.5 — makes it a course rather than a document:**

- `LearnerProgress` aggregate + attempt endpoint + real server-side grading.
- `objective:` alignment report over the AST.
- `rubric`, `scenario`, `ordering`, `matching`, `reflection`, `poll`.

**v2 — the rest:**

- `srs_deck` scheduling, `jeopardy`, `timeline`, `diagram` hotspots,
  `code_exercise` with execution.
- Export: print/PDF first, Anki second, QTI third, cmi5 only on demand.

The riskiest assumption in the whole design is that the agent authors valid YAML
components reliably. That is measurable in an afternoon: pick the four v1 types,
prompt the model to produce twenty of each from a course brief, and count parse
failures and schema violations. If block scalars and explicit ids get it above
~95%, the design holds. If not, the fallback is a stricter, more line-oriented
body grammar — not a different fence.

---

## Sources

- [GitHub docs: Creating diagrams](https://docs.github.com/en/get-started/writing-on-github/working-with-advanced-formatting/creating-diagrams)
- [GitHub changelog: Mermaid, topoJSON, geoJSON, ASCII STL in Markdown](https://github.blog/changelog/2022-03-17-mermaid-topojson-geojson-and-ascii-stl-diagrams-are-now-supported-in-markdown-and-as-files/)
- [CommonMark: Generic directives/plugins syntax](https://talk.commonmark.org/t/generic-directives-plugins-syntax/444)
- [remarkjs/remark-directive](https://github.com/remarkjs/remark-directive)
- [Pandoc 8.18: Divs and Spans](https://pandoc.org/demo/example33/8.18-divs-and-spans.html)
- [jgm/pandoc#7480: align fenced_divs with directive syntax](https://github.com/jgm/pandoc/issues/7480)
- [MyST Specification](https://mystmd.org/spec)
- [MyST: Exercises and Solutions](https://mystmd.org/guide/exercises)
- [MyST-Parser: Roles and Directives](https://myst-parser.readthedocs.io/en/latest/syntax/roles-and-directives.html)
- [jupyter-book/myst-spec](https://github.com/executablebooks/myst-spec)
- [Obsidian Spaced Repetition: Cloze Cards](https://stephenmwangi.com/obsidian-spaced-repetition/flashcards/cloze-cards/)
- [st3v3nmw/obsidian-spaced-repetition](https://github.com/st3v3nmw/obsidian-spaced-repetition)
- [obsidian-spaced-repetition#450: cloze blank-line ambiguity](https://github.com/st3v3nmw/obsidian-spaced-repetition/issues/450)
- [MoodleDocs: GIFT format](https://docs.moodle.org/502/en/GIFT_format)
- [GIFT (file format) — Wikipedia](https://en.wikipedia.org/wiki/GIFT_(file_format))
- [H5P content types and applications](https://h5p.org/content-types-and-applications)
- [H5P Branching Scenario](https://h5p.org/branching-scenario)
- [1EdTech QTI 3.0 Overview](https://www.imsglobal.org/spec/qti/v3p0/oview)
- [QTI 3.0 Best Practices and Implementation Guide](https://www.imsglobal.org/spec/qti/v3p0/impl)
- [Comparison of SCORM, xAPI and cmi5](https://xapi.com/cmi5/comparison-of-scorm-xapi-and-cmi5/)
- [iCAN: xAPI vs SCORM vs cmi5 in 2026](https://icantech.ai/insights/xapi-vs-scorm-vs-cmi5-learning-standards-comparison)
- [mdx2md: LLM sanitization notes](https://github.com/icyJoseph/mdx2md/blob/main/docs/llm-sanitization.md)
- [mdx-js/mdx security policy](https://github.com/mdx-js/mdx/security)
- [Endor Labs: CVE-2026-22709 vm2 sandbox escape](https://www.endorlabs.com/learn/cve-2026-22709-critical-sandbox-escape-in-vm2-enables-arbitrary-code-execution)
- [LangChain deepagents: Sandboxes](https://docs.langchain.com/oss/python/deepagents/sandboxes)

---

## 4. Server-Backed Components and the Projection Boundary

The proposal on the table: server-side / server-backed components for things like
quizzing, where the markdown representation "is reduced to a type and an id of
some sort." What follows works through where that is right, where it is wrong,
and — more usefully — why "pointer vs inline" turns out to be the wrong axis to
argue about.

### 4.1 Verdict up front

The proposal is **right about the mechanism it names and wrong about the layer it
applies it to.**

- Reducing to `{type, id}` is exactly right for **learner state**. Attempts,
  scores, and SR schedules cannot live in the document and must be keyed by a
  stable id. This is the part of the proposal that is unambiguously correct and
  that §3.6 already assumes.
- Reducing to `{type, id}` as the **content storage model** for v1 is wrong,
  for reasons that are specific to this codebase (§4.4) rather than general
  taste.
- What delivers the stated goal — the server controls what the learner can see —
  is **server-side projection, not server-side storage.** These get conflated
  because both are "the server does it," but they have completely different
  consequences for forking, scrubbing, diffing, and export.
- Pointer components are nevertheless **genuinely necessary** for a real subset
  of behavior (§4.3, level 4-5), and the v1 design should be shaped so they can
  be added without a rewrite (§4.7).

### 4.2 Steelmanning pointer-only, honestly

Four arguments, in ascending order of strength.

**(a) Item reuse across lessons.** One well-written MCQ used in a pre-assessment,
a practice set, and a final. Inline means three copies that drift. *Assessment:*
real, but not yet. It presupposes a course library large enough for reuse to be
observed. It is also solvable at the inline layer by a transclusion field
(`from: bank/severity-classification`) resolved at parse time — reuse does not
require the *authoritative* copy to be server-side, only that one copy is
authoritative.

**(b) Central revision.** Fix a typo or a bad distractor once, and every lesson
using the item updates. *Assessment:* real, and the strongest *operational*
argument. But note it is in direct tension with this repo's architecture: a
central mutable item that changes under a historical session is precisely what
the event log exists to prevent (§4.4).

**(c) Analytics / psychometrics across usages.** Item difficulty, discrimination
index, distractor analysis need attempts aggregated by *item*, not by
*occurrence-in-a-file*. *Assessment:* real, and — importantly — **it does not
require pointer storage.** It requires a stable item identity that survives
copying, which a content fingerprint (§4.5) or an optional `bank_id:` field
provides while the content stays inline. This argument is often taken as
decisive for item banks; here it is not.

**(d) Preventing answer leakage into history.** The strongest argument, and the
one worth taking apart carefully, because the framing "the answers are in git
history even if the current file is stripped" imports an assumption that does not
hold here.

There is no git in this loop. The relevant history is the **event log**, and the
leak surface is concrete and enumerable:

- `GET /api/sessions/{id}/files?path=&at=` — any historical event index.
- `GET /api/sessions/{id}/files/history?path=` — `presenters.py:160` returns
  `content` for every event that touched the path, plus the edit intent
  (`old_string`/`new_string`), which leaks answers *even from a diff*.
- The `rendered | source` toggle in the client (`app.js:522`).
- The SSE feed, which carries file events as they happen.

So the honest statement is: **in this architecture the leak is not a storage
problem, it is a read-authorization problem, and it is worse than the git framing
suggests** — the edit-intent fields leak answer text through a route that never
returns a whole file. Pointer-only genuinely fixes it, by never putting the
answer in the log at all. That is a real property and it should be written down
as such.

But there is a second fix that costs far less and is more aligned with where this
product is going: **a publication boundary.** Learners do not browse an authoring
session. A finished lesson is *published* — snapshotted out of the session into a
`Publication` (or `Course`) aggregate whose stored form is already the learner
projection, with answers held in a companion record the learner-facing routes
never read. The authoring session, with its full history, is an author artifact
behind author authorization; the learner's read surface has never contained an
answer at any event index.

That reframes the whole question. If author and learner share a read surface,
neither projection nor pointers save you — the source toggle and
`/files/history` are right there. If they do not share a read surface, leakage is
solved by the boundary, and pointer storage buys nothing on this axis.

**Where the initial reading overstates its case.** The claim that an opaque-id
lesson "can't be exported to PDF or printed as a workbook" is too strong: export
runs server-side, so it can resolve pointers and emit a complete workbook. What
pointer-only actually costs is narrower and should be stated precisely:

1. **Diffability of item wording.** `presenters.py`'s edit-intent display and any
   review workflow that asks "what changed in this lesson?" go blind. For a
   product whose pitch is "the agent produces reviewable course materials," this
   is a real loss.
2. **Dumb-renderer readability.** `cat`, GitHub, another agent reading the file
   as context, a file copied out of the workspace. A file that reads
   `component:mcq\nitem: a7f3c1` is not a deliverable.
3. **Self-containment of the artifact.** The file stops being the thing and
   becomes a manifest referencing a service. Everything downstream — export,
   review, agent-reads-its-own-output — now needs the service.
4. **The per-block `audience` projection has nothing left to project**, which is
   correct as stated: projection presupposes something to project *from*.

### 4.3 The spectrum, precisely

| Level | In the markdown | On the server | What breaks / costs | Component types that belong here |
|---|---|---|---|---|
| **1. Inline-full** | Everything: prompt, options, `correct`, feedback, rationale | Nothing | Answers visible to anyone who can read the file. No grading record. | `flashcards`, `checklist`, `reflection`, `diagram`, `timeline`, `srs_deck` (content), `objectives`, `rubric` |
| **2. Inline + server grading** | Everything | Grades an attempt, records it; withholds nothing on read | Same leakage as L1; adds a real attempt record. Cheap. | Self-study practice: `cloze`, low-stakes `mcq`, `ordering`, `matching` |
| **3. Server-projected** (recommended v1) | Everything (source of truth) | Parses, strips `correct`/`feedback`/`rationale` for `view=learner`, grades via POST, records attempts | Leakage via raw-file routes remains until read-auth or a publication boundary exists. One extra round trip + cache. | All of L2, plus graded `mcq`, `matching`, `ordering`, `code_exercise` (tests withheld), `scenario` (unvisited branches withheld) |
| **4. Pointer to a server item** | `type` + `item: <bank-id>@<version>` + optional cached `prompt` for readability | Full item content, versioned, in an item bank | Diffs, dumb-renderer readability, self-containment (§4.2). Needs bank lifecycle, versioning, GC. | Reused/banked items; items with psychometric history; anything where central revision is a stated requirement |
| **5. Fully server-owned flow** | `type` + a *flow* id and parameters (`pool: severity-items`, `n: 5`, `time_limit: 30m`) | The item pool, the selection, the sequencing, the gating | Everything at L4, plus the document no longer determines what the learner sees — it is irreproducible from the file | Randomized item pools, timed/proctored exams, adaptive sequencing, mastery gates, question-per-attempt exam forms |

Two observations that matter more than the table:

- **L1-L3 differ only in server behavior, not in file format.** Moving between
  them is a configuration change. Moving to L4/L5 is a format change and a data
  migration. That asymmetry is the whole argument for starting at L3.
- **L5 is not "pointer components done harder" — it is a categorically different
  claim**, that the document no longer determines the experience. That is
  correct and desirable for a proctored exam and wrong for a lesson. Do not let
  L5's legitimate needs justify moving lessons to L4.

### 4.4 Reconciling with the event-sourced filesystem

This is where the objection is not taste but architecture, and it can be stated
sharply.

**Fork.** `SessionService.fork()` replays a source session to an event index;
`start_in_project()` reuses forking with a narrower replay because "a project
shares a workspace and not a chat history"
(`application/session_service.py:251-273`). Both are **copy-by-replay**. Files
fork. A server-side item referenced by a bare id **does not fork** — so editing
an item in a forked session mutates the parent's lesson too. Forking is a
first-class feature here (there is a fork tree endpoint and a tree view in the
UI); a component that silently ignores it is a bug factory.

**Scrub.** `state_at(session_id, at)` refolds the filesystem to a past event, and
the file route explicitly supports reading a file that no longer exists at HEAD
because "seeing a deleted file again is the point of time travel, not an error"
(`app.py:306-320`). A bare-id pointer renders *today's* item inside *last
Tuesday's* lesson. The timeline stops being a faithful record.

**Both breakages have the same cause and the same fix: mutability, not
location.** A **version-pinned, immutable** pointer — `item: severity-class-1@7`,
where item versions are append-only and never edited in place — forks correctly
(the pin is copied with the file) and scrubs correctly (the pin at event N still
resolves to version 7). It also kills argument (b): central revision no longer
propagates, because propagation is exactly the thing that breaks fork and scrub.
You can have referential integrity or you can have central revision; in an
event-sourced system you cannot have both, and this system has already chosen.

So: pointer components are compatible with this architecture **iff** pinned and
immutable, and a pinned immutable pointer has given up the strongest operational
reason to want pointers at all. That is the crux, and it is why the
recommendation lands where it does.

**If an item bank is built, where does it live?** As a **separate aggregate with
its own event stream**, `ItemBank`, scoped to a `Project` — the same boundary
that already scopes a shared workspace and the redstring knowledge graph. Events:
`ItemDrafted`, `ItemRevised` (produces a new version, never mutates), `ItemRetired`.
Version numbers are monotonic per item. A read model materializes
`(item_id, version) -> content` for O(1) resolution during parse. It must not be
a projection of the session log (items outlive sessions) and it must not be
outside the log entirely (then it is unauditable state the timeline can't
explain). **UNVERIFIED:** that the project boundary is the right tenancy scope
for items — that depends on whether courses are expected to share items across
projects, which is a product question, not an architectural one.

### 4.5 Learner state, concretely

**Aggregate, not read model.** `LearnerProgress`, one per `(learner_id, course_or_project)`,
with its own event stream. Read models (mastery per objective, SR due-queue,
gradebook) are folded from it. The sequence of attempts is the pedagogically
interesting object, so the log is the right primitive — the same reason the
filesystem is a log here.

**Key.** `component_ref = (session_id | publication_id, path, component_id)`.
Path is included deliberately: the same `component_id` in two lessons is two
occurrences, and conflating them would corrupt both gradebook and psychometrics.

**Events, xAPI-verb-named** (§2.6), so an LRS bridge is a projection:

```
ComponentAttempted(ref, response, item_fingerprint, at_event, occurred_at)
ComponentAnswered(ref, response, correct, score, item_fingerprint, ...)
ComponentCompleted(ref, ...)
ComponentPassed / ComponentFailed(ref, score, threshold, ...)
CardReviewed(ref, card_id, grade, next_due, ...)
ChecklistItemToggled / ReflectionSubmitted(...)
```

**Version skew — the real problem the id alone doesn't solve.** An id says
*which* component was answered, not *which version*. Record both:

- `item_fingerprint` — `sha256` of the **normalized component AST** (parsed,
  key-sorted, whitespace-normalized, so cosmetic reformatting doesn't churn it).
- `at_event` — the session event index the learner's view was rendered from.

Together these make every attempt reconstructible: `state_at(session_id, at_event)`
refolds the exact file, and the fingerprint confirms the component in it is the
one that was answered. This works identically for inline (L1-L3) and pinned
pointers (L4) — for pointers the fingerprint is just the fingerprint of the
resolved version — which is what makes the migration in §4.7 non-breaking for
recorded history.

Policy on skew, worth deciding explicitly rather than by default:

| Change | Fingerprint | Treatment |
|---|---|---|
| Whitespace/formatting only | unchanged (normalized) | Continue the same item history |
| Feedback/rationale text edited | changed | Continue history; flag as `cosmetic` — did not change what was asked or what was correct |
| Distractor added/reworded, prompt reworded | changed | **New item generation.** Aggregate psychometrics separately; keep the gradebook |
| Correct answer changed | changed | **Invalidate prior attempts** for grading purposes. Never silently regrade; surface it |

Detecting which bucket a change falls in is a diff over the parsed component, not
over the text — another reason parsing lives server-side (§3.5).

### 4.6 Id stability

Ids are load-bearing at every level of the spectrum, so the rules are not
optional:

**Authoring rules** (enforced by the validator, stated in the prompt):
- Required, explicit, kebab-case, `^[a-z0-9]+(-[a-z0-9]+)*$`, 3-64 chars.
- Unique within the document. Uniqueness *across* the workspace is required only
  for banked items (L4) — document-scoped ids plus the path key avoid needing
  global coordination.
- Derived from content, not position: `sev-classification-scenario`, never
  `q1`, `question-3`, `mcq-2`. Positional ids are the single largest source of
  silent reattachment when the agent inserts an item.
- Never reuse an id for different content; never renumber.

**Collision avoidance.** Namespacing by document is enough (`modules/03-severity.md`
+ `sev-classification-1`). If a bank exists, banked ids are prefixed
(`bank:severity/classification-1`) so the two spaces cannot collide by accident.

**Validation** (all in the same pass as schema validation, §3.3):
1. Duplicate id within a document → **error**.
2. Missing id → **error** (with a suggested slug derived from the prompt, so the
   agent's fix is mechanical).
3. Positional-looking id (`q\d+`, `item-?\d+`) → **warning** with a suggestion.
4. **Id present in a prior version of this file with recorded attempts, now
   absent** → **warning** on write: `"'sev-classification-1' had 14 recorded
   attempts and is no longer in this file; those attempts are now orphaned."`
   This is the check that actually protects learner data, and it is only
   possible because both the file history and the attempt log are queryable
   server-side.
5. Id present but fingerprint changed in the "correct answer changed" bucket →
   **warning** naming the regrade consequence.

Checks 4 and 5 are the concrete payoff of putting validation on the write path
(§3.7 item 2): the agent gets told it just orphaned learner data, in the tool
result, while it can still fix it.

### 4.7 Recommendation, and the migration path

**v1 = spectrum level 3.** Full component inline in the markdown; server parses,
validates, and serves `view=author | view=learner`; grading is a POST resolved
against the full source; attempts recorded in `LearnerProgress` with
`item_fingerprint` + `at_event`. No item bank. Ids required and validated per
§4.6. This is the initial reading's position and I think it is correct, for a
sharper reason than "pointers break the file property": **L1→L3 are the same file
format, so level is a runtime decision, while L4 is a migration.** Starting at L3
costs nothing and forecloses nothing; starting at L4 forecloses L1-L3 permanently.

State the leakage caveat plainly in v1 docs (§3.5) and put the **publication
boundary** on the roadmap ahead of any item bank — it is the thing that actually
closes argument (d), it is independently needed for shipping a course to
learners, and it is much less machinery than a versioned bank.

**The forward-compatibility hinge — do this in v1, it is nearly free.** Make the
parser's output shape identical whether a component's content came from the file
or was resolved from a bank:

```jsonc
// ILLUSTRATIVE -- parsed component node
{"kind": "component", "type": "mcq", "id": "sev-classification-1",
 "source": {"origin": "inline"},                       // v1
 // "source": {"origin": "bank", "item": "severity/classification-1", "version": 7},
 "fingerprint": "sha256:...",
 "data": {...}}
```

Everything downstream — renderers, grading, export, `LearnerProgress` — keys on
`fingerprint` and `data`, never on where the content came from. Resolution
becomes one step inserted before projection.

**Migration path to an item bank, if reuse demand actually shows up:**

1. **Signal, not speculation.** Trigger on measured duplication — the same
   fingerprint (or high-similarity prompt) appearing in ≥3 documents — or an
   explicit request for central revision. Do not build it on the argument that
   item banks are what serious assessment systems have.
2. **Extract, don't rewrite.** `ItemBank` aggregate (§4.4), project-scoped,
   append-only versions. A tool promotes an inline component to a banked item and
   rewrites the file in place to a pinned reference.
3. **Pins are mandatory.** `item: severity/classification-1@7`. Unpinned
   references are a validation error, because unpinned is exactly what breaks
   fork and scrub (§4.4).
4. **Keep a readable cache in the file.** Carry `prompt:` (and only `prompt:`)
   alongside the pin, marked `cached: true`, so the file still reads as a
   document in `cat`, in a diff, and to another agent — and so the diffability
   loss in §4.2 is partially bought back. The bank stays authoritative; a stale
   cache is a validator warning, not an error.
5. **Recorded history is unaffected** — attempts were keyed on fingerprint all
   along, and the resolved item's fingerprint is the same value the inline
   component had.

**Where pointer/flow components are the right answer from day one, if these
requirements appear:** randomized item pools, timed or proctored exams,
question-per-attempt exam forms, adaptive sequencing, and mastery gates. These
are level 5, not level 4 — the server owns the *flow*, and the document declares
parameters rather than content. They should be a distinct, small set of component
types (`exam`, `pool`, `gate`) that are explicitly documented as *not*
self-contained, rather than a change in how ordinary lesson components are
stored. Keeping that line bright is what prevents the exam use case from dragging
the lesson use case to level 4 behind it.
