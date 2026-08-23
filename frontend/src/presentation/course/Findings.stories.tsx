import type { Meta, StoryObj } from '@storybook/react-vite'

import type { Finding } from '@domain/project/course.ts'

import { course } from './course-fixtures.ts'
import { Findings } from './Findings.tsx'

/** What the current stage's checks say, and the distinction the list exists to
 *  keep.
 *
 * **Two of the five severities are not defects.** `course.ts` spells it out:
 * `human_gate` and `critic_gate` "mark work no run can clear by itself.
 * Spelling them out keeps a reader from filing them with the failures just
 * because they arrived in the same list." `EverySeverity` is the only place
 * that separation can be judged — one at a time, a gate and a blocking finding
 * are two rows with different words on them.
 *
 * The edges carry it. `invariant` gets the loud one, because an invariant
 * fails invisibly: there is nothing for a person to look at and no judgement
 * to make. The two gates get their own colours, deliberately not a failure's.
 * And a severity the map has never seen falls back to the plain line —
 * reviewer prompts author these strings, so an unknown one is expected rather
 * than exceptional, and it must not read as the worst case by default.
 *
 * **`unimplemented` is not a severity**, which is the second thing worth
 * seeing. It is a gap in the preset, not a verdict about the work, and it
 * takes the fallback edge for that reason. `Unimplemented` shows it alone,
 * because a course with no findings *and* unimplemented checks is a real state
 * — the list draws for it, where it draws nothing at all when both are empty.
 *
 * **`open` marks the row a link named.** `#/p/<id>/finding/<check>` parsed and
 * opened this tab for several slices with the id dropped, so a link to one
 * finding produced an unmarked list of all of them. Matched on `check` rather
 * than an index, because a `Finding` has no id and the list is recomputed
 * against a course that grows. `TwoFromOneCheck` is the cost of that, shown
 * rather than hidden: two findings from one check both mark.
 */
const meta: Meta = {
  title: 'course/Findings',
}

export default meta

type Story = StoryObj

const finding = (over: Partial<Finding> & { check: string }): Finding => ({
  severity: 'advisory',
  message: 'The outline names four sections and the objectives cover three.',
  cites: [],
  suggestedEdit: null,
  ...over,
})

const Frame = ({ heading, children }: { heading: string; children: React.ReactNode }) => (
  <section style={{ padding: 'var(--space-3)', maxWidth: 680 }}>
    <h3 style={{ font: 'inherit', color: 'var(--fg-faint)', margin: '0 0 var(--space-2)' }}>
      {heading}
    </h3>
    {children}
  </section>
)

/** **All five, plus an unknown one.** The comparison the separation needs.
 *
 *  Read down the edges. One is loud; two are gates and must not read as
 *  failures; one is advisory; and the last is a severity nobody has written a
 *  rule for, which falls back to the plain line rather than to the worst
 *  case. */
export const EverySeverity: Story = {
  render: () => (
    <Frame heading="every severity, and one the map has never seen">
      <Findings
        course={course({
          findings: [
            finding({
              check: 'objectives.cover_outline',
              severity: 'invariant',
              message: 'An objective references a section the outline does not contain.',
            }),
            finding({
              check: 'outline.section_count',
              severity: 'blocking',
              message: 'The outline has two sections; the preset asks for at least four.',
            }),
            finding({
              check: 'objectives.verb_variety',
              severity: 'advisory',
              message: 'Six of eight objectives open with the same verb.',
            }),
            finding({
              check: 'framing.reviewed_by_a_person',
              severity: 'human_gate',
              message: 'This stage is held for a reader to approve before it advances.',
            }),
            finding({
              check: 'framing.critic_pass',
              severity: 'critic_gate',
              message: 'A critic pass has not run against this stage yet.',
            }),
            finding({
              check: 'framing.something_new',
              severity: 'idiosyncratic',
              message: 'A severity this build has never heard of, authored by a prompt.',
            }),
          ],
        })}
      />
    </Frame>
  ),
}

/** Checks the preset names and this build does not implement.
 *
 *  A gap in the preset, not a verdict — so it takes the fallback edge and is
 *  kept out of the severities above it. Shown with no findings at all, because
 *  that is a state the list draws for: it returns `null` only when *both* are
 *  empty. */
export const Unimplemented: Story = {
  render: () => (
    <Frame heading="no findings, but checks the preset asked for and this build lacks">
      <Findings
        course={course({
          findings: [],
          unimplementedChecks: ['outline.reading_level', 'objectives.bloom_coverage'],
        })}
      />
    </Frame>
  ),
}

/** Both at once, which is what a mid-preset stage usually looks like. */
export const FindingsAndUnimplemented: Story = {
  render: () => (
    <Frame heading="findings and gaps together">
      <Findings
        course={course({
          findings: [
            finding({ check: 'objectives.verb_variety' }),
            finding({
              check: 'outline.section_count',
              severity: 'blocking',
              message: 'The outline has two sections; the preset asks for at least four.',
            }),
          ],
          unimplementedChecks: ['outline.reading_level'],
        })}
      />
    </Frame>
  ),
}

/** One row marked, because a link named its check. */
export const OneRowOpen: Story = {
  render: () => (
    <Frame heading="linked to one check">
      <Findings
        open="outline.section_count"
        course={course({
          findings: [
            finding({ check: 'objectives.verb_variety' }),
            finding({
              check: 'outline.section_count',
              severity: 'blocking',
              message: 'The outline has two sections; the preset asks for at least four.',
            }),
            finding({ check: 'objectives.cover_outline', severity: 'invariant' }),
          ],
        })}
      />
    </Frame>
  ),
}

/** **The cost of matching on `check`, shown rather than hidden.**
 *
 *  A `Finding` has no id, and the array index is not stable because the list
 *  is recomputed against a course that grows — so the check name is the only
 *  thing a link can name. Two findings from one check therefore both mark.
 *  That is the honest answer for a link that names a check, and it beats
 *  marking the wrong single row. */
export const TwoFromOneCheck: Story = {
  render: () => (
    <Frame heading="one check, two findings — both mark">
      <Findings
        open="outline.section_count"
        course={course({
          findings: [
            finding({
              check: 'outline.section_count',
              severity: 'blocking',
              message: 'The outline has two sections; the preset asks for at least four.',
            }),
            finding({
              check: 'outline.section_count',
              severity: 'advisory',
              message: 'The second section carries most of the material.',
            }),
            finding({ check: 'objectives.verb_variety' }),
          ],
        })}
      />
    </Frame>
  ),
}

/** Nothing to say. The list draws **nothing at all** — not a heading over an
 *  empty region, which would read as a table that failed to load. */
export const NothingToReport: Story = {
  render: () => (
    <Frame heading="no findings and no gaps — the whole list is absent">
      <Findings course={course({ findings: [], unimplementedChecks: [] })} />
    </Frame>
  ),
}
