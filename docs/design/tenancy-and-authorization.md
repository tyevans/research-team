# Tenancy and authorization (W-B)

Status: design, written 2026-08-29. Implementation has not started. W-A
(identity) and W-C0 (settings) are the branches this builds on; neither is
merged to `main` at the time of writing, and every symbol quoted from them
below is quoted from their branch, not from `main`.

This document decides the questions the master plan left open, and argues the
ones where the master plan's own answer turns out to be wrong. Two of them
are. Read `docs/plans/user-system-master-plan.md` first; read the sections
below in order, because each decision constrains the next.

---

## 0. Two corrections to the master plan

The plan says two things that the code does not support. Both are stated here
first, because the rest of this document is built on the corrected version and
a reader who skips this will think the design ignores its brief.

**"The tenant id is a column on every read model row."** It does not need to
be, and should not be. Measured on 2026-08-29 by parsing the read-model
declarations: of the 22 `ReadModel` subclasses in
`infrastructure/persistence/read_models.py`, **21 already carry `project_id`**.
The three declared elsewhere (`TopicRow` and `CorpusFactsRow` in
`persistence/topics.py`, `InteractionEventRow` in `persistence/interaction_log.py`)
carry it too. The single exception is `ArtRow`, and its docstring says it is a
global library on purpose. So the data is already tenant-scoped through one
edge that does not exist yet: **project to tenant**. Adding a second, redundant
scoping column to 24 tables buys nothing and creates a class of bug that a
single edge cannot have -- a row whose `tenant_id` and whose project's
`tenant_id` disagree. Section 2 does it with one new column on one new row type.

**"Relationship-based (a Zanzibar-shaped tuple store), because the interesting
question here is 'can this user read this project' through group and tenant
inheritance, and that is a graph walk, not a column lookup."** The inheritance
described is two levels deep and has one edge per level. That is not a graph
walk; it is two indexed reads, and one of them is usually cached in the cookie
already. Section 3 makes the case against the tuple store and states, in
advance, the three changes to the product that would reverse it.

---

## 1. What a tenant is

**A tenant is a Zitadel organisation, mirrored locally as a row.** Zitadel is
the system of record for who belongs to an organisation, exactly as W-A's
`domain/user.py` makes it the system of record for who a person is. This
project mirrors enough to answer authorization without a network hop, and
nothing more.

`UserSignedIn.tenant_id` already exists and is already a `str` rather than a
`UUID`, because Zitadel org ids are snowflake-shaped decimal strings. That
choice was made in W-A specifically so this work would have something to key
on. Keep it: **a tenant id is a string everywhere in this repository.** Do not
convert it to a UUID at any boundary. A tenant whose id is not a Zitadel org id
does not exist.

### Personal tenants

**Every person gets a personal tenant, created on first sign-in.** Zitadel
creates an organisation for a self-registered user; if the deployment's Zitadel
does not, the sign-in path creates one through the management API before the
first `UserSignedIn` is appended. Either way, by the time a session cookie
exists, the subject in it belongs to at least one organisation.

The alternative -- a null tenant for a personal account -- was rejected. It
makes `tenant_id` optional on `ProjectRow`, which makes every authorization
check carry a branch for the case where there is nothing to check against, and
that branch is the one nobody writes a test for. A personal tenant costs one
row and removes an entire failure mode.

The personal tenant is not marked as personal in the schema. `TenantRow` has a
`kind` column with values `personal` and `shared`, and it is **display only**:
the onboarding copy in section 7 needs it, and nothing in the permission check
reads it. Stated because a `kind` column beside a permission system invites a
special case, and the special case is what turns a two-row check into a policy.

### Belonging to several tenants

A user may belong to several. The mechanism is already half-built and the
half that exists is the dangerous half.

W-A's session cookie carries `tid`, and `Principal.tenant_id` reads it. **That
value is the person's *active* tenant and must never be an input to a
permission decision.** It scopes listing -- which projects appear in the
sidebar -- and nothing else. Every check resolves the tenant of the *resource*
(the project's `tenant_id`), then asks whether this subject has a role in that
tenant. A cookie is a thing the holder controls the lifetime of; if a stale
`tid` could grant access, then a user removed from an organisation would keep
their access until their cookie expired, which is the failure that makes
"remove member" a lie.

So: `POST /api/tenants/{tenant_id}/activate` re-mints the cookie after checking
membership, and `Principal.tenant_id` is read by exactly two things -- the
project list and the console's tenant switcher. A test asserts the second half:
`test_a_cookie_naming_a_tenant_the_person_left_grants_nothing`, which signs in,
removes the membership without touching the cookie, and expects 404 on a
project the cookie's `tid` still names.

---

## 2. How tenancy reaches the data

One edge: **a project belongs to exactly one tenant.** Everything else is
already project-scoped, so everything else inherits.

### The event change

`ProjectCreated` gains `tenant_id: str`, required, no default.

This is a **breaking change to stored payloads** under the pre-release rule.
A `ProjectCreated` written before this field existed no longer loads. There is
no validator to translate one, because there is nothing to translate it *to*: a
default would have to invent a tenant, and a project silently assigned to a
tenant nobody chose is worse than a project that refuses to load. This follows
the precedent of `SessionStarted.project_id` and `SessionStarted.purpose`
exactly, including the obligation to say so in the field's docstring.

`tests/infrastructure/test_schema_evolution.py` gets a case that **asserts the
refusal** -- writes a `ProjectCreated` payload with no `tenant_id` straight into
the events table and expects the read to raise. Do not delete the existing
case; a deleted case is indistinguishable from a case nobody wrote.

`CreateProject` gains the same field. `POST /api/projects` supplies it from the
principal's active tenant.

### The new read model

Projects are currently not projected at all. `SessionService.list_projects()`
folds `read_category` over every `Project` stream on every request. That is the
shape `architecture.md` describes replacing for sessions, and it is the reason
project listing cannot be filtered by tenant without loading every project in
the installation first.

Add `ProjectRow` and `ProjectProjection` in
`infrastructure/persistence/read_models.py`, following `SessionSummaryRow`:

| column | source |
| --- | --- |
| `id` | the project id (the aggregate id) |
| `tenant_id` | `ProjectCreated.tenant_id` |
| `name` | `ProjectCreated.name` |
| `created_by` | `ProjectCreated.created_by`, the Zitadel subject, `""` when auth is off |
| `deleted` | set by `ProjectDeleted` |

`list_projects` reads this table with a `tenant_id` filter. The fold in
`session_service.py` stays as the definition, and a test feeds identical events
through both, following the `summaries.py` precedent.

`ProjectCreated.created_by` is a second new field on the same event, added in
the same breaking change. It is the "who owns this" that section 4's
`project.owner` role is seeded from, and adding it later would be a second
breaking change for one string.

### Membership tables

Three new read models, in a new module
`infrastructure/persistence/tenants.py` rather than in `read_models.py`. That
file is 5,123 lines; a fourth workstream editing it concurrently is a merge
nobody wins.

- `TenantRow` -- `id` (the Zitadel org id), `name`, `kind`, `created_at`.
- `MembershipRow` -- `tenant_id`, `subject`, `role`, `granted_at`, `granted_by`.
  Row id is `uuid5(TENANT_NAMESPACE, f"{tenant_id}:{subject}")`, derived for the
  reason every other derived id here is derived: a second grant to the same
  person must replace the first, not accumulate.
- `ProjectGrantRow` -- `project_id`, `subject`, `role`, `granted_at`,
  `granted_by`. Row id `uuid5(TENANT_NAMESPACE, f"{project_id}:{subject}")`.
  This is the per-project share described in section 7, and it is what makes a
  tenant member a `viewer` on one project and an `editor` on another.
- `InvitationRow` -- `tenant_id`, `email`, `role`, `token`, `invited_by`,
  `created_at`, `accepted_at`, `revoked_at`.

All four are fed by a projection over the events in section 7, so `/rebuild`
re-derives them. Membership is not settings: who is in an organisation is
exactly the kind of fact whose history is the point, so W-C0's
"a store with no projection" argument does not carry over.

### Verifying it

CLAUDE.md's read-models rule applies with full force and the incident it
describes is *this exact change*: `apply_schema`'s docstring names
"adding `project_id` to `SessionSummaryRow`" as the thing that broke every
existing database. Adding `tenant_id` to a *new* table does not repeat it, but
`ProjectRow` will be created empty on a database whose log is full, and the
projection resumes from the checkpoint rather than replaying -- so **every
project that existed before this branch is invisible until `/rebuild`**.

That is acceptable and must be stated in the release note, not discovered. The
verification obligation is concrete: run the branch against a copy of
`~/.research-team/sessions.db` made with
`uv run python -m research_team.infrastructure.persistence.local_copy`, confirm
`/api/projects` is empty, run `/rebuild`, confirm it is not. A fresh database
proves nothing here.

### The naming hazard, stated once and loudly

**`tenant_id` already means "project id" in this repository.** It is redstring's
vocabulary: `domain/project.py`'s module docstring says "the project id is also
redstring's `tenant_id`", and the name appears 87 times, almost all of them
inside `infrastructure/knowledge/` and in projection handlers that read
`event.tenant_id` off a redstring event.

The decision: **the new concept takes the name `tenant_id`, and redstring's
keeps it too, confined to `infrastructure/knowledge/` and to the redstring
event handlers in `read_models.py`.** Renaming redstring's is not available --
it is a library parameter name. Renaming ours is available but wrong: W-A
already wrote `UserSignedIn.tenant_id` meaning an organisation, and Zitadel,
the docs, and every future reader mean an organisation by it.

What makes this survivable rather than merely tolerable is that the two never
appear in the same function. The mitigation is mechanical and belongs in slice
B2: at every call into redstring, the argument is written as
`tenant_id=project_id` -- never `tenant_id=tenant_id`, never positionally --
so the seam is visible at the call site. `composition.py:2174` already does
this (`tenant_id=target_project_id`). A grep for `tenant_id=tenant_id` should
return nothing, and a test asserts it does.

---

## 3. Zanzibar: no

**Decision: a role table, not a tuple store.** Write the checker; embed
nothing.

### What the real access patterns are

Enumerated from the 118 routes in `app.py` (measured, not estimated):

- **80** are under `/api/projects/{project_id}/...` (38 GET, 38 POST, 3 DELETE, 1 PATCH). Every one of them
  authorizes against exactly one project.
- **20** are under `/api/sessions/...` (11 GET, 9 POST). A session belongs to
  exactly one project (`SessionStarted.project_id`, required), so these
  authorize against one project after one lookup that `SessionSummaryRow`
  already answers.
- **6** are `/api/interactions/...` -- the interaction log, a separate event
  store (CLAUDE.md, "The interaction log"). These are tenant-scoped, not
  project-scoped.
- **12** are the rest: `/api/projects` (list and create), `/api/tree`,
  `/api/health`, `/api/workers`, `/api/autonomy`, `/api/stream`,
  `/api/summaries/rebuild`, `/api/corpus/rebuild`, `/api/art/{art_id}.svg`,
  and two `/` handlers.

So the object graph is: **tenant, project, session**, where session-to-project
is a required field and project-to-tenant is the edge section 2 adds. Depth
two. No groups. No object nesting. No course-level or lesson-level sharing --
a course belongs to a project (`CourseRow.project_id`) and is reachable exactly
when the project is.

### What Zanzibar earns its complexity on

A relationship-tuple store with a check API pays for itself when at least one
of these is true:

1. **Permissions inherit through nested objects of arbitrary depth** -- folder
   in folder in folder, document in the innermost. Here the depth is fixed at
   two and known at compile time.
2. **Groups, and groups in groups.** A tuple store's real power is that
   `group:eng#member` can itself be a member of `group:all`, and the checker
   does not care how deep that goes. This project has no groups. Zitadel does,
   and if group-based access is ever wanted, the honest first move is to read
   Zitadel's groups, not to build a second group system here.
3. **"Who can see this?" answered in reverse, at scale.** Zanzibar's expand and
   reverse-index APIs exist because Google needed to enumerate the readers of
   an object across billions of tuples. Here, the readers of a project are one
   `SELECT` on `project_grants` plus one on `memberships`.
4. **Several services asking the same authorization question consistently.**
   Zookies exist to solve a distributed-cache staleness problem. This is one
   process over one SQLite file, with an in-process lock (`architecture.md`,
   "Concurrency, and its one limit"). There is no second reader to be
   inconsistent with.

None applies. The tuple store would be a general graph engine over a graph with
two edges.

### What it would cost

Concretely, and this is the part that decides it: a tuple store is a schema
language, a tuple table, a rewrite-rule evaluator, a check API, a cache with an
invalidation story, and a set of tests for the evaluator that are about the
evaluator rather than about this product's rules. Embedding one (openfga's
Python SDK, or SpiceDB) adds a service to `docker-compose.auth.yml` and a
network hop inside every request, on a project whose stated concurrency model
is one process. Writing one means writing a graph engine.

Against that, the role table's checker is roughly this, and this is the whole
of it:

```
resolve(subject, project) ->
    grant = project_grants[(project.id, subject)]      # one indexed read
    member = memberships[(project.tenant_id, subject)] # one indexed read
    return max(role_of(grant), implied_role_of(member))
```

### The shape that keeps the door open

The rejection is of the *machinery*, not of the model. Store grants in a shape
a tuple store could ingest without a data migration:

```
(subject, relation, object_type, object_id)
```

`MembershipRow` is `(subject, role, "tenant", tenant_id)` with the columns named
`subject`/`role`/`tenant_id`; `ProjectGrantRow` is the same over `project`. The
`Authorizer` port in `application/authorization.py` takes
`(principal, permission, resource)` and returns a bool, with **one production
implementation**. Every route depends on the port. Swapping in a tuple-backed
checker later is a new adapter and a wiring change, not 118 edits.

Note the trap this walks into, and the test that answers it: CLAUDE.md's
"A port with one adapter and no test between them is two things that were
never checked against each other" is precisely this shape. The obligation is a
test that drives the real membership writer and the real checker over one
database -- grant a role through the sharing API, then assert the route it
should unlock actually unlocks. A stubbed `Authorizer` in the route tests plus
a unit test of the checker proves neither half meets the other.

### What reverses this decision

Written down so the reversal is a decision rather than a drift. Any one of:

- **Teams or groups inside a tenant** -- "the curriculum team can edit every
  course project". The `max(grant, member)` resolution above gains a third
  source and then a fourth, and that is the slope.
- **Sharing below a project** -- publishing one course, or one learning path,
  to people who cannot see the project it came from. This is plausible: the
  catalog is already a public-feeling surface. It adds a third object level and
  a resource whose parent is not its authorization root.
- **A second process or a second service** reading the same permissions.

Two of the three are product decisions nobody has made. If the first or second
lands, revisit before building around it.

---

## 4. Roles and the permission matrix

Two role ladders, one per object type, and a resolution rule between them.

### Tenant roles

| role | means |
| --- | --- |
| `owner` | the organisation. Can transfer ownership, remove admins, delete the tenant. Exactly one per tenant. |
| `admin` | manages people and tenant settings. Implicit `project.owner` on every project in the tenant. |
| `member` | can create projects. Implicit `project.viewer` on nothing -- see below. |
| `guest` | can be granted individual projects and nothing else. Cannot create a project. |

**A `member` gets no implicit access to other members' projects.** This is the
non-obvious one and it is worth the argument. The tempting default is that
everyone in an organisation can read everything in it, and it is what most
small-team tools do. It is wrong here because a project is not a document: it
carries a knowledge graph, a corpus of fetched sources, and model spend. A
tenant that grows past a handful of people gets a sidebar listing every
project anyone ever started, and the fix at that point is a permission change
that takes access away from people who had it, which is the change nobody
wants to make. Starting closed and adding a per-project "visible to the whole
organisation" flag later is the reversible direction.

`admin` *is* implicit owner on every project, because an organisation needs
somebody who can reach a project whose creator left.

### Project roles

| role | means |
| --- | --- |
| `owner` | everything, including delete and share. Seeded from `ProjectCreated.created_by`. |
| `editor` | everything except delete, share, and transfer. |
| `runner` | read, plus the verbs that spend money. |
| `viewer` | read only. |

### Permissions, against the real verbs

The verbs are derived from the 118 routes, not invented.

| permission | routes it covers | roles |
| --- | --- | --- |
| `project.read` | the 38 `GET`s under `{project_id}`: catalog, curriculum, graph, sources, topics, timeline, ontology, asks, dialogues | viewer, runner, editor, owner |
| `project.write` | source add/drop/restore/patch, topic status and sub-questions, media proposal accept/reject/ignore, catalog feature/unfeature/abandon, blurbs | editor, owner |
| `project.run` | `sources/extract`, `sources/reindex`, `sources/{id}/perceive`, `embeddings`, `curriculum/author`, `catalog/{slug}/realize`, `catalog/art`, `art/reroll`, `dispatch`, `dispatch/bulk`, `topics/seed`, `ask`, `dialogues` | runner, editor, owner |
| `project.admin` | `DELETE /api/projects/{id}`, all of the sharing API | owner |
| `session.read` | the 11 `GET`s under `/api/sessions` | inherited from the session's project's `project.read` |
| `session.write` | turns, forks, cancel, autonomy, approvals, release, checklist | inherited from `project.run` |
| `tenant.read` | list members, read tenant settings | member, guest (self only), admin, owner |
| `tenant.admin` | invite, change role, remove, tenant settings write | admin, owner |
| `tenant.own` | transfer ownership, delete tenant | owner |
| `instance.admin` | `/api/summaries/rebuild`, `/api/corpus/rebuild`, `/api/health`, `/api/workers` | see below |

**`project.run` exists as a separate verb from `project.write`, and that is the
one split that is not obvious.** Justification: extraction, authoring, ask and
dialogue turns all call a model, and the model credentials are the tenant's
(W-C0 stores provider keys at tenant scope). A `viewer` who can start a
course-authoring run over a large topic spends somebody else's money, and does
it through a route whose name (`POST .../curriculum/author`) reads like an
ordinary write. Splitting the verb makes the spend visible in the matrix rather
than in a bill. The `runner` role exists so the split is usable -- a person who
should be able to run extraction but not edit the corpus is a real role in a
research group.

**`instance.admin` is not a role in any tenant.** `/api/summaries/rebuild`,
`/api/corpus/rebuild` and `/api/workers` act on the whole installation, across
every tenant. Making them a tenant role would be a lie: a tenant `owner`
rebuilding the corpus rebuilds everyone's. They are gated on a setting --
`AGENT_ADMIN_SUBJECTS`, a list of Zitadel subjects -- resolved through W-C0's
resolver at environment scope only, since it must not be settable from inside
a tenant. With auth off, everyone is an instance admin, which is what a local
single-user install is.

Note for whoever implements this: scouted-backlog item 11 found that
`POST /api/corpus/rebuild` and `POST /api/projects/{id}/sources/reindex` have
no frontend caller. That item asks whether they are operator surfaces or dead
code, and asks for the answer **before** this branch starts. If they survive,
`corpus/rebuild` is `instance.admin` and `sources/reindex` is `project.run`.

### The cross-tenant routes

`/api/tree` and `/api/stream` are the two that do not fit. `/api/tree` returns
projects and their sessions for the whole installation; `/api/stream` is the
SSE feed over the whole event log. Both must be filtered, not gated: a signed-in
person gets their own tenant's slice. For `/api/stream` this means the feed's
per-frame filter needs the project id, which `graph_change(item.event.tenant_id, ...)`
at `app.py:5992` already has -- that `tenant_id` is redstring's, meaning the
project. Filtering it against the principal's visible project set is a lookup
per frame against a set held for the connection's lifetime, refreshed when a
membership event lands. Say plainly what that costs: a person removed from a
project mid-stream keeps receiving its frames until the refresh. Bound the
refresh at 30 seconds and write the bound down.

---

## 5. How the check reaches 118 routes

### The mechanism: a dependency, not middleware, not a decorator

**Decision: a FastAPI dependency factory in the route signature.**

```python
@app.get("/api/projects/{project_id}/graph")
async def project_graph(project_id: UUID, _: Allowed = Requires("project.read")):
    ...
```

Middleware is not available, and for two independent reasons. The first is the
one CLAUDE.md documents: `@app.middleware("http")` is `BaseHTTPMiddleware`,
which runs the endpoint inside its own anyio task group and breaks every route
that schedules fire-and-forget work -- measured, four tests in
`test_extraction_routes.py`, with a failure that names nothing about
middleware. `_InteractionBodyCap` in `app.py` and W-A's `AuthGate` are the
worked examples of the plain-ASGI alternative.

But the plain-ASGI form does not work either, and this is the reason that
actually decides it: **a gate runs before routing, so it has no path
parameters.** It sees `/api/projects/3f2a.../graph` as a string. Deriving the
project id would mean reimplementing the route table as a set of regexes that
is free to disagree with the real one, and the disagreement is silent in the
permissive direction. W-A's `AuthGate` gets away with prefix matching because
its question ("is anyone signed in?") does not depend on which resource is
named. This question does.

A decorator was rejected for a smaller reason: it wraps the endpoint, so
FastAPI's signature introspection sees the wrapper, and the ordering between
stacked decorators becomes load-bearing and invisible. The dependency is in
the signature, where FastAPI already resolves `project_id` for it.

### `Requires`, concretely

```
Requires(permission)  ->  a Depends(...) that:
  1. reads `project_id` or `session_id` from the path params, or neither
  2. resolves the resource's tenant (ProjectRow, or SessionSummaryRow -> ProjectRow)
  3. asks the Authorizer port
  4. raises 404 or 403 per section 6
```

It lives in `interfaces/web/authz.py` beside `auth.py`. It reads the
`Authorizer` off `app.state`, the way `principal_of` reads `app.state.auth`, so
an app built without authorization wiring is not a crash.

### Catching a route that is missing its check

This is the failure that ships silently, and it is the same shape as the one
CLAUDE.md's "Checkpoints over model output" section is about: a rule enforced
by remembering is documentation, and the test is the contract.

`tests/interfaces/test_every_route_is_authorized.py`, derived by
introspection, with **four assertions**:

1. **Every `APIRoute` on the app carries exactly one authorization marker.**
   Walk `app.routes`; for each `APIRoute`, walk `route.dependant.dependencies`
   looking for the marker `Requires` attaches. Zero markers fails. Two fails
   too -- two checks on one route is either a copy-paste or a genuine
   conjunction, and a conjunction should be one named permission.
2. **...unless its path is in `PUBLIC_PATHS`,** a frozenset declared in
   `authz.py` beside the marker. `/`, `/api/health`, `/auth/*`, `/api/docs`.
3. **`PUBLIC_PATHS` contains no path the app does not serve.** This is the
   direction that is always forgotten. Without it, deleting a route leaves a
   stale exemption, and the next route that happens to be given that path is
   public by accident.
4. **A `project.*` permission appears only on a route whose path template
   contains `{project_id}`, and a `session.*` permission only on one with
   `{session_id}`.** This catches the copy-paste that gates a session route on
   a project permission the request cannot supply an id for -- which would
   otherwise resolve to "no resource named, allow", the permissive failure.

The test is parametrised over the routes so a failure names the offending
path, not a count. It is worth stating what it cannot do: it proves each route
has *a* check, not that the check is the *right* one. `project.read` on a
route that deletes something passes all four assertions. The matrix in section
4 is the only thing that catches that, and it is a review question.

The mechanical sweep across 118 routes is one slice on its own (section 8, B3),
held for as short a time as possible, and it lands while `AGENT_AUTH` is off,
so it is a runtime no-op the day it merges.

---

## 6. Default-deny, and `AGENT_AUTH=off`

### The off path

**Off means a permissive `Authorizer`, not an absent one.** The
`Requires(...)` dependency runs on every route in every configuration; what
changes is which adapter `composition.py` wires behind the port.
`PermissiveAuthorizer.check()` returns `True` on its first line and is what
`AGENT_AUTH=off` selects.

The alternative -- registering the dependency only when auth is on -- was
rejected for the reason W-A gives about `AuthGate`: it would mean the entire
existing suite of route tests exercises a code path that does not exist in
production-with-auth-on, and the first time the real dependency runs against
route 74 is in someone's browser. With a permissive adapter, every one of the
several hundred existing route tests runs the real resolution path -- path
param extraction, project lookup, port call -- and only the final bool differs.

A single-user local install with `AGENT_AUTH=off` therefore behaves exactly as
`main` does today: no sign-in, no tenant switcher, every project visible,
every route reachable, `instance.admin` granted. This is the configuration the
whole test suite and every other in-flight workstream runs in, and preserving
it byte-for-byte is the reason this branch is mergeable beside them.

`ProjectCreated.tenant_id` still has to be a real string with auth off, since
it is required. It is the constant `"local"`, defined once in
`domain/tenant.py` as `LOCAL_TENANT`, with a `TenantRow` seeded at startup so
the foreign concept is not dangling. Not `""`: an empty string is what an
uninitialised field looks like, and a bug that leaves `tenant_id` empty would
then be indistinguishable from correct local operation.

### The on path

- **Unauthenticated request to `/api/*`:** 401, from W-A's `AuthGate`, before
  routing. Unchanged by this work.
- **Authenticated, no role on the resource, read attempt:** **404.** A 403
  confirms the project exists, and project ids are UUIDs that appear in URLs
  people paste. "Does tenant X have a project" is not a question an outsider
  should be able to ask.
- **Authenticated, has read but not write:** **403.** Once a person can see a
  thing, hiding the reason they cannot change it helps nobody and produces a UI
  that cannot say why a button failed.
- **Authenticated, no tenant at all** (a subject whose org lookup failed):
  403 with a body naming the condition. Not 404: this is an installation
  problem, and a person locked out by it needs to be able to say what happened.

The rule, stated so it survives: **404 hides existence, 403 explains a
refusal, and the boundary between them is the read permission.**

### Default-deny in the checker

`Authorizer.check` returns `False` for every input it does not understand:
unknown permission string, project with no row, session with no project,
principal with no subject. This follows `FetchGrant.covers()` in
`application/grants.py`, whose docstring makes the argument -- a check that
raises on malformed input ends the request with a 500, and a 500 is a refusal
nobody can distinguish from a bug. Return "no" and let the route say so.

---

## 7. Sharing: what the API must support

Nine operations. All of them live in a new module,
`interfaces/web/tenants.py`, mounted with one `include_router` line in
`create_app` -- the pattern `export.py` and W-C0's `settings.py` already
establish, and the reason is contention: it keeps this feature's ~400 lines of
routes out of the 6,000-line file.

| route | permission | notes |
| --- | --- | --- |
| `GET /api/tenants` | authenticated | the caller's own memberships |
| `POST /api/tenants/{id}/activate` | membership in `{id}` | re-mints the cookie's `tid` |
| `GET /api/tenants/{id}/members` | `tenant.read` | |
| `POST /api/tenants/{id}/invitations` | `tenant.admin` | by email; see below |
| `GET /api/tenants/{id}/invitations` | `tenant.admin` | |
| `DELETE /api/tenants/{id}/invitations/{iid}` | `tenant.admin` | revoke |
| `POST /api/invitations/{token}/accept` | authenticated | the invitee, not the inviter |
| `PATCH /api/tenants/{id}/members/{subject}` | `tenant.admin` | change role |
| `DELETE /api/tenants/{id}/members/{subject}` | `tenant.admin`, or self | remove, or leave |
| `POST /api/tenants/{id}/transfer` | `tenant.own` | to an existing admin |
| `GET/PUT/DELETE /api/projects/{id}/grants` | `project.admin` | per-project share |

### Invite by email, against an IdP-backed identity

The hard case: the invitee may have no account. So an invitation is keyed by
**email**, not by subject, and is claimed at sign-in.

The claim rule: on `UserSignedIn`, look for open invitations matching the
token's `email` claim, **only when `email_verified` is true**. That condition
is load-bearing and must be a named test. Without it, anyone who can register
an account claiming an address they do not control can accept an invitation
sent to that address, and Zitadel's own verification is the only thing that
makes the email a meaningful identifier. If the deployment's Zitadel does not
issue `email_verified`, invitations by email must not be enabled -- fail loudly
at startup rather than quietly accepting an unverified match.

The token in the invitation URL is a second, independent path: it is a random
128-bit value, single-use, expiring in seven days, and accepting through it
does not consult the email claim at all. Both paths exist because they fail
differently -- the token covers "invited at an address they sign in with a
different one", and the email match covers "lost the link".

### Ownership transfer

Transfer requires the target to already be an `admin` of the tenant. This is a
guard rail rather than a permission model: transferring to an arbitrary subject
string is a typo away from handing an organisation to nobody, and there is no
undo. Two events -- `OwnershipTransferred` carries both subjects -- so the log
answers "who was owner on date D" without a fold over role changes.

### Settings-change attribution

W-C0 deferred the audit trail to this branch, explicitly, and named the reason:
an audit event written before there is an identity to attribute it to records
`None` for the only field anybody would query. There is an identity now.

Add `SettingChanged` and `SettingCleared` to a new `Settings` aggregate stream:

```
SettingChanged: scope, scope_id, setting_key, actor_subject, changed_at, was_secret
SettingCleared: scope, scope_id, setting_key, actor_subject, cleared_at
```

**The value is not on the event.** For a secret this is obvious. For an
ordinary setting it is a judgement: a log that records old and new values is a
better audit trail and is also a permanent, unrewritable copy of every model
endpoint URL and every chunk-size experiment anyone ever ran, in a store whose
whole design principle is that it is never rewritten. `was_secret` plus the
current value in `setting_overrides` answers "what is it now and who last
touched it", which is the question the deferral named. "What was it before" is
not answerable, and that is written down here rather than discovered later.

`SettingsStore.put` and `.clear` gain an `actor` parameter. With auth off the
actor is `LOCAL_SUBJECT`, for the same reason `tenant_id` is `"local"` rather
than empty. The store keeps its no-projection design -- these events are an
append beside it, not a replacement for it, and `store.py`'s docstring should
be updated to say the audit exists rather than that it is deferred.

### Console surfaces

Frontend work, listed for completeness and owned by this workstream:

- A tenant switcher in the account menu, reading `GET /api/tenants`.
- A members page: list, role dropdown, remove, invite form, pending invitations.
- **The onboarding copy** -- scouted-backlog item 20, which flags this as W-B's
  because the right copy depends on decisions made here. It now has them. Three
  distinct empty states, where `FirstRun` in
  `frontend/src/presentation/tree/TreeView.tsx:126-152` renders one:
  1. New personal tenant, no projects: today's copy, unchanged.
  2. New member of a shared tenant, no visible projects: "Nobody has shared a
     project with you yet" plus the admin's name, **not** "+ New project" as the
     primary action. Section 4's decision that a `member` sees nothing by
     default is what makes this state common rather than rare, which is exactly
     why the copy matters.
  3. `guest`: the same, without the "+ New project" affordance at all, since
     the route would 403.

---

## 8. Implementation slices

Six, ordered, each independently mergeable, each leaving the system working.
The ordering is driven by `app.py` contention: it is 6,037 lines and the most
contended file in the tree, so exactly one slice holds it for long.

### B1 -- The domain, the store, the checker. No routes.

`domain/tenant.py` (the tenant and membership events, `LOCAL_TENANT`,
`LOCAL_SUBJECT`), `infrastructure/persistence/tenants.py` (four read models and
their projection), `application/authorization.py` (the `Authorizer` port, the
permission catalogue, the role matrix, `RoleTableAuthorizer` and
`PermissiveAuthorizer`), `composition.py` (wiring, ~30 lines).

Touches `app.py`: **zero lines**. Nothing calls the checker yet; the system is
byte-identical at runtime. The port-and-one-adapter test from section 3 is
written here and is the slice's main deliverable alongside the code.

### B2 -- Projects get a tenant.

`domain/project.py` (`ProjectCreated.tenant_id` and `.created_by`, both
required and both documented as breaking), `read_models.py` (`ProjectRow`,
`ProjectProjection`), `application/session_service.py` (`list_projects` reads
the row), `tests/infrastructure/test_schema_evolution.py` (the refusal case),
and the `tenant_id=project_id` seam sweep from section 2.

Touches `app.py`: **2 routes** (`GET`/`POST /api/projects`). Small.

This is the slice whose verification obligation is real: it must be run against
a copy of the real database, per section 2. Do not merge it on a green suite
alone.

### B3 -- The sweep.

`interfaces/web/authz.py` (`Requires`, `PUBLIC_PATHS`), the four-assertion
coverage test, and the marker on all 118 routes.

Touches `app.py`: **every route**. This is the contended slice, and the
discipline is that it contains *nothing else* -- no new routes, no logic
changes, no refactors that happen to be nearby. One mechanical pass, reviewed
against the matrix in section 4, merged the day it is opened. Runtime no-op,
because `AGENT_AUTH` is still off and `PermissiveAuthorizer` is still wired.

Coordinate with scouted-backlog item 11 (the three uncalled routes): resolve it
**before** this slice starts or **after** it merges, never during. A deletion
against this diff is a near-certain conflict.

### B4 -- Membership, sharing, and the settings audit.

`interfaces/web/tenants.py` (all of section 7's routes), the invitation claim
in W-A's sign-in path, `SettingChanged`/`SettingCleared` and the `actor`
parameter on `SettingsStore`.

Touches `app.py`: **one `include_router` line.**

### B5 -- The console.

Tenant switcher, members page, the three onboarding states. Frontend only. Runs
in parallel with B4 once B4's API shape is agreed, which is what section 7's
table is for.

### B6 -- Flip the default.

`composition.py` selects `RoleTableAuthorizer` when `AGENT_AUTH` is on;
personal-tenant bootstrap on first sign-in; the 404-versus-403 behaviour; the
`/api/tree` and `/api/stream` filters from section 4.

Touches `app.py`: the two filtered routes. Small.

This is the first slice where anything is denied, and it is last on purpose:
by the time it lands, the marker is on every route, the checker has been in
production answering "yes" for weeks, and the only new thing is which adapter
is wired. If it goes wrong, the revert is one line in `composition.py`.

---

## 9. What this design does not do

Named so nobody has to work out whether the omission was deliberate.

- **No groups or teams.** Section 3 explains why, and names them as the first
  trigger to revisit the tuple-store decision.
- **No sharing below a project.** No published course, no public catalog link.
  This is the second trigger, and it is the one most likely to be wanted.
- **No sign-out that survives a restart.** W-A's `SessionStore` is a
  process-local revocation set and says so. Removing a member does not
  invalidate their live cookie; it stops the cookie from granting anything,
  which section 1 makes true and which is the property that matters.
- **No audit of reads.** `SettingChanged` records writes. Who looked at what is
  not recorded anywhere, and the interaction log (a separate event store, which
  no projection can span -- CLAUDE.md, "The interaction log") is the nearest
  thing to it.
- **No per-tenant database.** One SQLite file, one process, one lock. Row-level
  tenancy over a shared store is the model, and the concurrency limit in
  `architecture.md` applies unchanged.
- **No rate limiting or spend caps per tenant.** `project.run` makes the spend
  *authorizable*; it does not make it *bounded*. `FetchGrant` bounds network
  fetches within a run and is the nearest precedent for what a spend cap would
  look like.
