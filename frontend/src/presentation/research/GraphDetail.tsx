import { useState } from 'react'

import { edgesOf, isExpanded, type GraphView } from '@domain/knowledge/graph.ts'
import { shortId, type ProjectId } from '@domain/shared/identifier.ts'
import { passageStart } from '@infrastructure/rendering/snippet.ts'

import { Markdown } from '../common/content.tsx'
import { Disclosure } from '../common/primitives.tsx'
import { useEscape } from '../layout/OverlayHost.tsx'
import { projectHref } from '../routing/routes.ts'
import { useDefinition } from './use-definition.ts'
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
  showInGraphHref,
  onClose,
}: {
  projectId: ProjectId
  view: GraphView
  selected: string
  /** Selecting from here expands too, which is what makes this a way of
   *  walking the graph rather than a read-only card. */
  onSelect: (id: string) => void
  /** Take the entity off the drawing, or `undefined` where there is no drawing
   *  to take it off. The timeline reuses this panel and has no canvas to
   *  prune -- offering the control there would be a button that either does
   *  nothing or silently changes a different tab. */
  onRemove?: (id: string) => void
  /** Where "Show in graph" goes, or `undefined` where this panel *is* the
   *  graph. Optional for the reason `onRemove` is, in the other direction:
   *  the timeline needs a route into the graph view and `GraphPane` would be
   *  offering a link to the page the reader is already on.
   *
   *  An href rather than a callback, so it is a real link -- middle-click and
   *  "open in new tab" work, which is most of what makes the two views peers
   *  rather than one being a launcher for the other. */
  showInGraphHref?: string
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

  // Collapsed when the panel opens. The mentions are chunks, not quotations --
  // several of them, each a paragraph or more of retrieved prose -- and they
  // pushed the two things a reader clicked a node to see (what it is, what it
  // is wired to) off the bottom of the drawer. Local state rather than
  // persisted: the fold is a per-visit convenience, and a reader who opened it
  // for one entity has said nothing about the next one.
  const [mentionsOpen, setMentionsOpen] = useState(false)
  // Fetched independently of the edge list below and of the definition section
  // above it: reads over the same `selected` id, neither of which the other's
  // latency should hold hostage. A reader who clicked a heavily-connected node
  // should not wait on the corpus's BM25 lookup before seeing who it is wired
  // to, and a slow edge fetch must not blank the passages that already came
  // back.
  const usagesQuery = useUsages(projectId, selected, { enabled: mentionsOpen })
  // Deliberately its own query rather than a field the usages fetch also
  // carries -- see `use-definition.ts` for why a cache read and a BM25
  // lookup do not belong on one request.
  const definitionQuery = useDefinition(projectId, selected)

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
          {showInGraphHref && (
            <a className="btn btn-sm" href={showInGraphHref}>
              Show in graph
            </a>
          )}
          {/* "Remove from view", not "Delete": this takes a dot off a drawing
              and nothing else. A reader who thought this deleted an entity
              from the knowledge graph would never touch it. Rendered only
              where there is a drawing to remove it from -- the timeline reuses
              this panel with no `onRemove` at all. */}
          {onRemove && (
            <button
              type="button"
              className="btn btn-sm"
              onClick={() => onRemove(selected)}
              aria-label={`Remove ${node.name} from the view`}
            >
              Remove
            </button>
          )}
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

      {/* One scroller for everything under the header, which is a change from
          the edge list owning the only one.

          The drawer is a fixed-height column (`inset-y-3`), and every section
          above the edge list was laid out at its natural height with nowhere
          to overflow to: a long definition, or the mentions fold opened over
          several paragraphs of retrieved prose, ran off the bottom of the
          panel where no amount of scrolling reached it. The edge list scrolled
          beautifully and was the one part nobody was stuck in.

          `min-h-0` is the half that is easy to omit and silent when missing: a
          flex item's default `min-height: auto` refuses to shrink below its
          content, so `flex-1` alone would grow this box to the full height of
          everything inside it and push the overflow right back out of the
          panel. `shell-reached-dressing.browser.test.tsx` has the same pairing
          for the same reason.

          The edge list gives up its own `overflow-y-auto` rather than becoming
          a nested scroller inside this one. Two vertical scrollers in a 300px
          drawer is bad on its own, and the nested version does not even work:
          a flex item with no height bound grows to its content, so the inner
          list would never clip and `graph-dressing.browser.test.tsx`'s
          precondition -- `scrollHeight > clientHeight`, asserted so its ring
          measurements cannot pass vacuously -- would fail. `data-edge-scroll`
          moves here with the scrolling, which is what keeps that measurement
          pointed at the element that actually clips the rows. */}
      <div data-edge-scroll className="flex min-h-0 flex-1 flex-col overflow-y-auto">
        {/* Above the passages, per the brief: a generated definition is the
          answer to "what is this" in one place, and the passages beneath it
          are where a reader goes to check that answer against the corpus.
          Renders off its own query (`useDefinition`), so a slow generation
          never blocks the usages section below it, which is already
          rendering off a query of its own. */}
        <section className="border-0 border-b border-solid border-b-line px-3 py-[8px]">
          <h4 className="tracking-wide m-0 mb-[4px] text-xs text-fg-faint uppercase">Definition</h4>
          {definitionQuery.isPending ? (
            <p className="m-0 text-xs text-fg-dim">Generating a definition…</p>
          ) : definitionQuery.isError ? (
            <p className="m-0 text-xs text-fg-dim">The definition could not be read.</p>
          ) : definitionQuery.data.text === null ? (
            // `text: null` is a 200, not an error: the corpus has nothing to
            // ground a definition in for this entity, which is a fact worth
            // stating plainly rather than as a failure the reader might retry.
            <p className="m-0 text-xs text-fg-dim">
              No grounded definition is available for this entity.
            </p>
          ) : (
            <div className="flex flex-col gap-[4px]">
              <p className="m-0 text-sm [overflow-wrap:anywhere]">{definitionQuery.data.text}</p>
              {definitionQuery.data.stale ? (
                // The server served older text on purpose rather than
                // withholding it -- see `Definition`'s own docstring -- so the
                // reader is told it may be behind rather than left to assume
                // it is current. Client-side only: this is the same cached
                // `data` TanStack Query already keeps on screen through a
                // refetch on this key: no second endpoint, no server round
                // trip to ask "is this still being generated".
                <p className="m-0 text-xs text-fg-dim" role="status">
                  Updating — this definition may be out of date while a newer one generates.
                </p>
              ) : null}
              {/* Rendered, not just carried on the object: the backend refuses
                to store a definition that cites nothing (see
                `entity_definitions.py`), on the premise that an ungrounded
                definition is indistinguishable from a correct one at a
                glance. Leaving the citations off this panel would throw that
                guarantee away at the last step -- a reader would see prose
                that reads as fact with no way to tell it was checked. Same
                link pattern as the mentions list below (`doc` facet,
                `shortId`), so the two halves of the panel cite the same
                way; same known gap, too -- `Selection`'s `PlainFacet` arm
                has no `start`/`end` to carry, so this opens the document
                rather than the exact cited span. */}
              {definitionQuery.data.citations.length > 0 ? (
                <ul className="m-0 flex list-none flex-wrap gap-2 p-0">
                  {definitionQuery.data.citations.map((citation) => (
                    <li key={`${citation.sourceId}|${citation.start}|${citation.end}`}>
                      <a
                        className="font-mono text-xs text-fg-dim no-underline hover:underline"
                        href={projectHref(projectId, { facet: 'doc', id: citation.sourceId })}
                      >
                        {shortId(citation.sourceId)}
                      </a>
                    </li>
                  ))}
                </ul>
              ) : null}
            </div>
          )}
        </section>

        {/* Above the edge list, per the plan: a reader who came here to see
          *what a node is* wants the passages that named it before the graph
          it sits in -- the edges are how it relates to the rest of the
          drawing, and the passages are where the reader learns what "it" is
          at all. Renders off its own query, so a slow BM25 lookup here never
          blanks the edge list below (`edgesOf` reads straight from `view`,
          already resolved by the time this panel opens). */}
        <section className="border-0 border-b border-solid border-b-line px-3 py-[8px]">
          <Disclosure
            label={<span className="tracking-wide text-xs text-fg-faint uppercase">Mentions</span>}
            open={mentionsOpen}
            onToggle={() => setMentionsOpen((open) => !open)}
          >
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
                      <span className="font-mono text-xs text-fg-dim">
                        {shortId(usage.sourceId)}
                      </span>
                      {/* Rendered, not shown raw: a chunk is markdown lifted out of
                      a scraped page, and `## Prodigies` or `**religio**` on
                      screen as literal characters is the source's formatting
                      leaking through as noise.

                      **This nests anchors when the passage contains a link,
                      which is often.** `<a>`'s content model is transparent
                      and forbids interactive descendants, so a browser splits
                      the outer anchor around the inner one and the row stops
                      being a single link -- part of it navigates to the
                      document, part to wherever the corpus pointed. Chosen
                      deliberately over stripping the passage's own links: see
                      the commit message. `mention-snippet.browser.test.tsx`
                      measures what the browser actually does with it, because
                      jsdom does not reparent and so cannot see this at all. */}
                      <Markdown className="md-bare text-sm" source={passageStart(usage.text)} />
                    </a>
                  </li>
                ))}
              </ul>
            )}
          </Disclosure>
        </section>

        <h4 className="tracking-wide m-0 px-3 pt-[8px] text-xs text-fg-faint uppercase">
          Relationships
        </h4>

        {/* The list keeps its 4px padding even though the scrolling has left it:
          that padding is what gives the rows' inward focus ring somewhere to
          sit clear of the clip edge above. */}
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
          <ul className="m-0 flex list-none flex-col gap-[1px] p-[4px]">
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
      </div>
    </aside>
  )
}
