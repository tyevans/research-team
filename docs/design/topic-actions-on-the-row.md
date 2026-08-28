# Topic actions on the row, and what the queue header stops being

Read out of the working tree on branch `autonomy-lock-in-the-chrome` at
`fc03e8a`, which is `main` plus the autonomy lock. Line numbers are pointers,
not contracts.

This document does three things: it says why the project page's QUEUE header
is four stacked bands and should not be, it proposes the verbs that replace
them, and it argues that the unbounded autonomous run is not a feature the
console should offer — because the thing it was for is now expressible as a
bounded fan-out over the queue it was working from.

## 0. The ask, as given

> instead of the two ask buttons living in the queue header, reimagine where
> they live. Topic management — seeding and browsing — into a drawer like the
> security toggles. Autonomous research rounds and its kick-off: one, doesn't
> need to be that wordy, and two, maybe doesn't need to exist. Maybe in the
> list of topics we could have "find sources" or "write our understanding" or
> "refine this question", in an icon way that makes sense and looks good and
> isn't cluttered. We could also have a "find sources for all topics" button —
> that makes sense to me as the alternative to the unbounded autoresearch
> button.

Everything below is an argument for or against a part of that, and where it
departs from the ask it says so in the same paragraph.

## 1. What the header is now, measured rather than remembered

`QueueHeader` renders, in a 320px rail, top to bottom:

1. A full-width bordered band, **"Ask this project →"**.
2. A full-width bordered band, **"Be asked about this project →"**.
3. A card, **"Autonomous research"**: a title, a status chip, a link to the
   run's session, a two-sentence paragraph, a number input placeholder'd
   `max rounds (optional)`, and a `Start a run` button. Once a run has been
   watched it grows five counters, a working-on line, and an ending box with
   a headline, a paragraph, and the number input again.
4. A card, **"Seeding"**: `SeedForm`, its own subject field and submit.

Below all of it, the actual queue: a search box, four filter tabs, and the
topic rows.

That is roughly 320px of header above the first topic on a fresh project, and
the header is not a scroller by design — so on a short viewport the queue
begins below the fold and the rows, which are the only things on this page a
person acts on repeatedly, are the last thing they reach.

The four bands also have nothing in common except that they were each, at
some point, the newest thing added to this pane. Two are links that leave the
page. One configures a background loop. One starts a bounded turn. The
`QueueHeader` docstring already argues they are ordered by "how often does
somebody touch this", and that ordering is now false in both directions: the
ask links are the *least* touched (they leave the page) and sit first; seeding
is touched once per project and sits last but is the only one an empty project
needs.

**The deeper problem is that none of them are about a topic**, and the queue
is a list of topics. Every verb in this header acts on the project as a whole,
so a reader who has just read a row and wants to do something about *that row*
has one control — `Write understanding` — and everything else is 300px up the
page acting on something else.

## 2. The proposal in one screen

```
┌─ TOPICS ─────────────────────────────────────────────┐
│ [ search                    ]  ⚙  💬  ❔             │  ← toolbar
│ [ All 12 ][ Needs you 3 ][ Live 7 ][ Closed 2 ]      │
├──────────────────────────────────────────────────────┤
│ How does spacing interval affect retention?          │
│ investigating · 3 sources · 2 open      🔍  ✎  ⋯     │
├──────────────────────────────────────────────────────┤
│ What counts as a primary source here?                │
│ open · 0 sources                        🔍  ✎  ⋯     │
└──────────────────────────────────────────────────────┘
```

- **`⚙` opens the Topics drawer**: seeding, and the bulk verbs, including
  *Find sources for every topic shown*.
- **`💬` / `❔`** are the two ask links, as icons on one line rather than two
  full-width bands.
- **`🔍` / `✎`** are per-topic verbs. The third, "write our understanding",
  and `Manage`, live under `⋯`.

Everything from §1's list 1–4 leaves the header. The header becomes the
toolbar line and the filter tabs — which is what it was for.

## 3. The verbs

Three per-topic actions, of which one exists:

| verb | action | shape | exists |
|---|---|---|---|
| Find sources | `research` | one turn, may fetch | **new** |
| Write our understanding | `understanding` | one turn, reads only | yes |
| Refine this question | `refine` | one turn, reads only | **new** |

### 3.1 `research` — and why it is buildable now when it was not

`docs/design/topic-dispatch.md` §1 classes "research and fetch sources" as
*unbounded* and models it as an `AutoResearchRun` scoped to one topic, and
`BACKLOG.md` B24 records why it could not fetch: `fetch` floors at `ask`, and
an unattended loop that reaches an approval "either deadlocks on a future
nobody will resolve or is auto-rejected outright".

**The blocker is about being unattended, not about fetching**, and a dispatch
is attended by construction: a person pressed a button on a row, on a page,
seconds ago, and the approvals surface is on that page. The design document
says exactly this and then says to ship it anyway — §"Short version": *"Its
'fetch primary sources' half is blocked on `BACKLOG.md` B24 and should ship
**attended** rather than waiting for it."* That sentence has been true and
unacted-on since the document was written.

So `research` is `understanding`'s shape — one turn, `TopicSeeder`-shaped,
`start_in_project` → run → release in a `finally` — with a prompt that says to
search and fetch, and no loop. It is bounded because a turn is bounded. It is
not `AutoResearchRun` scoped to one topic; that model was chosen for a thing
that runs for an hour without a person, and this is not that.

What it costs, stated plainly: **one turn will not exhaust a question.** An
`AutoResearchRun` would keep going until it stopped finding things; this will
fetch what one turn's worth of searching reaches and stop. The answer is that
the button is cheap and pressing it twice is allowed — and that a person
watching one turn's results decide whether a second is worth it is better
research practice than a loop deciding for itself. This is the same argument
`topic_seeding.py` makes for seeding and it holds here for the same reason.

**Under an `ask` policy this asks.** That is not a degraded mode; it is the
feature working. The approvals already surface in the console, and the person
who pressed the button is the person who answers. Under a policy with `fetch`
at `auto` — set from the lock in the chrome — it does not ask. Nothing in this
design lowers a floor, and nothing may: B24's "a loop that can edit its own
permissions makes the floors advisory for everything else too" is the rule,
and the only reason it is not in tension here is that the *person* set the
policy, from a control that says out loud that it is instance-wide.

### 3.2 `refine` — the verb the queue has been missing

Seeding names questions from a subject in one burst; nothing since has ever
edited one. A question that arrived badly worded stays badly worded, and the
only recourse is `TopicManagePane`'s free-text edit — a person rewriting the
model's question by hand.

`refine` is one turn that reads what the project has gathered *for this topic*
and rewrites the question to be answerable by it: narrowing an unanswerably
broad question, splitting a compound one into sub-questions, or recording that
the material shows the question was the wrong one. It writes through the
topic's existing events (the question and its sub-questions are already
editable through `TopicManagePane`'s routes) and adds no vocabulary.

**Why it is worth building rather than left to the person:** the failure it
addresses is specific and observed in the seeding output — a seeded queue
contains questions that no amount of research can close because they were
never questions. Today those sit in the queue forever, because closing them is
an admission and refining them is typing.

### 3.2a What `refine` turned out to be, which is not quite what §3.2 asked for

§3.2 says `refine` "rewrites the question". **It cannot, and the implementation
says so rather than pretending otherwise:** no tool a dispatch turn holds can
rewrite a topic's question. The HTTP route that edits one exists for a person,
through the manage pane; there is no agent-facing equivalent.

So `refine` writes `refinement.md` into the topic's directory, opening with a
verdict on its own line — `fine`, `narrow`, `split` or `wrong` — then the
proposed wording, then why the material supports it. A person applies it.

Two consequences that bind the interface:

- **The row's control must not claim to rewrite anything.** "Refine this
  question" over a button that produces a proposal a person then applies is a
  label that lies about who decided. Whatever the icon's accessible name is, it
  has to survive a reader pressing it and finding a document.
- **The proposal has to be reachable, or this is the silent-output failure
  again.** It is: `refinement.md` lands under `/topics/<nn>-<slug>/`, which
  `TopicDocuments` already lists. Nothing new is needed, but nothing may break
  that either.

Also deliberate, and it costs something: the refine prompt forbids
`record_finding`, so a turn that genuinely learns about the *subject* while
reading has nowhere to put it. The alternative is worse — findings recorded by
a turn that never fetched are `UNDERSTANDING_PROMPT`'s failure with a different
verb.

And the verdict line is **not parsed by anything in Python**, on purpose. It is
there so a person scanning several refinements can sort them. Asserting on it
would be the half-a-contract mistake `CLAUDE.md` records paying for four times.

### 3.3 "Find sources for every topic shown" — the bounded fan-out

This is the ask's own proposal and it is the right one. It enqueues a
`research` dispatch for **each topic currently shown by the filter** — not for
every topic in the project — and the distinction is the whole safety
property: the count is on screen (`All 12`), the scope is something the person
chose, and `Needs you 3` is a three-item fan-out rather than a forty-item one.

The client sends the list of topic ids. The server does not decide the scope,
and deliberately: a route that took "all" would have to define "all" against a
queue the client is filtering, and the two definitions would drift.

The existing dispatch queue already does the rest — FIFO, one in flight per
project, `Stop` drops the lot — so this is a loop over an existing route, and
the aggregate bar the queue already renders (`1 running, 11 queued`) is
already the progress display. **This is the single strongest argument for
deleting the run panel**: the fan-out's progress surface already exists, is
already live, and is already per-topic.

## 4. What goes away

### 4.1 The autonomous run panel, and its HTTP routes

Deleted from the console: `RunPanel`, `RunView`, `ResearchDisabledNotice`,
`RunView.stories.tsx`, the `research` port on the container, the `ResearchRun`
domain model in `frontend/src/domain/research/run.ts`, and the `run-*` rules
in `components.css` that dress it.

Deleted from the server: `POST /api/projects/{id}/auto-research`, its status
GET and its cancel POST, and the `ResearchDisabledError` path the console
needed to explain a route that answered 503.

**Not deleted**: `domain/research_run.py`, `application/research_run.py`,
`application/research_round.py`, `application/research_supervisor.py`. The
REPL's `/research [n]` drives them and is a real caller. This is a deletion of
a *surface*, not of a capability, and saying which is which is the point —
`git log` should not later read as though the run machinery was removed.

The case for deleting the surface rather than merely shortening its prose:

- **It is the only control in the console that spends an hour of model time
  from one press**, and the only one whose stated ending vocabulary needs a
  paragraph per outcome to be honest about what happened. `RunPanel` is 365
  lines and `run.ts` adds a closed `StopReason` enum with five endings, five
  tones and five paragraphs. That weight is proportionate to a feature whose
  outcome nobody can predict; it is not proportionate once the same work is
  available as twelve visible dispatches a person can stop.
- **It is off by default.** `AGENT_RESEARCH_RUN` is unset in a default
  install, so what a default install actually renders is
  `ResearchDisabledNotice` — a card whose entire content is an apology for
  itself. That card has been the most prominent thing in the QUEUE header on
  every default install since it shipped.
- **Its failure mode is the one thing the fan-out cannot have.** A run decides
  for itself which topic to work and when to stop; a fan-out works the topics
  a person chose, in a queue a person can watch and stop. The ask's instinct —
  "maybe doesn't need to exist" — is correct, and the reason is not that the
  panel is wordy but that per-topic dispatch made it redundant.

*What would falsify this:* if in practice people press "find sources for every
topic" and then immediately want a second and third pass without pressing
again, the loop was the feature and this removes it. The way back is to build
the loop *over dispatches* — re-enqueue until quiet — which is a smaller thing
than the aggregate that exists, and would land on the fan-out button rather
than in a card of its own.

### 4.2 The two ask bands

They become icons on the toolbar line, keeping both routes reachable — which
is the property `QueueHeader`'s docstring records having lost once already,
when deleting two views deleted the last inbound link to a page that still
worked. **Any change here must keep exactly two inbound links**, and the story
test for it is that `projectHref` is called with `facet: 'ask'` and with
`facet: 'dialogue'` from something the queue pane renders.

Icons alone are not enough: an unlabelled icon with no accessible name is the
S-D2 defect the console already records, and `AutonomyLock` is the worked
example of the fix — a `Tooltip` for the mouse *and* an `aria-label` carrying
the same sentence, so a screen reader and a keyboard both get it without the
tooltip opening.

### 4.3 Seeding, out of the header and into a drawer

`SeedPanel` moves behind the `⚙` toolbar button, into a `Drawer` — the same
primitive the lock opens, for the same reason: a control touched once per
project should not hold permanent height on a rail whose job is a list.

**This is a departure from the ask, which said "seeding and browsing".** The
search box and the filter tabs stay inline. A filter is not a setting; it is a
statement about what the list in front of you currently is, and putting it
behind a door means a reader can be looking at three of twelve topics with
nothing on screen saying so. The tabs already carry their counts for exactly
that reason. What moves into the drawer is everything that *configures* the
queue rather than *describes* it.

## 5. Verification, and the traps this repository has already paid for

- **The dressing trap.** `SeedPanel`, `SeedForm` and anything the drawer holds
  must not depend on a stylesheet on the die-with-its-screen list. `run-*` in
  `components.css` is deleted with `RunPanel` in the same commit, not left
  dead. Whatever survives carries its dressing as utilities. jsdom applies no
  stylesheet, so no test can catch a class that resolves to nothing — this is
  a review obligation and a `check-deleted.mjs` rule, not a test.
- **The icon-row measurement.** Three icon buttons plus a `⋯` on a 294px row,
  beside a status chip and a dispatch chip that is already clamped to `18ch`,
  is exactly the width fight `TopicQueue`'s `CHIP` comment records losing
  twice. `TopicQueue.browser.test.tsx` is where a row's contents get measured;
  a new one is required, and it must fail before it passes.
- **The one-adapter seam.** The bulk fan-out's client and the dispatch route
  must be tested against each other over real data, not each against a stub.
  CLAUDE.md's co-mention entry is the cost of not doing this.
- **The checkpoint/prompt contract.** `research` and `refine` add prompts. If
  anything in Python asserts on text those prompts produce, the literal is a
  constant the prompt interpolates, and a test holds the pair. This design
  asserts on nothing a model writes, which is the cheapest way to comply.
- **The route's action set.** `DISPATCH_ACTIONS` and `DispatchAction` are two
  spellings of one vocabulary and the existing test asserting the route
  refuses an unknown action by name is what notices if only one is widened.
