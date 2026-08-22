/** What a project turned out to be about, and in what order to learn it.
 *
 * Types and one fold, no fetching and no React. The fold — `stepsOf` — exists
 * here rather than in the pane because it is the join the server deliberately
 * does not make: the wire carries areas as a list and the path as a list of
 * slugs, which is the honest shape (an area belongs to the map whether or not
 * a path visits it), and every surface that draws the path needs them zipped.
 * Zipping in a component would put a lookup that can silently miss inside a
 * render.
 */

/** One entity's place in an area.
 *
 * `centrality` is a weighted degree *inside the area*, already rounded by the
 * server. Not comparable across areas, and nothing should try: a large area's
 * members carry larger numbers for reasons that are about the area's size
 * rather than about the entities.
 */
export interface AreaMember {
  readonly entityId: string
  readonly name: string
  readonly entityType: string
  readonly centrality: number
  readonly temporal: string | null
}

export interface LearningArea {
  readonly slug: string
  readonly title: string
  readonly summary: string | null
  readonly size: number
  /** The map sent anchors only, and there were more. Distinct from `size`:
   *  a card showing five of five and one showing five of sixty are different
   *  claims, and a reader counting rows cannot tell them apart. */
  readonly truncatedMembers: boolean
  readonly members: readonly AreaMember[]
}

/** One ordering claim, with the evidence that produced it.
 *
 * `reason` is prose from the server rather than a score, because a score is
 * not checkable — "its entities are cited by the later area's more than the
 * reverse" is something a reader can go and look at.
 */
export interface PrerequisiteEdge {
  readonly before: string
  readonly after: string
  readonly weight: number
  readonly reason: string
  /** The reverse also had a claim, and this direction won by a margin. Shown,
   *  never hidden: a mutual dependency is real information about the subject,
   *  and the reader deciding whether to trust the order is the one who needs
   *  it. */
  readonly contested: boolean
}

export interface LearningPath {
  readonly slug: string
  readonly title: string
  /** The area this path was cut to reach, or `null` for the complete path. */
  readonly destination: string | null
  readonly areaSlugs: readonly string[]
  readonly edges: readonly PrerequisiteEdge[]
}

/** What the projection was computed from.
 *
 * Rendered on every surface that shows areas, and not as decoration: a map
 * over forty entities and one over four thousand draw identically, so without
 * these numbers a reader cannot tell a thin projection from a rich one — or a
 * feature that ran from one that was never wired.
 */
export interface DerivedFrom {
  readonly entities: number
  readonly relationships: number
  readonly passages: number
  /** Embedding-derived edges actually drawn, after the similarity floor.

   * Beside `usedEmbeddings` rather than instead of it, because the two answer
   * different questions. The flag says whether the signal contributed at all,
   * which is what decides whether the map can be trusted as a whole picture;
   * the count says whether it contributed *meaningfully*, and eleven edges
   * across four thousand entities is true and negligible at once. */
  readonly semanticEdges: number
  readonly usedEmbeddings: boolean
  readonly truncated: boolean
}

export interface Curriculum {
  readonly areas: readonly LearningArea[]
  readonly path: LearningPath
  readonly derivedFrom: DerivedFrom
}

export const emptyCurriculum: Curriculum = {
  areas: [],
  path: { slug: 'complete', title: '', destination: null, areaSlugs: [], edges: [] },
  derivedFrom: {
    entities: 0,
    relationships: 0,
    passages: 0,
    semanticEdges: 0,
    usedEmbeddings: false,
    truncated: false,
  },
}

export interface PathStep {
  readonly position: number
  readonly area: LearningArea
  /** Why this step follows the one before it, or `null` when nothing ordered
   *  them. `null` is a real answer and is rendered as one — the server omits
   *  an edge below its evidence floor rather than inventing a weak one, so a
   *  step with no reason is telling the truth about the pair. */
  readonly reason: PrerequisiteEdge | null
}

/** The path's areas in order, zipped with the edge that placed each.
 *
 * An area named by the path but absent from the map is **skipped**, not
 * rendered as a placeholder. The two lists come from one response computed in
 * one pass, so a mismatch means the projection changed underneath a stale
 * client — and a row reading "unknown area" would invite a reader to conclude
 * something about their project rather than about their tab.
 */
export const stepsOf = (curriculum: Curriculum): readonly PathStep[] => {
  const bySlug = new Map(curriculum.areas.map((area) => [area.slug, area]))
  const reasons = new Map(
    curriculum.path.edges.filter((e) => !e.contested).map((e) => [e.after, e]),
  )
  const steps: PathStep[] = []
  for (const slug of curriculum.path.areaSlugs) {
    const area = bySlug.get(slug)
    if (area === undefined) continue
    steps.push({ position: steps.length + 1, area, reason: reasons.get(slug) ?? null })
  }
  return steps
}

/** Every contested edge on the path. Surfaced together because they are the
 *  one thing about an order a reader should be interrupted for, and one
 *  buried per step is one nobody reads. */
export const contestedEdges = (curriculum: Curriculum): readonly PrerequisiteEdge[] =>
  curriculum.path.edges.filter((edge) => edge.contested)
