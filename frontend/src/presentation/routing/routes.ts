import { EventIndex, isEventIndex } from '@domain/session/event-index.ts'
import { ScrubPoint } from '@domain/session/scrub-point.ts'
import { FilePath } from '@domain/shared/file-path.ts'
import { ProjectId, SessionId } from '@domain/shared/identifier.ts'

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
  'stage',
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
  'doc',
  // The corpus's other half: a candidate that has not been accepted into it
  // yet. Its own facet rather than folded into `doc` -- `MediaProposalPane`
  // has no single-select reading the way a document list does, so its id is
  // always null, but it is still a *place on the project* and belongs in the
  // grammar for the reason `timeline` and `tree` are.
  'media',
  'file',
  'artifact',
  'finding',
  // Selects nothing -- the ask page is one conversation and has no parts worth
  // a URL. It is a facet anyway because it is a *place on the project*, and
  // giving it a route of its own would be a second grammar for the same idea.
  'ask',
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

export const parseRoute = (hash: string): Route => {
  const parts = splitQuery(hash)
    .path.replace(/^#?\/?/, '')
    .split('/')
    .filter(Boolean)
    .map(decodeURIComponent)

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
