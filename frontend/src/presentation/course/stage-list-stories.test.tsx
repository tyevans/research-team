import { composeStories } from '@storybook/react-vite'
import { render, screen } from '@testing-library/react'
import { expect, it } from 'vitest'

import * as stories from './StageList.stories.tsx'

/** The rail shows what the preset declared, not what the log recorded.
 *
 * `StageList.tsx` states it: "a rail built from what happened can only show
 * what happened, and the question this answers is what was *supposed* to."
 * `AFullPreset` is fifteen stages with two run, and a build that listed only
 * what had run would show two -- which is a rail that looks complete and
 * answers a different question.
 *
 * The accessible name carries the count, and that is not decoration: the row
 * is a `<button>`, `Tooltip`'s wrapper is another one, so "4/6" and the em
 * dash cannot be expanded for a reader who needs them expanded. They are said
 * in full in `aria-label` instead. Asserting the label rather than the visible
 * text is therefore asserting the thing the component actually promises.
 *
 * **Proved red** two ways, and the first is less surgical than it first
 * looked. Filtering `course.stages` to `status !== 'upcoming'` fails **three**
 * of the five, not one: `AFullPreset` drops from 15 rows to 2, and
 * `EveryStatus` and `ArtifactCounts` both lose rows too, because most of their
 * fixtures are upcoming stages. That is the fixtures being realistic rather
 * than the assertions being redundant -- an upcoming stage is what most of a
 * preset is at any moment -- but the earlier draft of this note claimed the
 * first test failed alone, and it does not.
 *
 * The second is surgical: replacing the em-dash branch with `0 of 0` fails the
 * count test and nothing else.
 *
 * Not asserted: the status *colours*. They are `rail-dot rail-${status}` and
 * `Chip tone={status}`, whose computed values jsdom does not resolve. What is
 * asserted is that a status the build has never seen still renders a row --
 * which is the half that would silently lose a stage.
 */
const { EveryStatus, ArtifactCounts, AFullPreset, NoGate, GatesAndReports } =
  composeStories(stories)

const rows = () => document.body.querySelectorAll('li.rail-item')

it('lists every declared stage, not only the ones that have run', () => {
  render(<AFullPreset />)
  expect(rows()).toHaveLength(15)
})

/** A status this build has never heard of still gets a row.
 *
 *  `unknown` is what a preset grown on the server produces against a console
 *  that has not been rebuilt. Dropping it would lose a stage silently, which
 *  is the same failure the `Findings` list guards against for severities. */
it('renders a stage whose status this build does not recognise', () => {
  render(<EveryStatus />)
  expect(rows()).toHaveLength(4)
  expect(screen.getByText('A stage from a newer preset')).toBeInTheDocument()
})

/** The counts, in the accessible name, including the case that is not a
 *  number. */
it('says the artifact count in full, and says when there is none to say', () => {
  render(<ArtifactCounts />)
  expect(
    screen.getByRole('button', { name: /Part written.*4 of 6 declared artifacts written/ }),
  ).toBeInTheDocument()
  expect(
    screen.getByRole('button', { name: /Declares none.*declares no artifact of its own/ }),
  ).toBeInTheDocument()
})

/** A gate a person answers, readable before they are standing at it. */
it('names the gate decisions on an opened stage', () => {
  render(<GatesAndReports />)
  expect(screen.getByText(/approve · revise · halt/)).toBeInTheDocument()
  expect(screen.getByText(/instructional designer/)).toBeInTheDocument()
})

/** A labelled row with nothing after it reads as a gate whose decisions failed
 *  to load, so the row is absent rather than empty. */
it('draws no gate row for a stage that has none', () => {
  const { container } = render(<NoGate />)
  expect(container.querySelector('.rail-detail')).not.toBeNull()
  expect(container.querySelector('.rail-gate')).toBeNull()
})
