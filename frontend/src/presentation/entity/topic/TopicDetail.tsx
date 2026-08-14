import type { ReactNode } from 'react'

import type { TopicDetail as TopicDetailView } from '@domain/research/topic.ts'

import { EntityStatus } from '../EntityStatus.tsx'

/** The `Detail` density: the sole occupant of a region.
 *
 * It may scroll, it owns its headings, and it is the only density allowed to
 * render fields no list shows. That last clause is the whole reason this
 * component exists, and it closes a specific, documented gap.
 *
 * **`TopicList.tsx` fetches the detail fresh because the manage panel needs
 * the rationale and the scope. That panel renders neither.** R-F3.10 counts
 * five fields fetched by what is now `TopicManagePane` and rendered nowhere in
 * `presentation/`: `rationale`, `scope`, `sourceIds`, `findingNotes` and
 * `contested` — the largest unrendered field set the research report found. A
 * comment describing behaviour the code does not have is worse than no
 * comment, because it is believed. All five are rendered here.
 *
 * **Still true of the pane today, and this component is still the only place
 * any of the five is rendered — nothing mounts it yet.** `TopicDetail` is
 * imported by its own test and by `Topic.stories.tsx` and by no component, so
 * the gap R-F3.10 named is closed in the workbench and open in the console.
 *
 * The panel also once rendered the question as `<h3 className="drawer-title">`
 * — the `Drawer` component's own heading class, in a file that did not use
 * `Drawer` — while the queue rendered the same field as
 * `<div className="topic-question">`: two markups for one entity sharing no
 * class name at all. Both halves have since moved (the pane's heading is
 * utilities, the row's class is `.ent-topic-question`), so the specific
 * mismatch is gone; the reason it argued for — one entity, one markup, owned
 * here — is why this component looks the way it does.
 *
 * Not a dialog. `Detail` is a density, not a container: the same component
 * belongs in a region on the research page and inside an overlay, and a
 * component that assumed a dialog could not be put in a pane. The overlay, if
 * there is one, is the caller's.
 */
export const TopicDetail = ({
  topic,
  slots = {},
}: {
  topic: TopicDetailView
  slots?: Partial<{
    /** Status changes and their mandatory justification — the view's, because
     *  the mutation and the reason it is required both live in a hook. */
    actions: ReactNode
    /** Sub-questions, which are their own entity with their own row and their
     *  own mutation. A slot rather than a nested render, so this component
     *  does not acquire a dependency on a thing that resolves them. */
    subQuestions: ReactNode
  }>
}) => (
  <article className="ent-topic-detail" data-topic={topic.topicId}>
    <header className="ent-topic-detail-head">
      {/* `h2`, not the drawer's `h3`: the heading level is a property of the
          document this is placed in, and a detail is the top of its region.
          The old markup borrowed a class from a component it does not use,
          which is how the level got decided by a stylesheet. */}
      <h2 className="ent-topic-detail-question">{topic.question}</h2>
      <EntityStatus status={topic.status} />
      {/* `isBlocked` was read by nowhere in this component, so a blocked topic
          looked exactly like an open one — `TopicRow` says it with a red left
          border, and a detail has no rows to border. Said in words here, which
          is the better half of the pair anyway: the row is scanned and the
          detail is read.

          A chip rather than a fourth section, and beside the status rather
          than under it, because both of these are the answer to "what state is
          this in" — the thing a reader looks at the top of a detail to learn.
          `triggers` below says *why*, and only when the server sent a reason. */}
      {topic.isBlocked ? <EntityStatus status="blocked" /> : null}
      {topic.contested ? <EntityStatus status="contested" detail="findings disagree" /> : null}
      {slots.actions}
    </header>

    {/* The two fields the comment promised and the manage pane never shows. Each
        renders only when present: an empty `rationale` is a topic somebody
        opened in a hurry, and a heading over nothing is worse than silence. */}
    {topic.rationale.trim().length > 0 ? (
      <section className="ent-topic-section">
        <h3>Why this is being asked</h3>
        <p>{topic.rationale}</p>
      </section>
    ) : null}

    {topic.scope.trim().length > 0 ? (
      <section className="ent-topic-section">
        <h3>What counts as an answer</h3>
        <p>{topic.scope}</p>
      </section>
    ) : null}

    <section className="ent-topic-section">
      <h3>Findings</h3>
      {/* The count and the prose, both. They are separate wire fields --
          `findings` an int, `finding_notes` a list -- and `presenters.py`
          carries a comment warning that the two collide by name. A reader
          wants the number and what it says; neither can be reconstructed from
          the other. */}
      <p className="ent-topic-count">
        {topic.findings} {topic.findings === 1 ? 'finding' : 'findings'} from {topic.sources}{' '}
        {topic.sources === 1 ? 'source' : 'sources'}
      </p>
      {topic.findingNotes.length > 0 ? (
        <ul className="ent-topic-notes">
          {topic.findingNotes.map((note) => (
            <li key={note}>{note}</li>
          ))}
        </ul>
      ) : (
        // Says what to do next rather than only that there is nothing —
        // "empty states that do not say what to do next" is a named defect in
        // two of the four reports.
        <p className="ent-topic-empty">
          Nothing recorded yet. Investigating this topic is what writes findings here.
        </p>
      )}
    </section>

    {topic.triggers.length > 0 ? (
      <section className="ent-topic-section">
        <h3>Why this needs attention</h3>
        <ul className="ent-topic-triggers">
          {topic.triggers.map((trigger) => (
            <li key={trigger}>{trigger}</li>
          ))}
        </ul>
      </section>
    ) : null}

    <section className="ent-topic-section">
      <h3>Sub-questions</h3>
      {slots.subQuestions ?? (
        <p className="ent-topic-empty">
          {topic.openSubQuestions} open of {topic.subQuestions.length}.
        </p>
      )}
    </section>

    {/* Ids rather than document names, and deliberately so: naming them means
        reading the corpus, and this component may not fetch. A view that has
        the corpus in hand passes `EntityRef`s through a slot instead. Showing
        the ids is still worth more than showing nothing, which is what
        happens today. */}
    {topic.sourceIds.length > 0 ? (
      <section className="ent-topic-section">
        <h3>Sources</h3>
        <ul className="ent-topic-sources">
          {topic.sourceIds.map((id) => (
            <li key={id} className="ent-topic-source-id">
              {id}
            </li>
          ))}
        </ul>
      </section>
    ) : null}
  </article>
)
