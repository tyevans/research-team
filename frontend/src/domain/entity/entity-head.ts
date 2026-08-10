/** What every presentable has in common, and nothing more.
 *
 * Three fields, because three is what it takes to name a thing in someone
 * else's sentence: what kind it is, which one it is, and what to call it. A
 * fourth would have to be justified by a second component needing it, and no
 * component does.
 *
 * **Why this exists at all.** A reference to an entity is written seven ways
 * in this console today — `held by 3f2a…` on a landing row against `not held`
 * on the scrub bar, a breadcrumb naming a project by short id "deliberately,
 * to avoid a request on every session load" against a landing page naming it
 * in full, the dock showing a name "or short id while `/api/projects` has not
 * resolved". Seven sites, one job, no shared component. `EntityHead` is the
 * argument that component takes.
 *
 * **`kind` is a closed union rather than a string.** An unknown kind should be
 * a type error at the call site that invented it, not a chip with no styling
 * discovered by a reader. This is the same reasoning `tokens.css` gives for
 * refusing a second literal hex.
 */
export type EntityKind = 'project' | 'session' | 'topic' | 'document' | 'worker'

export interface EntityHead {
  readonly kind: EntityKind
  /** The wire id, whole. Never shortened here: shortening is a presentation
   *  decision that depends on how much room the site has, and a head that
   *  arrived pre-shortened cannot be un-shortened for a `title` or a URL. */
  readonly id: string
  /** What to call it, when that is known.
   *
   *  `null` rather than falling back to the id here, and that is the whole
   *  design of this type. `Breadcrumbs` names a project by short id
   *  deliberately, to avoid a request on every session load; the landing page
   *  knows the name because it already listed projects. Both are right. What
   *  is wrong is that each site decides separately what to do when the name is
   *  absent, so the console says `3f2a1b9c` in one place and `unknown project`
   *  in another for the same fact. Carrying the absence explicitly moves that
   *  decision into one component — and, critically, makes "name it if you
   *  already know it, never fetch in order to name it" expressible rather than
   *  merely conventional. */
  readonly label: string | null
}

/** Whether a head is naming its entity or falling back to an id.
 *
 * Exported because the fallback should be *visible* — a short id rendered in
 * the same weight as a name reads as a name, and a reader cannot tell that the
 * console does not know what this thing is called.
 */
export const isNamed = (head: EntityHead): boolean =>
  head.label !== null && head.label.trim().length > 0
