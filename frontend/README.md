# research-team console

The web front end, as a standalone application. It talks to the Python server
over `/api` and knows nothing else about it.

```bash
npm install
npm run dev      # http://localhost:5173, proxying /api to 127.0.0.1:8000
npm run build    # → ../research_team/interfaces/web/static
npm test
npm run lint
npm run typecheck
```

`npm run dev` expects the API server to be up (`uv run web.py` in the repo
root). Point it somewhere else with `RT_API_URL`.

The build lands in the directory the Python server already mounts at `/static`,
so `uv run web.py` serves the built console with no extra step — and the built
assets are committed for exactly that reason. Rebuild and commit them with any
change under `src/`.

## Layers

Dependencies point inwards only. Each layer may import from the ones above it in
this list and never from the ones below.

```
domain/          pure model. no framework, no I/O, no browser
  ├── session/       the event log, scrub points, the turn lifecycle
  ├── conversation/  messages, tool runs, the transcript
  ├── workspace/     files and revisions
  ├── lesson/        parsed documents, widgets, attempts
  ├── project/       projects, workflows, the course
  ├── research/      autonomous runs and how they end
  ├── activity/      provisional content from a running turn
  └── shared/        identifiers, file paths

application/     use cases and the ports they need
  ├── ports/         interfaces, stated in domain terms
  ├── session/       the session aggregate's store
  ├── lesson/        attempt state
  └── queries/       cache keys

infrastructure/  adapters implementing the ports
  ├── http/          fetch client, DTO schemas, and the mappers between
  ├── sse/           the live feed
  ├── storage/       localStorage
  └── rendering/     markdown and diff, over libraries

presentation/    React. reads domain types, calls ports through the container
app/             the composition root: the only place adapters are named
```

`eslint.config.js` enforces the two boundaries that matter: the domain may not
import a framework or an outer layer, and the application may not import the UI.

## Where the difficult parts live

Three pieces carry most of the subtlety, and each is documented at length in its
own file rather than summarised here:

- **`domain/session/turn-end-ledger.ts`** — why a `running: true` answer from
  the server is not always believed. The backend clears its current-turn tracker
  and emits the turn-end event in two steps, so a GET can describe a turn this
  connection already watched end.

- **`application/session/session-store.ts`** — the whole session view as one
  aggregate: a turn that may be running in another tab, provisional content that
  may never be recorded, a cancel that may not have settled, and a stream whose
  frames arrive on three channels with two different replay guarantees.

- **`infrastructure/http/mappers.ts`** — the anti-corruption layer. Wire shapes
  in, domain objects out. It is the only module allowed to know that the server
  spells it `knowledge_attached`.

## What the browser is not allowed to do

- **It cannot grade an answer.** The learner projection strips the answer key
  server-side. `Verdict` has no constructor from a score, so the type itself
  refuses to let a renderer invent one.
- **It cannot turn model output into markup.** `dangerouslySetInnerHTML` appears
  once, in `presentation/common/content.tsx`, and is fed only by
  `infrastructure/rendering/markdown.ts`, which sanitises with a closed
  allow-list and strips every href that is not `http(s)` or `mailto`.
