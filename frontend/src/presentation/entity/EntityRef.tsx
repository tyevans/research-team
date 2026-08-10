import clsx from 'clsx'

import { isNamed, type EntityHead } from '@domain/entity/entity-head.ts'
import { shortId } from '@domain/shared/identifier.ts'

/** The `Ref` density: an entity named inside someone else's sentence.
 *
 * One line, no box, no actions. The density exists because seven sites in this
 * console do this job and none of them shares code: `held by 3f2a…` on a
 * landing row against `not held` on the scrub bar; the breadcrumb naming a
 * project by short id "deliberately, to avoid a request on every session load"
 * against the landing page naming it in full; the dock showing a name "or
 * short id while `/api/projects` has not resolved"; `working_on` on the run
 * panel; a finding's `cites`; `forked @ 12`.
 *
 * **The rule it makes real: name it if you already know the name, never fetch
 * in order to name it.** That reasoning exists today as a comment in one
 * component. Here it is the type — a `Ref` takes an `EntityHead` whose label
 * may be null and renders the short id when it is, so a caller that does not
 * know the name has an honest thing to pass rather than a reason to go and
 * ask. Nothing in this component can fetch, which is what enforces it.
 *
 * **The fallback is visible rather than silent**, which is the one behaviour
 * change here. A short id rendered in the same weight as a name reads *as* a
 * name, and a reader cannot tell that the console does not know what the thing
 * is called. Monospace at the small size says "this is an identifier".
 */
export const EntityRef = ({
  head,
  href,
  prefix,
  className,
}: {
  head: EntityHead
  /** Navigation is a URL, never a handler.
   *
   *  L-§9.3: "Nothing on the page is a link. Every navigation is a `<button>`
   *  calling `navigate()`. No ⌘-click, no middle-click, no copy-link, no
   *  status-bar preview." Making `href` the only navigation this contract
   *  accepts closes that once rather than at each call site. Omit it for a
   *  reference with nowhere to go — which renders as text, deliberately not as
   *  a disabled link, the distinction C-F62 draws. */
  /** `| undefined` explicitly, because `exactOptionalPropertyTypes` is on.
   *  Without it a caller cannot *forward* an optional `href` it received —
   *  only omit the prop entirely — which forces a conditional spread at every
   *  site that passes one through. `ProjectCard` handing its `href` to
   *  `EntityRef` is exactly that site. */
  href?: string | undefined
  /** The word before the name, when the sentence needs one: `held by`,
   *  `forked from`. A prop rather than the caller's own `<span>` so that the
   *  prefix and the name cannot be separated by a line break, which is what
   *  makes `held by 3f2a1b9c` wrap into two unrelated-looking fragments in a
   *  narrow rail. */
  prefix?: string
  className?: string
}) => {
  const named = isNamed(head)
  const text = named ? head.label : shortId(head.id)

  const body = (
    <>
      {prefix === undefined ? null : <span className="ent-ref-prefix">{prefix} </span>}
      <span className={clsx('ent-ref-name', !named && 'ent-ref-id')}>{text}</span>
    </>
  )

  return href === undefined ? (
    <span className={clsx('ent-ref', className)} data-kind={head.kind}>
      {body}
    </span>
  ) : (
    <a className={clsx('ent-ref', className)} data-kind={head.kind} href={href}>
      {body}
    </a>
  )
}
