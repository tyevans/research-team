# research-team console

The web front end, as a standalone application. It talks to the Python server
over `/api` and knows nothing else about it.

```bash
npm install
npm run dev      # http://localhost:5173, proxying /api to 127.0.0.1:8000
npm run verify   # everything CI runs, in CI's order
```

`npm run dev` expects the API server to be up (`uv run web.py` in the repo
root). Point it somewhere else with `RT_API_URL`.

### Which Node

`.nvmrc` names a full version, and `nvm use` before touching the lockfile is
not optional. The version there is the one CI runs, so the npm that writes
`package-lock.json` is the npm that reads it.

It said `24` once, which resolved to whatever the runner had newest. A machine
a few minor versions behind wrote a lockfile CI's npm rejected, and the
rejection came from `npm ci` — before any check ran, so the frontend gates were
skipped rather than failed. The pull request looked green.

The cost is a deliberate commit each time Node moves, and it is the intended
cost: bumping the pin is the moment to regenerate the lockfile with the new npm
and see the result before it is anyone else's problem. There is no `engines`
field to go with it — an exact version there would turn every bump into a hard
stop for whoever is mid-change, which buys strictness by making the pin
expensive to move, and a pin nobody moves goes stale.

## The pipeline

`npm run verify` is the whole gate, and `.github/workflows/ci.yml` runs the same
list as separate steps — separate only so a red box in a pull request names what
broke without anyone opening the log. If `verify` passes locally, CI passes.

| step   | command                        | what it is for                                                                                                                                                                         |
| ------ | ------------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| format | `npm run format:check`         | Prettier owns formatting outright; ESLint's opinions about it are switched off in `eslint.config.js` so the two can never disagree. `npm run format` fixes.                            |
| lint   | `npm run lint`                 | The layer boundaries, mainly. `no-restricted-imports` is the load-bearing rule: the domain may not import a framework or an outer layer.                                               |
| types  | `npm run typecheck`            | Two configs. `tsconfig.json` is the browser's and cannot see `node` types, which is what stops application code reaching for `process`; `tsconfig.node.json` covers the build tooling. |
| tests  | `npm run test:coverage`        | Two vitest projects — `app` in jsdom, `build` in Node — with coverage floors per layer.                                                                                                |
| build  | `npm run build`                | Into `../research_team/interfaces/web/static`.                                                                                                                                         |
| size   | `npm run size`                 | The bundle budget.                                                                                                                                                                     |
| audit  | `npm audit --audit-level=high` | Runs in CI. Dependabot raises the fixes.                                                                                                                                               |

Note that `npm run build` no longer type-checks on its own — `verify` sequences
the two, and having `build` do it as well meant paying for it twice.

### Why the build output is committed

It lands in the directory the Python server already mounts at `/static`, so
`uv run web.py` serves the console with no Node toolchain anywhere in the
picture. Requiring one to run the web UI would be a regression.

The cost is that the committed copy can go stale, so CI rebuilds and fails if
the result differs from what the commit carries. Rebuild and commit with any
change under `src/`. Two consequences follow from output being in the history:

- **The bundle is split by how often each part moves** (`manualChunks` in
  `vite.config.ts`), not by what it does. Unsplit, editing one component
  rewrites 460 kB of the diff; split, a dependency-free change touches only
  `app-*.js`.
- **`build.target` and `sourcemap` are stated rather than inherited.** A
  toolchain upgrade should not silently change the syntax level of a file
  already committed, and a source map would add two megabytes to the history
  per change for a debugging aid the dev server provides for free.

### The bundle budget

`scripts/check-size.mjs` fails the build when a chunk crosses its gzipped limit,
and — just as importantly — when a chunk appears that no budget covers. A
dependency never announces that it cost 300 kB; it announces that it solved a
problem, and the cost shows up months later as a console that takes a second to
paint. Raising a limit is a legitimate change. Raising it in the same commit
that consumed it, with no note about what was bought, is what this catches.

### Coverage floors

Ratchets, not targets: each sits just under what the suite reaches today, so the
gate catches a layer losing its tests or a module arriving without any. They
differ by layer because one number would be either a lie about the domain or an
impossible bar for the views — the domain is held near total, and the
presentation layer's floor is low and _visible_ rather than absent, which is the
honest way to carry that debt.

### Two configs, one fact

The path aliases are declared twice, for `tsc` and for Vite, because the two
read different files. `scripts/build-config.test.ts` asserts the two agree —
drift there is quiet and unpleasant, since code type-checks and lints and then
fails at run time with a bare import error.

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
