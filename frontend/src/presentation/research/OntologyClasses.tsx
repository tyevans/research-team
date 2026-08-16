import type { OntologyClass, OntologyMember } from '@domain/knowledge/ontology.ts'
import { childrenOf } from '@domain/knowledge/ontology.ts'

import { EmptyState } from '../common/primitives.tsx'

/** Discovered classes, drawn so a reader can decide whether to believe them.
 *
 * **Why this exists at all, when the classes are already on the canvas.** A
 * force-directed drawing cannot show order. Five `instance_of` spokes into a
 * `Rank` hub are five identical lines whether or not the ranks form a scale --
 * the ordinal is in the data and invisible there. So `kind` selects the layout
 * here, and that is the whole justification for a second surface.
 *
 * Everything on this screen is derived: a model read a document and proposed
 * these groupings. The design follows from that one fact rather than from a
 * house style, and it makes three promises.
 *
 * 1. Every class can be opened at the sentence it came from. Not quoted
 *    inline -- quoted text proves the model wrote a sentence, where opening
 *    the document proves the sentence is *in* it, which is the different and
 *    stronger claim.
 * 2. Every class shows its own arithmetic. "2 of 6 stated" is a claim the
 *    reader can check against the sentence in front of them, and the shortfall
 *    is stated rather than smoothed away.
 * 3. Nothing derived is drawn like something asserted. The dashed rule is the
 *    same visual language `--link-inferred` gives the dashed edges on the
 *    canvas, so a reader learns "this was derived" once.
 *
 * What is deliberately absent is an accept/reject control. Judging a class
 * wrong and recording that judgement are different features, and a human
 * verdict living in a derived view is the confusion this whole layer is
 * arranged to avoid.
 */

/** Left rule dashed, not solid: the same "derived" language the canvas uses
 *  for inferred edges. `border-0` first is not optional -- this build imports
 *  no preflight, so `border-dashed` with only `border-l-2` giving a width
 *  would draw the browser's ~3px default on the other three sides, and a rule
 *  meant for one edge would draw a box. No gate catches it. */
const CARD = [
  'border-0 border-l-2 border-dashed border-l-line-strong',
  'mb-3 rounded-md bg-bg-panel-2 px-3 py-2',
].join(' ')

/** An ordered scale's member: the ordinal is shown because it *is* the
 *  information -- `D C B A S` is not recoverable from anything else on the
 *  row, and a scale drawn without it is a bag with extra steps. */
const SCALE_MEMBER = 'flex items-baseline gap-1.5 rounded bg-bg-raise px-2 py-1 text-sm'

/** A set's member: no number, deliberately. A reader shown `01 02 03` beside
 *  an unordered set would read a sequence the document never stated. */
const SET_MEMBER = 'rounded bg-bg-raise px-2 py-1 text-sm'

const Checksum = ({ klass }: { klass: OntologyClass }) => {
  if (klass.declaredCount === null) {
    // No count to check against. Saying "6 members" here would look like a
    // verification and be nothing of the kind.
    return (
      <span className="text-xs text-fg-faint">
        {klass.members.length} {klass.members.length === 1 ? 'member' : 'members'}
      </span>
    )
  }
  return (
    <span
      className={klass.complete ? 'text-xs text-fg-faint' : 'text-xs text-accent'}
      // Read aloud as a sentence rather than as two numbers and a slash: this
      // is the one element on the card a reader is meant to act on.
      title={
        klass.complete
          ? 'Every member the document counted was found.'
          : 'The document counted more members than this pass found. See what was rejected below.'
      }
    >
      {klass.members.length} of {klass.declaredCount} stated
    </span>
  )
}

const Members = ({ klass }: { klass: OntologyClass }) => {
  if (klass.kind === 'ordered_scale') {
    return (
      <ol className="gap-1.5 m-0 flex list-none flex-wrap items-center p-0">
        {klass.members.map((member: OntologyMember) => (
          <li key={member.name} className={SCALE_MEMBER}>
            {member.ordinal !== null && (
              <span className="text-xs text-fg-faint tabular-nums">{member.ordinal}</span>
            )}
            <span>{member.name}</span>
          </li>
        ))}
      </ol>
    )
  }
  return (
    <ul className="gap-1.5 m-0 flex list-none flex-wrap p-0">
      {klass.members.map((member) => (
        <li key={member.name} className={SET_MEMBER}>
          {member.name}
        </li>
      ))}
    </ul>
  )
}

const Rejections = ({ klass }: { klass: OntologyClass }) => {
  if (klass.rejectedMembers.length === 0) return null
  return (
    <p className="m-0 mt-2 text-xs text-fg-dim">
      Not in the document:{' '}
      {klass.rejectedMembers.map((rejected, index) => (
        <span key={rejected.name}>
          {index > 0 && ', '}
          <span className="text-fg">{rejected.name}</span> ({rejected.reason})
        </span>
      ))}
    </p>
  )
}

const ClassCard = ({
  klass,
  classes,
  sourceHref,
}: {
  klass: OntologyClass
  classes: readonly OntologyClass[]
  sourceHref: (evidence: OntologyClass['evidence']) => string
}) => {
  const children = childrenOf(classes, klass.id)
  return (
    <li className={CARD}>
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h3 className="font-semibold m-0 text-sm text-fg">{klass.name}</h3>
        <div className="flex items-baseline gap-3">
          <Checksum klass={klass} />
          <a className="text-xs text-fg-dim underline" href={sourceHref(klass.evidence)}>
            {/* Names the document, because a reader with several open needs to
                know which one this came from before deciding to follow it. */}
            evidence in {klass.evidence.sourceId}
          </a>
        </div>
      </div>
      {klass.stale && (
        <p className="m-0 mt-1 mb-1 text-xs text-fg-dim">
          {/* Shown, not hidden: the text still describes something, and a
              reader deciding whether to trust it needs to know the graph moved
              underneath it. */}
          Re-extracted since this was found. Run the pass again to refresh it.
        </p>
      )}
      <div className="mt-2">
        <Members klass={klass} />
      </div>
      <Rejections klass={klass} />
      {children.length > 0 && (
        <ul className="m-0 mt-3 list-none p-0 pl-3">
          {children.map((child) => (
            <ClassCard key={child.id} klass={child} classes={classes} sourceHref={sourceHref} />
          ))}
        </ul>
      )}
    </li>
  )
}

export const OntologyClasses = ({
  classes,
  sourceHref,
}: {
  classes: readonly OntologyClass[]
  /** Where to send a reader who wants to check a class against its source.
   *  Injected rather than built here, so this component knows nothing about
   *  routing and can be rendered in a test without one. */
  sourceHref: (evidence: OntologyClass['evidence']) => string
}) => {
  if (classes.length === 0) {
    return (
      <EmptyState
        heading="No classes found yet"
        detail="Run a discovery pass over a document to find the groups it states."
      />
    )
  }
  return (
    <ul className="m-0 list-none p-0">
      {childrenOf(classes, null).map((klass) => (
        <ClassCard key={klass.id} klass={klass} classes={classes} sourceHref={sourceHref} />
      ))}
    </ul>
  )
}
