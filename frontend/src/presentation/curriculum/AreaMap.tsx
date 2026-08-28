import type { Curriculum, LearningArea } from '@domain/knowledge/curriculum.ts'

/** What this project turned out to be about, as cards.
 *
 * **Its job is to be falsifiable at a glance**, which decides everything about
 * what it shows. A reader who knows the subject should be able to look at this
 * and say "those two are the same area" or "that one is three areas" — and a
 * card that showed only a generated title would make that impossible, because
 * a plausible title fits a wrong cluster perfectly. So every card leads with
 * the entity names the graph put in it, and the title is secondary.
 *
 * Sized by member count, but only coarsely: a card whose height tracked size
 * exactly would make the largest area unreadable and the smallest a sliver,
 * and the reader's question is "is this area big" rather than "how big".
 */
export const AreaMap = ({
  curriculum,
  selected,
  areaHref,
}: {
  curriculum: Curriculum
  selected: string | null
  areaHref: (slug: string) => string
}) => {
  if (curriculum.areas.length === 0) return <EmptyMap derivedFrom={curriculum.derivedFrom} />

  return (
    <div className="flex flex-col gap-3">
      <DerivedFromLine curriculum={curriculum} />
      <ul className="m-0 grid list-none grid-cols-[repeat(auto-fill,minmax(15rem,1fr))] gap-3 p-0">
        {curriculum.areas.map((area) => (
          <li key={area.slug}>
            <AreaCard area={area} href={areaHref(area.slug)} selected={area.slug === selected} />
          </li>
        ))}
      </ul>
    </div>
  )
}

const AreaCard = ({
  area,
  href,
  selected,
}: {
  area: LearningArea
  href: string
  selected: boolean
}) => (
  <a
    href={href}
    aria-current={selected ? 'true' : undefined}
    className={[
      // `border` alone, deliberately **without** `border-0` beside it.
      // `CLAUDE.md` pairs the two, and that rule is about a *directional*
      // width -- `border-0` zeroes the three sides you did not ask for. Here
      // all four sides are wanted, so the pair is two conflicting width
      // utilities whose winner is decided by stylesheet order rather than by
      // anything in this file. The first draft had it and prettier's class
      // sort is what made it visible.
      'block rounded-md border border-line p-3 text-fg no-underline',
      'focus-visible:lay-ring-inward hover:bg-bg-hover',
      selected ? 'border-accent bg-bg-raise' : 'bg-bg-panel',
    ].join(' ')}
  >
    <div className="flex items-baseline justify-between gap-2">
      <span className="truncate font-medium">{area.title}</span>
      <span className="shrink-0 text-xs text-fg-dim">{area.size}</span>
    </div>
    {area.summary !== null && <p className="mt-1 mb-0 text-xs text-fg-dim">{area.summary}</p>}
    {/* The names, not a count of them. See the module docstring: a reader can
        only falsify a cluster by seeing what is in it. */}
    <ul className="mt-2 mb-0 flex list-none flex-wrap gap-1 p-0">
      {area.members.map((member) => (
        <li
          key={member.entityId}
          className="rounded-md bg-bg-panel-2 px-2 py-1 text-xs text-fg-dim"
        >
          {member.name}
        </li>
      ))}
      {area.truncatedMembers && (
        <li className="px-2 py-1 text-xs text-fg-dim">+{area.size - area.members.length} more</li>
      )}
    </ul>
  </a>
)

/** What the projection was built from, on every view that shows it.
 *
 * Not decoration. A map over forty entities and one over four thousand draw
 * identically, so without this line a reader cannot tell a thin projection
 * from a rich one — or from a feature that never ran at all.
 */
export const DerivedFromLine = ({ curriculum }: { curriculum: Curriculum }) => {
  const { entities, relationships, passages, semanticEdges, usedEmbeddings, truncated } =
    curriculum.derivedFrom
  return (
    <p className="m-0 text-xs text-fg-dim">
      Projected from {entities} entities, {relationships} stated relationships and {passages} shared
      passages
      {/* The embedding channel is named whether or not it ran, and that is
          the point of saying it at all. Its absence is silent everywhere else:
          embeddings can be switched off, a project ingested before they were
          durable has none recorded, and a provider whose endpoint was down
          leaves them missing — and all three produce a map that draws
          perfectly. A reader who is not told is looking at a weaker claim
          than they think they are. */}
      {usedEmbeddings ? `, and ${semanticEdges} links found by meaning alone.` : '.'}
      {!usedEmbeddings && (
        <span> Nothing was joined by meaning — this map is the graph alone.</span>
      )}
      {truncated && (
        <span className="text-k-failure">
          {' '}
          The graph was larger than one read returns, so these areas cover part of it.
        </span>
      )}
    </p>
  )
}

const EmptyMap = ({ derivedFrom }: { derivedFrom: Curriculum['derivedFrom'] }) => (
  <div className="p-4 text-sm text-fg-dim">
    <p className="m-0 font-medium text-fg">No learning areas yet.</p>
    {/* Two different empty states, and they want different next actions, so
        they get different sentences. A project with no entities needs
        extraction; one with entities but no areas has a graph too sparse to
        cluster, and telling that reader to extract again is advice that will
        not help. */}
    {derivedFrom.entities === 0 ? (
      <p className="mt-1 mb-0">
        This project&rsquo;s graph is empty. Add sources and extract them, and the areas will
        follow.
      </p>
    ) : (
      <p className="mt-1 mb-0">
        {derivedFrom.entities} entities are in the graph, but too few are connected to cluster —
        areas come from stated relationships and from entities named together in a passage.
        Extracting more sources is what adds both.
      </p>
    )}
  </div>
)
