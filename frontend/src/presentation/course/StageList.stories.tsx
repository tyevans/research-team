import type { Meta, StoryObj } from '@storybook/react-vite'

import type { StageProgress } from '@domain/project/course.ts'

import { artifact, course, stage } from './course-fixtures.ts'
import { StageList } from './StageList.tsx'

/** Every stage the preset declares, whichever have run.
 *
 * `StageList.tsx` states the rule and it is the reason the rail exists at all:
 * **a rail built from what happened can only show what happened, and the
 * question this answers is what was *supposed* to.** So the list comes from
 * the preset rather than from the log, and a course two stages in still shows
 * every stage after them.
 *
 * `EveryStatus` is where that is checkable. `CoursePanes` already renders this
 * component, but only ever with `done` and `current` — the two a running
 * course happens to have — so `upcoming` and `unknown` had no page at all.
 * `unknown` matters more than it looks: it is what a preset grown on the
 * server produces against a console that has not been rebuilt, and a status
 * this build has never heard of must read as neutral rather than as a fault.
 *
 * Two other things worth one page each:
 *
 * - **Written-of-declared, not a percentage.** A stage owing two artifacts
 *   with one written is a specific situation and "50%" is not. A stage that
 *   declares none shows an em dash rather than `0/0`, which would read as a
 *   failure to produce something nobody asked for.
 * - **`halt` is worth seeing in advance.** The domain says why: "the pipeline
 *   is structurally biased toward producing its own output, and the gates that
 *   can stop it are the counterweight." `GatesAndReports` opens a stage that
 *   can be halted, so the decision is legible before a reader is standing at
 *   it.
 */
const meta: Meta = {
  title: 'course/StageList',
}

export default meta

type Story = StoryObj

const outputs = (written: number, declared: number) =>
  Array.from({ length: declared }, (_, i) =>
    artifact({ path: `course/step/out${String(i)}.md`, present: i < written }),
  )

const rail = (stages: readonly StageProgress[]) => course({ stages })

const Frame = ({ heading, children }: { heading: string; children: React.ReactNode }) => (
  <section style={{ padding: 'var(--space-3)', maxWidth: 420 }}>
    <h3 style={{ font: 'inherit', color: 'var(--fg-faint)', margin: '0 0 var(--space-2)' }}>
      {heading}
    </h3>
    {children}
  </section>
)

/** **All four statuses**, which no running course produces at once.
 *
 *  `unknown` is the one to look at. It is what a preset grown on the server
 *  produces against a console that has not been rebuilt, and it must read as
 *  neutral — a stage nobody has classified is not a stage that failed. */
export const EveryStatus: Story = {
  render: () => (
    <Frame heading="done, current, upcoming, unknown">
      <StageList
        openStage={null}
        onToggleStage={() => undefined}
        course={rail([
          stage({ index: 1, id: 's1', name: 'Intake', status: 'done', outputs: outputs(2, 2) }),
          stage({ index: 2, id: 's2', name: 'Framing', status: 'current', outputs: outputs(1, 3) }),
          stage({
            index: 3,
            id: 's3',
            name: 'Drafting',
            status: 'upcoming',
            outputs: outputs(0, 4),
          }),
          stage({
            index: 4,
            id: 's4',
            name: 'A stage from a newer preset',
            status: 'unknown',
            outputs: outputs(0, 1),
          }),
        ])}
      />
    </Frame>
  ),
}

/** **The counts, including the two that are not numbers.**
 *
 *  `4/6` is short and marked as such. `6/6` is complete. `—` is a stage that
 *  declares no artifact of its own, and is deliberately not `0/0` — which
 *  would read as a failure to produce something nobody asked for. */
export const ArtifactCounts: Story = {
  render: () => (
    <Frame heading="written of declared">
      <StageList
        openStage={null}
        onToggleStage={() => undefined}
        course={rail([
          stage({ index: 1, id: 'a', name: 'All written', status: 'done', outputs: outputs(6, 6) }),
          stage({
            index: 2,
            id: 'b',
            name: 'Part written',
            status: 'current',
            outputs: outputs(4, 6),
          }),
          stage({
            index: 3,
            id: 'c',
            name: 'None written',
            status: 'upcoming',
            outputs: outputs(0, 6),
          }),
          stage({ index: 4, id: 'd', name: 'Declares none', status: 'upcoming', outputs: [] }),
        ])}
      />
    </Frame>
  ),
}

/** A stage opened, with its gate and its report.
 *
 *  `halt` is in the list on purpose. A reader who meets a gate for the first
 *  time when it stops the run has learnt about it too late; the rail is where
 *  it can be read in advance. */
export const GatesAndReports: Story = {
  render: () => (
    <Frame heading="opened — the gate a person answers">
      <StageList
        openStage="s2"
        onToggleStage={() => undefined}
        course={rail([
          stage({ index: 1, id: 's1', name: 'Intake', status: 'done', outputs: outputs(2, 2) }),
          stage({
            index: 2,
            id: 's2',
            name: 'Framing',
            status: 'current',
            outputs: outputs(1, 3),
            gateDecisions: ['approve', 'revise', 'halt'],
            reviewerRole: 'instructional designer',
            findingsReport: 'course/framing/findings.md',
          }),
          stage({
            index: 3,
            id: 's3',
            name: 'Drafting',
            status: 'upcoming',
            outputs: outputs(0, 4),
          }),
        ])}
      />
    </Frame>
  ),
}

/** A stage with no gate at all. The gate row is absent rather than empty — a
 *  labelled row with nothing after it reads as a gate whose decisions failed
 *  to load. */
export const NoGate: Story = {
  render: () => (
    <Frame heading="opened — no gate">
      <StageList
        openStage="s1"
        onToggleStage={() => undefined}
        course={rail([
          stage({
            index: 1,
            id: 's1',
            name: 'Intake',
            status: 'done',
            outputs: outputs(2, 2),
            gateDecisions: [],
            findingsReport: null,
          }),
        ])}
      />
    </Frame>
  ),
}

/** **The rule, at the length a real preset has it.** Fifteen stages, two run.
 *
 *  A rail built from the log would show two rows here. This shows fifteen,
 *  which is the whole point: a reader can see what the project has committed
 *  to before any of it has happened. */
export const AFullPreset: Story = {
  render: () => (
    <Frame heading="fifteen declared, two run">
      <StageList
        openStage={null}
        onToggleStage={() => undefined}
        course={rail(
          Array.from({ length: 15 }, (_, i) =>
            stage({
              index: i + 1,
              id: `s${String(i + 1)}`,
              name: [
                'Intake',
                'Framing',
                'Three-source analysis',
                'Candidate objectives',
                'Educational screen',
                'Psychology screen',
                'Intent specification',
                'Evidence design',
                'Experience design',
                'Assessment blueprint',
                'Lesson authoring',
                'Media plan',
                'Accessibility pass',
                'Outcome evidence',
                'Defect localisation',
              ][i]!,
              status: i === 0 ? 'done' : i === 1 ? 'current' : 'upcoming',
              outputs: outputs(i === 0 ? 2 : i === 1 ? 1 : 0, (i % 4) + 1),
            }),
          ),
        )}
      />
    </Frame>
  ),
}
