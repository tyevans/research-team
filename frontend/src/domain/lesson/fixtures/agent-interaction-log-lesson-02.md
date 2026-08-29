---
title: The field the system bothers to truncate
area: agent-interaction-log
builds_toward: Understanding 2 — the most sensitive field is user-typed text, logged by default
---

## The cap

Someone pastes a whole document into the ask box — a paper, a memo, a wall of text — and the system stores only the first 4,000 characters. Roughly 700 words. The rest is gone.

The README is explicit about the cap: "Each of the two is truncated at 4,000 characters — roughly 700 words — so a document pasted into the ask box is stored as its opening rather than in full." [[src:github-com-tyevans-research-team-blob-main-readme-md-8f240ffa]]

You would not expect a system to bother capping a field at ~700 words unless it knew that field was different from the others. It does. The cap is a tell: you do not truncate an id, you do not truncate a duration, you do not truncate a view name. You truncate the one field that could be a whole pasted document, because that field is a different kind of thing from the rest.

What makes it different, and who the decision to store it at all belongs to, is the question this lesson answers.

## The line the system draws

The interaction log records what the console user does — navigation, dwell, search, approval decisions — and POSTs it to a second, separate event store from the one holding sessions. [[src:github-com-tyevans-research-team-blob-main-readme-md-8f240ffa]] Within that vocabulary, the system draws a line, and the line is the point.

Two fields carry text the user typed, and nothing else in the vocabulary does: `AskSubmitted.query_text` — the research prompt itself, whatever someone typed to ask the agent something — and `SearchPerformed.query_text`, every entity search run in the console. [[src:github-com-tyevans-research-team-blob-main-readme-md-8f240ffa]] Everything else is structure: ids, view names, counts and durations, with a zero-result search recorded as its length rather than its text. [[src:github-com-tyevans-research-team-blob-main-readme-md-8f240ffa]]

```component:definition
id: ail-l2-def
entity: AskSubmitted.query_text
entity_id: e5dc7038-622a-5a71-95c9-5622e4209a59
```

The distinction is the tool you will need. A field that carries the person's own words is a different kind of thing from a field that carries metadata about what happened. The person's words are free-form, unbounded, and composed deliberately — they could be a research question, a pasted document, a private note. The structure is bounded and mechanical: an id is an id, a duration is a number of seconds, a view name is a name from a fixed set. When you are looking at a schema and trying to decide which fields are sensitive, the line to draw is this one: does the field carry the person's words, or does it carry the shape of what happened?

## The most sensitive field

The README does not hedge about which of the two text fields is the most sensitive: "The first is the most sensitive field in the system, and both are logged by default." [[src:github-com-tyevans-research-team-blob-main-readme-md-8f240ffa]]

```component:compare
id: ail-l2-compare
entities:
  - AskSubmitted.query_text
  - SearchPerformed.query_text
```

Both fields carry the person's words, but they are not equally sensitive. A search query is a fragment — a name, a term, a probe. The person types it to find something, and it is usually short. The research prompt is the full statement of what the person wants the agent to do, and it is where they are most likely to paste something they did not intend to keep. That is why the cap matters most on the prompt: it is the field where a whole document is most likely to land, and it is the field the README calls the most sensitive in the system.

## What "logged by default" commits the system to

"Logged by default" is not a config detail. It is a decision, and the decision has a real owner.

`AGENT_INTERACTION_LOG` is the only default-on boolean in this project. [[src:github-com-tyevans-research-team-blob-main-readme-md-8f240ffa]] Everything else that reaches the network is off or gated by default; this one field is the exception, the one thing the system collects without asking. "Logged by default" means the capture happens without the person whose text it is opting in. The decision to capture their words was made by whoever set the default, not by them. That person is the real owner of the decision — it is their text, their privacy, their words — but they did not make it. The default was set on their behalf.

A config detail is something you do not think about, that is buried, that nobody owns. A privacy decision should be visible and reversible, because it has a real owner. The system treats this field as the latter: the boolean is named, it is the only default-on one, and it is reversible. Setting `AGENT_INTERACTION_LOG=0` removes the dependency entirely, and the ingest route then answers 503 rather than silently accepting and discarding. [[src:github-com-tyevans-research-team-blob-main-readme-md-8f240ffa]] The 503 is the point: the system does not pretend the route is there when it is not. The decision is visible, and it can be reversed.

## The cost of getting it wrong

If you treat the free-text field as structure — just another config detail — you miss two things. You miss that it is the most sensitive field in the system, and you miss that logging it by default is a privacy decision with a real owner, not a config detail.

The evidence is in the README: the log "has no reader today: no read API, no browser view, nothing consumes it yet. It exists to build a real corpus before later work designs friction detection against it." [[src:github-com-tyevans-research-team-blob-main-readme-md-8f240ffa]] The most sensitive field is being captured by default, for a question that does not exist yet. If you get this wrong, you design a new log that captures user-typed text by default without recognizing you are making a privacy decision on someone's behalf — you bury it in a config default rather than making it visible and reversible, and the person whose text it is never gets to see the decision or reverse it.

## Apply it to a schema you have not seen

You are about to design a new log. It has five fields: an id, a view name, a duration, a count, and a free-text field holding the user's typed prompt. Flag which carry user-typed text and which are structure.

The id, the view name, the duration, and the count are structure. They are bounded, mechanical, and they tell you what happened without carrying the person's words. The free-text field is the one that carries the person's own words. It is the most sensitive field in the new log, and it is the one you must decide about.

Now argue whether the free-text field should be logged by default or by opt-in. "Logged by default" means the system captures the person's words without asking them, and the decision was made on their behalf. If you log it by default, you are making a privacy decision with a real owner — the person whose text it is — and that decision should be visible and reversible, not buried in a config default.
