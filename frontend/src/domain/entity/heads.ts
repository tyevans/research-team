import type { Project } from '../project/project.ts'
import type { TopicDetail, TopicView } from '../research/topic.ts'
import type { SessionSummary } from '../session/session.ts'
import type { EntityHead } from './entity-head.ts'

/** The entity envelope, derived rather than sent, in the one place that
 *  derives it.
 *
 * **Client-side rather than server-side, and that is a cost decision made with
 * eyes open.** `presenters.py` writes fourteen views and none carries a common
 * head. Adding `{kind, id, label}` there is the more correct answer — the wire
 * would describe entities the same way for every consumer, and a second client
 * or a CLI would get it for free rather than reimplementing this file. It
 * costs fourteen presenter changes and their tests. This costs one function
 * per entity and no Python at all. The cheaper arm is taken, and it is chosen
 * for cost rather than for correctness.
 *
 * **Keeping the reversal cheap is why this module exists as a module.** Every
 * derivation is here and nothing else constructs an `EntityHead`. Moving
 * server-side is then: add the three keys to the presenters, add them to the
 * DTO schemas, carry them through `mappers.ts` onto the domain types, and
 * replace each function below with a field read — then delete the file when
 * the last one is a passthrough. **No component changes**, because no
 * component knows where its head came from. Spread across the components that
 * need one, that migration is a rewrite instead of a deletion.
 *
 * **Domain rather than `infrastructure/http/dto.ts`, which is where the design
 * put it.** That placement does not survive contact with this codebase: `dto.ts`
 * holds wire schemas, `mappers.ts` converts them to domain types, and **no
 * module under `presentation/` or `domain/` imports either** — components are
 * handed domain types and never see a DTO. A head derived from a DTO would
 * therefore have nowhere to go. Deriving from domain types puts it where the
 * components actually are, and costs the reversal nothing: when the wire grows
 * the envelope, `mappers.ts` is what reads it, which is the layer whose job
 * that already is. The design's client-side-versus-server-side argument is
 * untouched; only the file is different.
 */

export const projectHeadOf = (project: Project): EntityHead => ({
  kind: 'project',
  id: project.id,
  label: project.name,
})

/** A session has no name, and inventing one would be worse than admitting it:
 *  `EntityRef` renders the short id in monospace when the label is null, which
 *  makes the console's existing convention visible instead of implicit.
 *
 *  `firstMessage` is deliberately **not** used as a label. It is the opening
 *  prompt, frequently a paragraph, and a reference that expands to a paragraph
 *  is not a reference. The landing page shows it as a session's *preview*,
 *  which is a different job from naming it. */
export const sessionHeadOf = (session: SessionSummary | string): EntityHead => ({
  kind: 'session',
  id: typeof session === 'string' ? session : session.id,
  label: null,
})

/** A topic's question is its name — the one presentable whose label is a
 *  sentence. `EntityRef` truncates by CSS rather than by slicing the string,
 *  because a sliced string cannot be recovered for a `title`, and a topic's
 *  question is exactly the thing a reader hovers to read in full. */
export const topicHeadOf = (topic: TopicView | TopicDetail): EntityHead => ({
  kind: 'topic',
  id: topic.topicId,
  label: topic.question,
})
