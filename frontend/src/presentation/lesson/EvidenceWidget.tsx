import { useQuery } from '@tanstack/react-query'

import { useContainer } from '@app/container-context.tsx'
import type { AttemptsApi } from '@application/lesson/use-attempts.ts'
import { queryKeys } from '@application/queries/keys.ts'
import { resolvedWidgetQuery } from '@application/queries/resolved-widget.ts'
import type { ComponentBlock } from '@domain/lesson/document.ts'
import type { EvidenceSource } from '@domain/lesson/widgets.ts'
import { readEvidence } from '@domain/lesson/widgets.ts'
import type { ProjectId, SourceId } from '@domain/shared/identifier.ts'

import { Prose } from './widgets.tsx'

/** A claim beside the passages it rests on.
 *
 * The one resolved type with nothing to resolve: source ids are already in
 * the authoring model's context via `[[src:...]]`, so this takes them
 * directly and uses none of `useEntityReference`. Its "no project in scope"
 * state is drawn here rather than by `ResolvedFrame`, because there is no
 * entity reference for a frame to frame -- the claim itself is the prose it
 * degrades to.
 *
 * `attempts` is in the signature and unused, for `DefinitionWidget`'s reason:
 * every entry in `RENDERERS` takes it, and a resolved component is not
 * gradeable.
 *
 * The cost the spec states plainly and this widget does not prevent: a model
 * can write a claim the excerpt does not support. Making that visible is the
 * point. Prose can do the same today and nothing shows the reader.
 */
export const EvidenceWidget = ({
  block,
  projectId,
}: {
  block: ComponentBlock
  attempts: AttemptsApi
  projectId?: ProjectId
}) => {
  const evidence = readEvidence(block)

  return (
    <div className="cmp-body">
      {/* No `cmp-claim` class: it would have no rule in `components.css`, and
          a class in the attribute with nothing in the bundle is
          indistinguishable from one that works -- the same call
          `DefinitionWidget` makes about `cmp-definition-text`. */}
      <Prose text={evidence.claim} />
      <ol className="cmp-evidence-list">
        {evidence.sources.map((source, index) => (
          // Indexed rather than keyed by `source.source`: two entries may
          // quote two ranges of the same document, which is the ordinary case
          // for a claim resting on one long source.
          <li key={index}>
            {/* Narrowed at the call site rather than cast inside `Passage`,
                copying `DefinitionWidget`: TypeScript carries the guarantee
                that a fetch only happens with a project in scope, instead of
                a comment claiming it. */}
            {projectId ? (
              <Passage projectId={projectId} source={source} />
            ) : (
              <span className="cmp-ref-note">{source.source}</span>
            )}
          </li>
        ))}
      </ol>
    </div>
  )
}

/** Split out so `useQuery` is mounted per passage and only once there is a
 *  project to read from -- a hook cannot be called conditionally, and a list
 *  of sources needs one query each anyway. */
const Passage = ({ projectId, source }: { projectId: ProjectId; source: EvidenceSource }) => {
  const { documents } = useContainer()
  // Omitted rather than `undefined`, because absent means "from the start" /
  // "to the end" and `0` would ask for nothing. `exactOptionalPropertyTypes`
  // makes the two genuinely different at the port. The key already carries the
  // same nullable pair, so two ranges over one source stay two cache entries.
  const range = {
    ...(source.start === null ? {} : { start: source.start }),
    ...(source.end === null ? {} : { end: source.end }),
  }

  const passage = useQuery({
    queryKey: queryKeys.document(projectId, source.source as SourceId, range),
    queryFn: () => documents.read(projectId, source.source as SourceId, range),
    // One policy for every resolved widget; the reasoning is in the constant.
    // An invented source id is a 404 forever, so the app-wide `retry: 1`
    // buys a second request and a longer wait before the prose that says so.
    ...resolvedWidgetQuery,
  })

  if (passage.isPending) return <span className="cmp-ref-note">fetching the passage…</span>
  // Quiet prose and no `role="alert"`, matching every other failure in this
  // feature: an invented source id is the ordinary case here, and an error
  // panel would sit on top of the answer's own sentence.
  if (passage.isError || !passage.data) {
    return (
      <span className="cmp-ref-note">
        {source.source} — could not be quoted from this project&rsquo;s corpus
      </span>
    )
  }

  return (
    <figure className="cmp-passage">
      <blockquote>{passage.data.text}</blockquote>
      {/* The offsets the server *served*, not the ones asked for: the route
          clamps rather than refusing, so printing the request beside a
          different excerpt would misdescribe what the reader is looking at. */}
      <figcaption>
        {source.source} {passage.data.start}–{passage.data.end}
      </figcaption>
    </figure>
  )
}
