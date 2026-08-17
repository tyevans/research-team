import type { AttemptsApi } from '@application/lesson/use-attempts.ts'
import type { ComponentBlock, LessonDocument as Doc } from '@domain/lesson/document.ts'
import type { ProjectId } from '@domain/shared/identifier.ts'

import { Markdown } from '../common/content.tsx'
import { Tooltip } from '../common/Tooltip.tsx'
import { Checklist } from './Checklist.tsx'
import { Cloze } from './Cloze.tsx'
import { DefinitionWidget } from './DefinitionWidget.tsx'
import { EvidenceWidget } from './EvidenceWidget.tsx'
import { Flashcards } from './Flashcards.tsx'
import { GraphWidget } from './GraphWidget.tsx'
import { Mcq } from './Mcq.tsx'

/** A parsed markdown artifact: prose, and widgets a learner can operate.
 *
 * Three rules hold across all of it, and each is enforced structurally rather
 * than by convention:
 *
 *  - Nothing here grades. The learner projection strips the answer key before
 *    it leaves the server, so the browser genuinely *cannot* mark an attempt.
 *    Submitting posts and renders what comes back.
 *
 *  - Model-authored text reaches the page only through `<Markdown>`, which
 *    sanitises. A component's prose fields are markdown too — an mcq prompt
 *    routinely carries a code span or a list — so they go through the same one.
 *
 *  - Degradation is per block. An unknown type renders as a labelled code
 *    block, a component with errors renders as its own source plus a panel
 *    naming the fields, and neither takes the rest of the document down.
 */
const FILE_WITHHELD_EXPLANATION =
  'The answer key was removed from this response and is graded on the server. ' +
  'The raw file is still readable from the source toggle, so this keeps answers ' +
  'off the page rather than out of reach.'

export const LessonDocument = ({
  doc,
  attempts,
  withheldExplanation = FILE_WITHHELD_EXPLANATION,
  projectId,
}: {
  doc: Doc
  attempts: AttemptsApi
  /** What the "answers withheld" tooltip says the answer key's absence means.
   *  Defaults to the file wording -- "graded on the server, readable from the
   *  source toggle" -- which is true of a lesson file and false of an ask
   *  turn, where the raw answer travels in the *same* response as the blocks.
   *  The ask surface passes its own text rather than this default. */
  withheldExplanation?: string
  /** Optional because the lesson caller has no project in scope -- a course
   *  is read from a session, not a project, and `Markdown` already treats a
   *  missing `projectId` as "leave `[[src:...]]` unexpanded" for exactly that
   *  reason. The ask surface does have one, and passes it: without it, a
   *  reference in the model's prose renders as a working link right up until
   *  the same answer also carries a widget, at which point the identical
   *  `[[src:...]]` prints as literal text -- same answer, two renderings,
   *  decided only by whether a component happened to be present. */
  projectId?: ProjectId
}) => (
  <div className="md doc">
    {doc.blocks.map((block, index) =>
      block.kind === 'markdown' ? (
        // Spread rather than a bare `projectId={projectId}`: `exactOptionalPropertyTypes`
        // treats an explicit `undefined` differently from an omitted prop, and
        // `Markdown`'s own optional `projectId` is what "no project in scope" means.
        <Markdown
          key={index}
          source={block.text}
          className="md-unwrapped"
          {...(projectId ? { projectId } : {})}
        />
      ) : (
        <Component
          key={block.id}
          block={block}
          attempts={attempts}
          withheldExplanation={withheldExplanation}
          {...(projectId ? { projectId } : {})}
        />
      ),
    )}
  </div>
)

const RENDERERS: Readonly<
  Record<
    string,
    (props: {
      block: ComponentBlock
      attempts: AttemptsApi
      /** Optional because a lesson file is read from a session, which has no
       *  project in scope -- see this module's `projectId` prop. A resolved
       *  component handed none renders its `unavailable` state, which is
       *  prose, which is the same answer as every other failure here. */
      projectId?: ProjectId
    }) => React.ReactElement
  >
> = {
  flashcards: Flashcards,
  mcq: Mcq,
  cloze: Cloze,
  checklist: Checklist,
  definition: DefinitionWidget,
  evidence: EvidenceWidget,
  graph: GraphWidget,
}

const Component = ({
  block,
  attempts,
  withheldExplanation,
  projectId,
}: {
  block: ComponentBlock
  attempts: AttemptsApi
  withheldExplanation: string
  projectId?: ProjectId
}) => {
  if (block.unknown) return <UnknownComponent block={block} />
  if (block.errors.length > 0) return <BrokenComponent block={block} />

  const Renderer = RENDERERS[block.type]
  if (!Renderer) return <UnknownComponent block={block} />

  return (
    <section
      className={`cmp cmp-${block.type}`}
      data-component={block.id}
      aria-label={`${block.type} component`}
    >
      <div className="cmp-kind">
        <span className="cmp-kind-name">{block.type}</span>
        {block.withheld.length > 0 ? (
          <Tooltip explanation={withheldExplanation}>
            <span className="cmp-withheld">answers withheld</span>
          </Tooltip>
        ) : null}
      </div>
      {/* Spread rather than a bare `projectId={projectId}`, matching the
          `Markdown` call above: `exactOptionalPropertyTypes` treats an
          explicit `undefined` differently from an omitted prop. */}
      <Renderer block={block} attempts={attempts} {...(projectId ? { projectId } : {})} />
    </section>
  )
}

/** A fenced block naming a type this build does not implement, shown exactly as
 *  an unrecognised fence is — which is the safe failure for a viewer. */
const UnknownComponent = ({ block }: { block: ComponentBlock }) => (
  <pre className="md-code cmp-unknown" data-lang={block.lang ?? undefined}>
    <code>{block.raw}</code>
  </pre>
)

const BrokenComponent = ({ block }: { block: ComponentBlock }) => (
  <section className="cmp cmp-broken">
    <div className="cmp-kind">
      <span className="cmp-kind-name">{block.type}</span>
      <span className="cmp-broken-tag">did not parse</span>
    </div>
    <ul className="cmp-error-list">
      {block.errors.map((error, index) => (
        <li key={index}>
          {error.path ? <code className="cmp-error-path">{error.path}</code> : null}
          <span>{error.message}</span>
        </li>
      ))}
    </ul>
    <pre className="md-code">
      <code>{block.raw}</code>
    </pre>
  </section>
)
