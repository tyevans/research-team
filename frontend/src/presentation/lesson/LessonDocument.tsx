import type { AttemptsApi } from '@application/lesson/use-attempts.ts'
import type { ComponentBlock, LessonDocument as Doc } from '@domain/lesson/document.ts'

import { Markdown } from '../common/content.tsx'
import { Checklist } from './Checklist.tsx'
import { Cloze } from './Cloze.tsx'
import { Flashcards } from './Flashcards.tsx'
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
export const LessonDocument = ({ doc, attempts }: { doc: Doc; attempts: AttemptsApi }) => (
  <div className="md doc">
    {doc.blocks.map((block, index) =>
      block.kind === 'markdown' ? (
        <Markdown key={index} source={block.text} className="md-unwrapped" />
      ) : (
        <Component key={block.id} block={block} attempts={attempts} />
      ),
    )}
  </div>
)

const RENDERERS: Readonly<
  Record<string, (props: { block: ComponentBlock; attempts: AttemptsApi }) => React.ReactElement>
> = {
  flashcards: Flashcards,
  mcq: Mcq,
  cloze: Cloze,
  checklist: Checklist,
}

const Component = ({ block, attempts }: { block: ComponentBlock; attempts: AttemptsApi }) => {
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
          <span
            className="cmp-withheld"
            title={
              'The answer key was removed from this response and is graded on the server. ' +
              'The raw file is still readable from the source toggle, so this keeps answers ' +
              'off the page rather than out of reach.'
            }
          >
            answers withheld
          </span>
        ) : null}
      </div>
      <Renderer block={block} attempts={attempts} />
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
