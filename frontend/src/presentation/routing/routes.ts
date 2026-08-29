import { EventIndex, isEventIndex } from '@domain/session/event-index.ts'
import { ScrubPoint } from '@domain/session/scrub-point.ts'
import { FilePath } from '@domain/shared/file-path.ts'
import { ProjectId, SessionId } from '@domain/shared/identifier.ts'
import { isScope, type Scope } from '@domain/settings/spec.ts'

/** The console's routes, as values rather than as strings.
 *
 * Every route here is a *linkable state*, which is the point: a scrub position
 * and an open file are in the URL so a reader can send somebody the exact thing
 * they are looking at. `#/s/<id>/at/12` and `#/s/<id>/file/<path>` are both
 * bookmarks, not click-only states.
 *
 * Hash-based because the backend serves one static file and knows nothing about
 * client paths — a history route would 404 on reload.
 *
 * There are three routes, not four, and the change is deliberate. `course` and
 * `research` were two nouns naming two *pages*; a project is one place, and the
 * thing that varies is which of its parts you are looking at. So one project
 * route carries a `Selection`, and the pages become a rendering decision rather
 * than a routing one. The cost is that `#/p/<id>` alone no longer says which
 * page you meant, and `App.tsx` has to choose — that choice is temporary and
 * goes away when the two views merge.
 */
export type Route =
  /** The landing page. Named for what it shows -- projects, with their
   *  sessions inside them -- rather than for the fork tree it used to lead
   *  with. The href is unchanged; only the name is honest now. */
  | { readonly name: 'home' }
  /** One session's transcript, standalone.
   *
   * Kept as a top-level route even though a session is also a `Selection` on a
   * project: a transcript is readable without knowing which project it belongs
   * to, and every link into one from outside the console (a log line, a
   * notification) has a session id and nothing else. */
  | {
      readonly name: 'session'
      readonly id: SessionId
      readonly at: ScrubPoint
      readonly path: FilePath | null
    }
  | {
      readonly name: 'project'
      readonly id: ProjectId
      /** What is selected on the project page, or null for the default.
       *
       * In the URL for the reason the scrub point is: a topic, a stage, an
       * entity or an artifact somebody navigated to is a thing worth sending,
       * and a reload that dropped it would throw away the search that found
       * it. One field rather than one per kind because the project can only
       * have one thing selected at a time -- that is not a UI convenience,
       * it is what the page is. */
      readonly selection: Selection | null
    }
  /** The interaction log's reader, with its filter state.
   *
   * A route, not a facet on the project page, and the reason is what the view
   * is *about*: the log spans projects and installs, and the questions it
   * answers -- did the recorder stop, what did one browser session do, where
   * is the friction -- are questions about the console rather than about any
   * one project. A facet would force a project id onto that view, and the
   * first thing a reader would have to do is pick a project to ignore.
   *
   * Reached from the header beside the brand, for the same reason. There is
   * nowhere on a project page this belongs.
   *
   * `filters` rather than `Selection`: the project route selects one thing at
   * a time, which is what that page is, and this one narrows a stream by
   * several independent axes at once. */
  | { readonly name: 'interactions'; readonly filters: InteractionFilters }
  /** One scope's settings.
   *
   * A top-level route rather than a facet on the project page, and the
   * argument is the interaction log's own, one paragraph above: a facet forces
   * a project id onto a view, and the first thing a reader of a *user*-scope
   * settings page would have to do is pick a project to ignore. The same
   * reasoning gives the same answer.
   *
   * `scope` and `scopeId` are both in the path because the page is one
   * component parametrised by them -- `#/settings/project/<id>` and
   * `#/settings/tenant/<id>` are the same screen over different data, not two
   * screens. Only `project` is reachable today; the grammar admits the other
   * two so that S5 is a component change rather than a routing one.
   *
   * `group` is optional so a link can land on a section. Optional rather than
   * defaulted to the first group: "the settings page" and "the settings page
   * scrolled to Extraction" are different things to send somebody, and
   * defaulting would make the first unspellable. */
  | {
      readonly name: 'settings'
      readonly scope: Scope
      readonly scopeId: string
      readonly group: string | null
    }

/** What kind of thing is selected on a project page.
 *
 * A closed set rather than any string, because an unrecognised facet has to be
 * distinguishable from a recognised one with no id: `#/p/x/entity` is the graph
 * with nothing chosen, and `#/p/x/nonsense/1` is a typo that belongs on the
 * picker. `parseRoute` returns `home` for the second, and a test fails if it
 * stops.
 */
export type Facet = (typeof FACETS)[number]

/** Exported so a test can assert its coverage against the list itself rather
 *  than against a copy of it — a copy is a second thing to forget. */
export const FACETS = [
  'session',
  'topic',
  'entity',
  // The graph's peer rather than a mode of it: same material, ordered by time
  // instead of wired by relationship. A facet of its own because it is a place
  // on the project with its own selection, which is exactly what the grammar
  // is for.
  'timeline',
  // The graph's third reading, after canvas (`entity`) and time (`timeline`):
  // the same material as a list rather than a drawing. A facet of its own for
  // the reason `timeline` is -- it is a place on the project with its own
  // selection, which is exactly what the grammar is for.
  'tree',
  // The graph's fourth reading: not the entities but the *classes* a discovery
  // pass found over them. A facet of its own for `tree`'s reason -- a place on
  // the project with its own selection -- and beside `tree` because both are
  // list readings of the material the canvas draws.
  'ontology',
  // The two curriculum readings, beside the graph readings above rather than
  // at the end: an area is a cluster of the same entities `entity`, `tree` and
  // `timeline` draw, read a fourth way -- by what they turn out to be *about*.
  // `path` is its own facet rather than a mode of `area` for the reason
  // `timeline` is not a mode of `entity`: it is a place on the project with
  // its own selection, which is exactly what the grammar is for.
  'area',
  'path',
  // The Curriculum tab's default reading: the front page a person browses
  // rather than the analytic map or the ordered path above. Its own facet
  // rather than `id: null` on `area` -- a category is worth sending to
  // somebody, and `id` here is a category key, not an area slug, so folding
  // it into `area` would make one facet's id mean two different kinds of
  // thing depending on which reading was on screen.
  'catalog',
  // One candidate's course page, opened from a card on the catalog facet
  // above. Its own facet rather than `catalog`'s `id` for the reason
  // `catalog`'s own comment gives: `catalog`'s id is a category key, and a
  // course's id is a candidate slug -- two different kinds of thing, so one
  // facet's id cannot mean both without a reader having to guess which.
  'course',
  'doc',
  // The corpus's other half: a candidate that has not been accepted into it
  // yet. Its own facet rather than folded into `doc` -- `MediaProposalPane`
  // has no single-select reading the way a document list does, so its id is
  // always null, but it is still a *place on the project* and belongs in the
  // grammar for the reason `timeline` and `tree` are.
  'media',
  'file',
  // Selects nothing -- the ask page is one conversation and has no parts worth
  // a URL. It is a facet anyway because it is a *place on the project*, and
  // giving it a route of its own would be a second grammar for the same idea.
  'ask',
  // A place on the project with a durable id, unlike `ask` beside it: a
  // dialogue's id is minted by the server and is a row key, so it has a better
  // claim to a URL segment than an ask does. The grammar already supports it
  // unchanged -- `Selection` carries an id for every plain facet.
  'dialogue',
] as const

type PlainFacet = Exclude<Facet, 'session' | 'file'>

/** One selected thing, with whatever else that kind of thing needs.
 *
 * A union rather than one record with optional fields: a scrub point on a
 * selected *topic* is meaningless, and a shape that permits it invites a call
 * site to read it. Two arms carry more than an id, and only two.
 *
 * Every arm's `id` is nullable, and that is the truncation rule the two old
 * routes already had: a hand-edited `#/p/x/entity` with nothing after it landed
 * on an empty canvas rather than falling through to the tree. Keeping it means
 * "the graph, nothing selected" and "the drawer, closed" stay expressible,
 * which they must be while the facet is also what chooses the view.
 */
export type Selection =
  | {
      readonly facet: 'session'
      readonly id: SessionId | null
      readonly at: ScrubPoint
      readonly path: FilePath | null
    }
  | { readonly facet: 'file'; readonly id: FilePath | null }
  | { readonly facet: PlainFacet; readonly id: string | null }

const isFacet = (raw: string | undefined): raw is Facet =>
  raw !== undefined && (FACETS as readonly string[]).includes(raw)

/** One kind of interaction event, as the log's vocabulary names it.
 *
 * A closed set here for the reason `FACETS` is a closed set: the filter is
 * built from the vocabulary rather than from the data, so a kind that was
 * never emitted and a kind that does not exist stay distinguishable. A filter
 * offering only what the table happens to hold cannot show that the recorder
 * stopped, which is the first question the explorer exists to answer.
 *
 * It is a hand-kept copy of `INTERACTION_EVENTS` in
 * `research_team/domain/interaction.py`, and that is a cost worth naming: the
 * two are in different languages, so nothing in either gate compares them. A
 * kind added on the server and not here is a kind this route drops from a
 * URL -- silently, because dropping an unrecognised kind is also how a typo
 * is handled. The health route answers with every kind it knows, so the
 * cheapest check available is that this list and that response agree; nothing
 * asserts it yet.
 *
 * Exported so a test asserts coverage against the list rather than a copy. */
export const INTERACTION_KINDS = [
  'ViewEntered',
  'ViewExited',
  'AttentionLost',
  'AttentionRegained',
  'EntityOpened',
  'ProjectSwitched',
  'ExtractionQueued',
  'ExtractionCancelled',
  'DispatchRequested',
  'SearchPerformed',
  'AskSubmitted',
  'ApprovalDecided',
  'ActionUndone',
  'ActionRetried',
  'EmptyResultEncountered',
  'RenderErrorRaised',
] as const

export type InteractionKind = (typeof INTERACTION_KINDS)[number]

const isInteractionKind = (raw: string): raw is InteractionKind =>
  (INTERACTION_KINDS as readonly string[]).includes(raw)

/** The filter bar's state, and every field of it is in the URL.
 *
 * The grammar's own rule, applied: a linkable state is a bookmark. A filtered
 * reading of the log is exactly the thing somebody wants to send -- "the four
 * empty searches on the catalog last Tuesday" is a link or it is a paragraph
 * of instructions.
 *
 * Arrays rather than sets for the two multi-selects, because a `Set` is not
 * structurally comparable and every test here is `toEqual`. Order is the
 * order the URL carried, which the printer and the parser both preserve, so
 * the round trip is an identity rather than a normalisation.
 *
 * `since` and `until` are the raw strings from the URL, kept as strings
 * rather than parsed into `Date`s: they go back out to the server as query
 * parameters, and a parse-and-reformat here would be a second date format for
 * nobody's benefit. They are validated on the way in -- see
 * `parseInteractionFilters`. */
export interface InteractionFilters {
  readonly kinds: readonly InteractionKind[]
  readonly views: readonly string[]
  readonly projectId: string | null
  readonly installId: string | null
  readonly browserSessionId: string | null
  readonly since: string | null
  readonly until: string | null
}

/** The unfiltered log, which is what `#/i` with no query means. */
export const NO_INTERACTION_FILTERS: InteractionFilters = {
  kinds: [],
  views: [],
  projectId: null,
  installId: null,
  browserSessionId: null,
  since: null,
  until: null,
}

/** The one query string this app's hash routes carry -- `?t=<seconds>`, the
 *  seek a citation link put on a `doc` route (see `references.ts`'s
 *  `expandReferences` and `GraphDetail`'s citation links, the two things that
 *  produce it). Split off here, once, rather than left for `parseRoute` to
 *  trip over: `wouter`'s `useHashLocation` hands back the hash verbatim,
 *  query and all, and a naive `split('/')` over `…/doc/<sourceId>?t=252`
 *  would fold `?t=252` onto the end of the id segment instead of parsing it
 *  as a document at all -- silently, because `?t=252` contains no `/` for the
 *  segment split to catch. Measured against `parseRoute.test.ts` before this
 *  existed: a citation's own link broke the id it pointed at.
 */
const splitQuery = (hash: string): { path: string; query: string | null } => {
  const raw = String(hash ?? '')
  const at = raw.indexOf('?')
  return at === -1
    ? { path: raw, query: null }
    : { path: raw.slice(0, at), query: raw.slice(at + 1) }
}

/** `null` for every case that is not "a well-formed non-negative seek" --
 *  absent, non-numeric, negative, or a range (`t=5,10`, which
 *  `expandReferences` never emits for a query, only for the inline
 *  reference's own `@start-end` form). Defensive on purpose: this value
 *  arrives from a URL a person can hand-edit and a model indirectly
 *  influenced through the citation it wrote, and the failure this guards is
 *  a seek to `NaN` reaching `HTMLMediaElement.currentTime`, which throws.
 *  Mirrors `expandReferences`'s own answer to a malformed offset -- render as
 *  though it were not there, rather than guess -- so the two ends of this
 *  round trip agree about what a bad value means. `Number(...)` rather than
 *  `Number.parseInt`: a definition citation's `atSeconds` is a float
 *  (`GraphDetail` formats it with plain `String()`), so `252.5` in the query
 *  has to parse back to `252.5`, not truncate to `252`. */
export const parseSeekSeconds = (hash: string): number | null => {
  const { query } = splitQuery(hash)
  if (query === null) return null
  const raw = new URLSearchParams(query).get('t')
  if (raw === null || raw === '') return null
  const seconds = Number(raw)
  return Number.isFinite(seconds) && seconds >= 0 ? seconds : null
}

/** Which lesson is being presented, and at which slide, or `null` for "the
 *  document, not the deck".
 *
 * `?deck=<path>&slide=<n>` on whatever route is already showing, read
 * independently of `useRoute` -- the same shape as `?t=` above, and the same
 * argument, which `parseSeekSeconds`'s docstring makes: a query parameter that
 * applies to one surface does not belong in the `Route` union, because every
 * other route's reader would then have to guard a field that cannot apply to
 * it. A deck opens over a course page today; it is a lesson file's second
 * reading and could open over the workspace tomorrow without the grammar
 * changing.
 *
 * Defensive in the way the rest of this parser is: a `deck=` with no path is
 * not a deck, and a `slide=` that is absent, non-numeric or negative is slide
 * zero rather than a `NaN` reaching an array index. An index past the end is
 * *not* rejected here -- `clampSlide` handles it against the deck, which is
 * the only thing that knows how long the lesson is. */
export const parseDeck = (hash: string): { path: string; slide: number } | null => {
  const { query } = splitQuery(hash)
  if (query === null) return null
  const params = new URLSearchParams(query)
  const path = params.get('deck')
  if (path === null || path === '') return null
  const raw = Number(params.get('slide') ?? '')
  const slide = Number.isFinite(raw) && raw >= 0 ? Math.trunc(raw) : 0
  return { path, slide }
}

/** The same hash with a deck opened on it, or closed.
 *
 * Built by rewriting the current hash rather than from a route, because the
 * deck is a layer over whatever page is showing and closing it must land the
 * reader exactly where they were -- including any other query the route
 * carried. `slide` is omitted at zero, so the first slide has one spelling. */
export const withDeck = (hash: string, deck: { path: string; slide: number } | null): string => {
  const { path, query } = splitQuery(hash)
  const params = new URLSearchParams(query ?? '')
  params.delete('deck')
  params.delete('slide')
  if (deck !== null) {
    params.set('deck', deck.path)
    if (deck.slide > 0) params.set('slide', String(deck.slide))
  }
  const printed = params.toString()
  const base = path.startsWith('#') ? path : `#${path}`
  return printed === '' ? base : `${base}?${printed}`
}

export const parseRoute = (hash: string): Route => {
  const { path, query } = splitQuery(hash)
  const parts = path
    .replace(/^#?\/?/, '')
    .split('/')
    .filter(Boolean)
    .map(decodeURIComponent)

  // The only route whose state lives in the query rather than in the path.
  // `parts.length === 1` rather than a prefix match: `#/i/anything` is a typo
  // or a dead link, and it falls through to `home` exactly as an unrecognised
  // facet does. Nothing after `i` means anything, so accepting it would be
  // answering a question nobody asked.
  if (parts[0] === 'i' && parts.length === 1) {
    return { name: 'interactions', filters: parseInteractionFilters(query) }
  }

  // `isScope` rather than any string: `#/settings/nonsense/1` is a typo or a
  // dead link and falls through to `home` exactly as an unrecognised facet
  // does. Accepting it would render a page whose every row was filtered out by
  // `spec.scopes`, which reads as "this scope has no settings" -- a wrong
  // answer rather than an absent one.
  if (parts[0] === 'settings' && parts[1] && parts[2] && isScope(parts[1])) {
    return { name: 'settings', scope: parts[1], scopeId: parts[2], group: parts[3] ?? null }
  }

  if (parts[0] === 's' && parts[1]) {
    const { at, path } = parseSessionTail(parts.slice(2))
    return { name: 'session', id: SessionId(parts[1]), at, path }
  }

  // A project page belongs to the project, not to the session that happens to
  // be driving it: the topics, artifacts and graph outlive any one session, so
  // the route that shows them is keyed the way they are stored.
  if (parts[0] === 'p' && parts[1]) {
    const id = ProjectId(parts[1])
    if (parts[2] === undefined) return { name: 'project', id, selection: null }

    const selection = parseSelection(parts.slice(2))
    // An unrecognised facet is a typo or a dead link, and the project page has
    // nothing to show for it. Falling back to the project with no selection
    // would silently answer a question nobody asked.
    if (selection === null) return { name: 'home' }
    return { name: 'project', id, selection }
  }

  return { name: 'home' }
}

/** The `at`/`file` tail, shared by the standalone session route and the session
 *  facet, because they are the same suffix and were the same code twice. */
const parseSessionTail = (
  segments: readonly string[],
): { at: ScrubPoint; path: FilePath | null } => {
  let rest = segments

  let at = ScrubPoint.head()
  if (rest[0] === 'at' && rest[1]) {
    const index = Number.parseInt(rest[1], 10)
    if (isEventIndex(index)) at = ScrubPoint.at(EventIndex(index))
    rest = rest.slice(2)
  }

  // A path may itself contain slashes, so everything after `file` is one
  // segment rejoined — splitting it into route parts would lose directories.
  const path = rest[0] === 'file' && rest[1] ? FilePath.of(rest.slice(1).join('/')) : null

  return { at, path }
}

/** `null` for an unrecognised facet, which is the caller's cue to give up. */
const parseSelection = (segments: readonly string[]): Selection | null => {
  const facet = segments[0]
  if (!isFacet(facet)) return null

  if (facet === 'session') {
    const id = segments[1] ? SessionId(segments[1]) : null
    const { at, path } = parseSessionTail(segments.slice(2))
    return { facet, id, at, path }
  }

  if (facet === 'file') {
    // Rejoined for the reason the session's file segment is.
    return { facet, id: segments[1] ? FilePath.of(segments.slice(1).join('/')) : null }
  }

  // Deliberately one segment: the remaining facets are keyed by opaque ids, and
  // a builder that encodes them keeps any slash inside a single segment. A doc
  // identified by a path would need the rejoin above, and would be a change to
  // this line rather than to the grammar.
  return { facet, id: segments[1] ?? null }
}

export const homeHref = (): string => '#/'

/** `#/settings/<scope>/<id>`, with an optional group segment.
 *
 * Every segment is encoded, for `seg`'s reason one layer down: a tenant id or
 * a group name may hold a space or a slash, and forgetting on the last one is
 * how a link becomes a route nobody can reproduce. For any route this builds,
 * `parseRoute(settingsHref(...))` returns it back. */
export const settingsHref = (scope: Scope, scopeId: string, group?: string | null): string => {
  const tail = group ? `/${encodeURIComponent(group)}` : ''
  return `#/settings/${encodeURIComponent(scope)}/${encodeURIComponent(scopeId)}${tail}`
}

/** `#/i`, with the filters in the query part.
 *
 * Repeatable keys for the two multi-selects (`?kind=A&kind=B`) rather than a
 * comma-joined list: a view name is a free string that a future route segment
 * could contain a comma in, and `URLSearchParams` already encodes and decodes
 * repetition without anybody writing a splitter.
 *
 * Empty filters print as a bare `#/i`, so the unfiltered log has one spelling
 * rather than one with an empty query on the end. Duplicates are dropped, so
 * the printed form is canonical: for any `f` this function can produce,
 * `parseRoute(interactionsHref(f))` is `{ name: 'interactions', filters: f }`. */
export const interactionsHref = (filters: InteractionFilters = NO_INTERACTION_FILTERS): string => {
  const query = new URLSearchParams()
  for (const kind of unique(filters.kinds)) query.append('kind', kind)
  for (const view of unique(filters.views)) query.append('view', view)
  if (filters.projectId) query.set('project', filters.projectId)
  if (filters.installId) query.set('install', filters.installId)
  if (filters.browserSessionId) query.set('session', filters.browserSessionId)
  if (filters.since) query.set('since', filters.since)
  if (filters.until) query.set('until', filters.until)
  const printed = query.toString()
  return printed === '' ? '#/i' : `#/i?${printed}`
}

const unique = <T>(values: readonly T[]): readonly T[] => [...new Set(values)]

/** Total, and defensive in the way the rest of this parser is -- with one
 *  difference from the facet parser worth stating, because it is the opposite
 *  choice.
 *
 * An unrecognised *facet* fails the whole route to `home`: a facet decides
 * which page renders, so a typo there means the console has no idea what to
 * show. A bad *filter* does not. `#/i?kind=Nonsense&kind=ViewExited` is a
 * reader who mistyped one of two kinds, and dropping the bad one leaves a
 * page that answers most of what they asked; falling back to `home` would
 * throw away the other kind, the time window and the whole visit. So a
 * malformed value is dropped from the filter, the rest survives, and `#/i`
 * with nothing recognisable left is the unfiltered log rather than an error.
 *
 * A date is kept only if `Date.parse` reads it. That is deliberately the
 * loosest check available -- the value goes to a server that parses it again
 * and is the real authority -- and it is enough to stop `since=yesterday`
 * from reaching a comparison as `NaN`, which is the failure this guards.
 * The string is stored as it arrived rather than reformatted, so the round
 * trip is exact.
 */
export const parseInteractionFilters = (query: string | null): InteractionFilters => {
  if (query === null || query === '') return NO_INTERACTION_FILTERS
  const params = new URLSearchParams(query)
  const one = (key: string): string | null => {
    const raw = params.get(key)
    return raw === null || raw === '' ? null : raw
  }
  const instant = (key: string): string | null => {
    const raw = one(key)
    return raw !== null && Number.isFinite(Date.parse(raw)) ? raw : null
  }
  return {
    kinds: unique(params.getAll('kind').filter(isInteractionKind)),
    views: unique(params.getAll('view').filter((view) => view !== '')),
    projectId: one('project'),
    installId: one('install'),
    browserSessionId: one('session'),
    since: instant('since'),
    until: instant('until'),
  }
}

/** The scrub point and the open file are both in the URL, and both are
 *  optional.
 *
 * Carrying them together is what makes "the exact thing I am looking at"
 * linkable: a reader comparing one file across two points is looking at a
 * position *and* a document, and a link that dropped either would send somebody
 * to a different screen. It is also the reason neither needs a copy in
 * component state — the address bar is the single source of truth. */
export const sessionHref = (
  id: SessionId,
  at?: ScrubPoint | null,
  path?: FilePath | null,
): string => `#/s/${encodeURIComponent(id)}${sessionTail(at, path)}`

const sessionTail = (at?: ScrubPoint | null, path?: FilePath | null): string => {
  let tail = ''
  if (at && at.kind === 'historical') tail += `/at/${at.at}`
  if (path) tail += `/file/${encodeURIComponent(path.value)}`
  return tail
}

/** The project page, with or without a selection.
 *
 * One builder for eight facets rather than eight builders: the grammar is
 * uniform by construction, so a facet added to `Facet` is linkable without
 * anyone remembering to write its href. */
export const projectHref = (projectId: ProjectId, selection?: Selection | null): string =>
  `#/p/${encodeURIComponent(projectId)}${selection ? selectionTail(selection) : ''}`

const selectionTail = (selection: Selection): string => {
  if (selection.facet === 'session') {
    if (!selection.id) return '/session'
    return (
      `/session/${encodeURIComponent(selection.id)}` + sessionTail(selection.at, selection.path)
    )
  }
  if (selection.facet === 'file') {
    return selection.id ? `/file/${encodeURIComponent(selection.id.value)}` : '/file'
  }
  return selection.id
    ? `/${selection.facet}/${encodeURIComponent(selection.id)}`
    : `/${selection.facet}`
}

/** The session facet, built.
 *
 * A helper only because this arm has three fields and two of them are usually
 * defaults; the other seven facets are object literals at the call site and do
 * not need one. */
export const sessionSelection = (
  id: SessionId | null,
  at: ScrubPoint = ScrubPoint.head(),
  path: FilePath | null = null,
): Selection => ({ facet: 'session', id, at, path })
