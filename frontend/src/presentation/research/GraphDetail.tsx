import { edgesOf, isExpanded, type GraphView } from '@domain/knowledge/graph.ts'
import { shortId, type ProjectId } from '@domain/shared/identifier.ts'

import { useEscape } from '../layout/OverlayHost.tsx'
import { projectHref } from '../routing/routes.ts'
import { useUsages } from './use-usages.ts'

/** An edge row: a full-width bare button you walk the graph with.
 *
 * The left edge is drawn on hover *and* focus and is the same "this one" mark
 * the document and topic rows use — one convention for row emphasis across the
 * page. `border-0` first because `border-solid` styles all four sides, so the
 * three with no explicit width would otherwise fall back to the browser's
 * `medium`; the transparent 2px reserves the gutter so the row does not shift
 * when it lights up.
 *
 * **The ring is inward, and that is a change from the rule this replaces.**
 * `tokens.css`'s global `:focus-visible` draws 2px at `outline-offset: 1px` —
 * three pixels outside the border box — and these rows are `w-full` inside a
 * scroller whose padding is 4px. One pixel of slack is not a fix, it is a
 * coincidence that survives until somebody tightens the padding, and the
 * scroller clips on the padding box regardless once a row is scrolled to the
 * edge. `lay-ring-inward` puts the whole ring inside the row.
 *
 * It is a class and not the `focus-visible:outline-offset-[-2px]` utility
 * `DocumentBrowser`'s `RING_INWARD` reached for, because that utility does not
 * work -- `layout.css` carries the measurement and the layering argument.
 * `graph-dressing.browser.test.tsx` is what catches it coming back; jsdom
 * cannot, because it lays nothing out.
 *
 * `[font:inherit]` is arbitrary because the `font` shorthand has no utility,
 * and a `<button>` that does not inherit it renders in the user agent's
 * 13.33px sans — this build imports no preflight, so nothing else resets it. */
const ROW = [
  'flex w-full cursor-pointer flex-col items-start gap-[1px]',
  'border-0 border-l-2 border-solid border-l-transparent rounded-md',
  'bg-transparent px-[7px] py-[5px] text-left text-inherit [font:inherit]',
  'hover:bg-bg-hover hover:border-l-accent',
  'focus-visible:bg-bg-hover focus-visible:border-l-accent',
  'lay-ring-inward',
].join(' ')

/** What the selected node is, and what it is connected to.
 *
 * The answer to "I clicked a node and nothing meaningful happened". Expanding
 * draws more dots; this says what the dot under the cursor actually was and
 * how it relates to the ones around it -- which is the question somebody
 * browsing a knowledge graph is asking in the first place.
 *
 * Relationship type is the row's heading rather than a detail hidden in a
 * tooltip: `advised` and `contradicts` are the content of a knowledge graph,
 * and a list that only said "connected to" would be throwing away the part
 * worth reading.
 */
export const GraphDetail = ({
  projectId,
  view,
  selected,
  onSelect,
  onRemove,
  onClose,
}: {
  projectId: ProjectId
  view: GraphView
  selected: string
  /** Selecting from here expands too, which is what makes this a way of
   *  walking the graph rather than a read-only card. */
  onSelect: (id: string) => void
  onRemove: (id: string) => void
  onClose: () => void
}) => {
  // Escape closes it, the way it closes the drawers this console already has.
  // Not a focus trap, though, and deliberately not: the drawer is modal and
  // this is not -- the point of the panel is to read it *while* working the
  // canvas beside it, so trapping focus inside would break the one thing it is
  // for. `useEscape` rather than `Overlay` is exactly that distinction: a turn
  // at the key without being portalled, floated or confined.
  //
  // **This was a `window` listener, and that was the defect.** The host hands
  // Escape to the topmost layer and to nothing else, precisely so two open
  // things do not both close on one keypress -- and a listener bound to
  // `window` sits outside that arrangement entirely. `inert` does not cover
  // it either: it blocks focus and pointers and has no opinion about keydown
  // listeners on `window`. So with the agent dock expanded over the research
  // view, one Escape closed the dock *and* this panel behind it, which the
  // reader could not see was in play.
  useEscape(onClose)

  // Fetched independently of the edge list below and of the definition Task
  // 12 adds above this section: three reads over the same `selected` id, none
  // of which the others' latency should hold hostage. A reader who clicked a
  // heavily-connected node should not wait on the corpus's BM25 lookup before
  // seeing who it is wired to, and a slow edge fetch must not blank the
  // passages that already came back.
  const usagesQuery = useUsages(projectId, selected)

  const node = view.nodes.find((candidate) => candidate.id === selected)
  // The selection can outlive its node only if something removed it from the
  // view, which nothing does today -- but rendering an empty shell would be a
  // worse answer than rendering nothing.
  if (!node) return null

  const edges = edgesOf(view, selected)

  return (
    // Docked to the right edge of the stage, top to bottom, so it does not
    // stack on the same corner as the search bar opposite it.
    <aside
      className="lay-region-float absolute inset-y-3 right-3 flex w-[min(300px,calc(100%_-_20px))] flex-col rounded-md border border-solid border-line bg-bg-panel shadow-1"
      aria-label={`About ${node.name}`}
    >
      <header className="flex items-start gap-2 border-0 border-b border-solid border-b-line px-3 py-[8px]">
        <div className="min-w-0 flex-auto">
          {/* Entity names in this corpus run to whole sentences -- a `fact` is
              a full clause -- so the heading wraps rather than being clipped to
              one line. */}
          <h3 className="font-semibold m-0 text-sm [overflow-wrap:anywhere]">{node.name}</h3>
          <p className="mx-0 mt-[2px] mb-0 font-mono text-xs text-fg-dim">{node.entityType}</p>
        </div>
        <div className="flex shrink-0 gap-2">
          {/* "Remove from view", not "Delete": this takes a dot off a drawing
              and nothing else. A reader who thought this deleted an entity
              from the knowledge graph would never touch it. */}
          <button
            type="button"
            className="btn btn-sm"
            onClick={() => onRemove(selected)}
            aria-label={`Remove ${node.name} from the view`}
          >
            Remove
          </button>
          <button
            type="button"
            className="btn btn-sm"
            onClick={onClose}
            aria-label="Close entity details"
          >
            Close
          </button>
        </div>
      </header>

      {/* Above the edge list, per the plan: a reader who came here to see
          *what a node is* wants the passages that named it before the graph
          it sits in -- the edges are how it relates to the rest of the
          drawing, and the passages are where the reader learns what "it" is
          at all. Renders off its own query, so a slow BM25 lookup here never
          blanks the edge list below (`edgesOf` reads straight from `view`,
          already resolved by the time this panel opens). */}
      <section className="border-0 border-b border-solid border-b-line px-3 py-[8px]">
        <h4 className="tracking-wide m-0 mb-[4px] text-xs text-fg-faint uppercase">Mentions</h4>
        {usagesQuery.isPending ? (
          <p className="m-0 text-xs text-fg-dim">Loading mentions…</p>
        ) : usagesQuery.isError ? (
          <p className="m-0 text-xs text-fg-dim">Mentions could not be read.</p>
        ) : usagesQuery.data.length === 0 ? (
          // Same distinction the edge list draws below, and the same reason:
          // a fetch that came back empty is not the same fact as one that has
          // not happened yet, and this branch only renders once it has.
          <p className="m-0 text-xs text-fg-dim">No mentions of this entity were found.</p>
        ) : (
          <ul className="m-0 flex list-none flex-col gap-[6px] p-0">
            {usagesQuery.data.map((usage) => (
              <li key={`${usage.sourceId}|${usage.start}|${usage.end}`}>
                {/* The `doc` facet `CitationList` already links through, not
                    the API route Task 6 built -- that endpoint answers JSON,
                    and a reader who followed it would get a page of raw text
                    with no reader chrome around it, which is not "the passage
                    in context" the citation decision promised. `Selection`'s
                    `PlainFacet` arm carries only an id (`routes.ts`), so this
                    cannot ask for `start`/`end` today -- it opens the right
                    document rather than a scrolled-to span, and lands on the
                    top of the reader rather than on this exact mention. That
                    gap is real and is not this task's to close; see the
                    commit message. */}
                <a
                  className="flex flex-col gap-[1px] text-inherit no-underline hover:underline"
                  href={projectHref(projectId, { facet: 'doc', id: usage.sourceId })}
                >
                  <span className="font-mono text-xs text-fg-dim">{shortId(usage.sourceId)}</span>
                  <span className="text-sm [overflow-wrap:anywhere]">{usage.text}</span>
                </a>
              </li>
            ))}
          </ul>
        )}
      </section>

      <h4 className="tracking-wide m-0 px-3 pt-[8px] text-xs text-fg-faint uppercase">
        Relationships
      </h4>

      {edges.length === 0 ? (
        // Two different facts, and telling them apart matters: an entity whose
        // neighbourhood has been fetched and came back empty really has no
        // recorded connections, and telling that reader to click it again
        // sends them to fetch a second time for the same nothing.
        <p className="m-0 p-3 text-xs text-fg-dim">
          {isExpanded(view, selected)
            ? 'No relationships were recorded for this entity.'
            : 'Nothing connected to this one has been drawn yet. Click it on the canvas to pull in its neighbourhood.'}
        </p>
      ) : (
        <ul
          data-edge-scroll
          className="m-0 flex list-none flex-col gap-[1px] overflow-y-auto p-[4px]"
        >
          {edges.map((edge) => (
            <li key={`${edge.direction}|${edge.relationshipType}|${edge.other.id}`}>
              <button
                type="button"
                data-edge-row
                className={ROW}
                onClick={() => onSelect(edge.other.id)}
              >
                <span className="font-mono text-xs text-fg-dim">
                  {/* The arrow carries the direction, so the row reads as a
                      sentence about the selected node in both cases rather
                      than as a label the reader has to reverse in their head
                      half the time. */}
                  {edge.direction === 'out' ? '→' : '←'} {edge.relationshipType}
                </span>
                <span className="text-sm [overflow-wrap:anywhere]">{edge.other.name}</span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </aside>
  )
}
