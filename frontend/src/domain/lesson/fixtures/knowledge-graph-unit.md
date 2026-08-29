# Knowledge Graph

The knowledge graph in this project is a projection folded from the event log: a structure of entities and relationships extracted from text by `remember`, read back by `graph_search`, and corrected by `unmerge`. It is not a second source of truth — it is rebuilt whenever a project opens, and costs nothing to lose. [[src:github-com-tyevans-research-team-blob-main-readme-md-8f240ffa]] The graph is what the corpus actually connects, and it is the substrate from which learning areas are clustered and ordered into a path. [[src:github-com-tyevans-research-team-blob-main-readme-md-8f240ffa]]

## Enduring Understandings

1. **A projection that can be rebuilt at any time is more trustworthy than a store that is maintained incrementally, because the log is the only source of truth and anything computed from it can be thrown away.** The session list's projection, the knowledge graph, and the learning-area clusters are all pure functions of the log; a fold is recomputed every time and cannot be stale, while a projection written down once can be wrong permanently if a handler throws. [[src:github-com-tyevans-research-team-blob-main-docs-design-architecture-md-a0edb5a8]] [[src:github-com-tyevans-research-team-blob-main-readme-md-8f240ffa]]

2. **The shape of a knowledge graph is determined by evidence of different strengths, and the system must weight those channels explicitly rather than letting a single channel dominate.** A stated relationship is the strongest evidence that two entities belong together; two names in one passage is weaker; an entity's nearest neighbour in embedding space is a hypothesis no document ever made, so it is weighted below both and drawn only above a similarity floor. The co-mention channel takes entities dropped from 105 to 7 on a five-article corpus; the semantic channel takes that 7 to 1 — so the second is real and small. [[src:github-com-tyevans-research-team-blob-main-readme-md-8f240ffa]]

3. **Gating write operations is what makes a shared knowledge structure trustworthy across sessions, because both `remember` and `unmerge` change what every later session sees, while `graph_search` does not.** Read-only tools are not gated — there is nothing to approve about a read. The asymmetry between read and write is the mechanism that keeps the graph honest: a write is a commitment that outlives the session that made it. [[src:github-com-tyevans-research-team-blob-main-readme-md-8f240ffa]]

4. **Learning areas are clusters the corpus actually connects, not topics chosen for the learner, and their ordering into a path is derived from dependency relationships in the graph, never asked of a model.** Each step carries the evidence that placed it, and where two areas genuinely depend on each other the path says so instead of quietly picking one. [[src:github-com-tyevans-research-team-blob-main-readme-md-8f240ffa]]

## Essential Questions

1. Why is a projection that can be rebuilt at any time more trustworthy than a store that is maintained incrementally — and what does that cost in terms of failure modes a fold does not have?

2. What is the epistemic status of a semantic edge (embedding similarity) compared to a stated relationship, and why must the system weight them differently even when the similarity is high?

3. What is the difference between a command and an event, and why does that distinction matter for the integrity of the log? A command that `decide` refuses leaves no trace; an event is a frozen fact written down forever. [[src:github-com-tyevans-research-team-blob-main-research-team-domain-commands-py-4a46b411]]

4. Why are `remember` and `unmerge` gated but `graph_search` is not, and what does the asymmetry between read and write tell us about what the system considers reversible?

5. What does it mean for a knowledge graph to be "folded from the log" rather than "maintained as a database," and what does that buy in terms of reproducibility — a project reopened years later reproduces the same graph without depending on a live model call? [[src:github-com-tyevans-research-team-blob-main-readme-md-8f240ffa]]

## Knowledge

- The knowledge graph is a projection folded from the event log, rebuilt whenever a project opens, and costing nothing to lose. [[src:github-com-tyevans-research-team-blob-main-readme-md-8f240ffa]]
- Three tools make the graph: `remember` extracts entities and relationships from text and records them permanently; `unmerge` reverses a consolidation the matcher got wrong; `graph_search` reads it back. The first two are gated because both change what every later session sees. [[src:github-com-tyevans-research-team-blob-main-readme-md-8f240ffa]]
- Extraction runs once, when `remember` is called; what it produced is what replays thereafter. A project reopened years later reproduces the same graph without depending on a live model call. [[src:github-com-tyevans-research-team-blob-main-readme-md-8f240ffa]]
- The graph decides the shape and embeddings close the gaps in it. A stated relationship is the strongest evidence; two names in one passage is weaker; an entity's nearest neighbour in embedding space is a hypothesis no document ever made, so it is weighted below both and drawn only above a similarity floor. [[src:github-com-tyevans-research-team-blob-main-readme-md-8f240ffa]]
- What gets embedded is the entity's card — its name, type, properties and named relations — rather than the bare name. The vectors are on the event log, so a project folds them back at open along with the graph and the corpus. [[src:github-com-tyevans-research-team-blob-main-readme-md-8f240ffa]]
- Learning areas are clusters of entities the corpus actually connects, ordered into a path by which areas the others depend on. The ordering is derived, never asked of a model; each step carries the evidence that placed it. [[src:github-com-tyevans-research-team-blob-main-readme-md-8f240ffa]]
- Nothing about the projection is stored. It is a pure function of a graph that is itself folded from the log, and every view shows the entity, relationship and passage counts it was built from — so a thin result is visible as thin rather than merely looking like a small project. [[src:github-com-tyevans-research-team-blob-main-readme-md-8f240ffa]]
- Gated tools have three levels: `auto` runs it, `ask` interrupts the turn for a person, `deny` refuses without asking. Read-only tools are not gated. A change takes effect on the next tool call, including one made partway through a running turn. [[src:github-com-tyevans-research-team-blob-main-readme-md-8f240ffa]]
- A project is a set of sessions sharing a filesystem lineage and a knowledge graph, one at a time. That inheritance is forking applied across sessions, which is why a project's filesystem still folds out of one event stream and time travel still works on it. [[src:github-com-tyevans-research-team-blob-main-readme-md-8f240ffa]]
- Content passed to `remember` leaves the process to be extracted, reaching the same model endpoint every turn already uses. With `AGENT_GRAPH_STORE=neo4j` the graph leaves too, and with embeddings on — the default — every extracted entity's name is sent to an embedding endpoint. [[src:github-com-tyevans-research-team-blob-main-readme-md-8f240ffa]]
- Commands are values, not method calls: `decide` matches on the pair (command, state), so a request has to be something you can hold, pass to a pure function, and assert about without an aggregate in scope. They are never stored. A command that `decide` refuses leaves no trace. [[src:github-com-tyevans-research-team-blob-main-research-team-domain-commands-py-4a46b411]]
- Events are frozen facts about the past and are written down forever. The log records what happened, and a rejected request did not happen. [[src:github-com-tyevans-research-team-blob-main-research-team-domain-commands-py-4a46b411]]
- The session is written as a decider: `decide(command, state)` says which requests are legal and what facts they produce, `evolve(state, event)` says what each fact does, and `Session` is a thin shell that connects those two pure functions to replay, snapshots, and the repository. The rules test as rules. [[src:github-com-tyevans-research-team-blob-main-docs-design-architecture-md-a0edb5a8]]
- The log lives in SQLite. Listing sessions reads a projection — a table kept up to date event by event by a SubscriptionManager, which replays from a persisted checkpoint on startup and then follows the live bus. [[src:github-com-tyevans-research-team-blob-main-docs-design-architecture-md-a0edb5a8]]
- A fold is recomputed every time, so it cannot be stale and a fixed bug is retroactive. A projection is written down once: if a handler throws, the row it would have updated is wrong permanently — a restart does not help, because catch-up resumes after the event that was never applied. [[src:github-com-tyevans-research-team-blob-main-docs-design-architecture-md-a0edb5a8]]
- Rebuilding is idempotent and safe to reach for on a hunch: the log is the only source of truth, so anything computed from it can be thrown away. [[src:github-com-tyevans-research-team-blob-main-docs-design-architecture-md-a0edb5a8]]
- The four layers are domain, application, infrastructure, and interfaces; imports only ever point inward. The domain layer knows nothing about langchain, deepagents, SQLite, or the environment. [[src:github-com-tyevans-research-team-blob-main-docs-design-architecture-md-a0edb5a8]]
- The dependency rule is asserted, not just documented: a test parses every module and fails if a layer imports outward, if the domain or application layer names a framework, or if anything but the entrypoint imports the composition root. [[src:github-com-tyevans-research-team-blob-main-docs-design-architecture-md-a0edb5a8]]

## Skills

- Read and interpret a knowledge graph projection: identify entities, relationships, and the evidence (stated relationship, co-mention, semantic edge) that placed each connection.
- Distinguish between a command and an event, and explain why a rejected command leaves no trace while an event is written down forever.
- Explain the fold-vs-projection tradeoff: what a fold buys (cannot be stale, retroactive bug fixes) and what it costs (linear time), and what a projection buys (speed) and what it costs (a failure mode a fold does not have).
- Apply the gating model to a new tool: determine whether it is read-only or write, and if write, which level (`auto`, `ask`, `deny`) is appropriate and why.
- Trace how a learning area is derived from the graph: identify the entities in the cluster, the evidence that connected them, and the dependency relationships that ordered the area in the path.
- Explain why a project reopened years later reproduces the same graph without depending on a live model call, and what that implies about where extraction happens and where the result is stored.
- Identify the boundary of the process: what content leaves the process when `remember` is called, when `AGENT_GRAPH_STORE=neo4j` is set, and when embeddings are on.
