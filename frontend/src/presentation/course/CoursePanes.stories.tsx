import type { Meta, StoryObj } from '@storybook/react-vite'
import { useState } from 'react'

import { allArtifacts, writtenCount } from '@domain/project/course.ts'

import { Pane } from '../layout/Pane.tsx'
import type { Track } from '../layout/split-tracks.ts'
import { Split } from '../layout/Split.tsx'
import { ArtifactList } from './ArtifactList.tsx'
import { StageList, stagesLeftBehind } from './StageList.tsx'
import { artifact, course, stage } from './course-fixtures.ts'

/** The two columns, declared here rather than imported.
 *
 * They were `COURSE_TRACKS` in `use-course.ts`, which died with `CourseView`.
 * These stories outlive that page because they are not about it: they are the
 * only place `StageList` and `ArtifactList` render real content side by side
 * with no `QueryClientProvider` around them, and deleting five assertions to
 * remove one import would have been a bad trade. So the pair keeps a workbench,
 * and the workbench owns its own geometry.
 *
 * The numbers are unchanged -- `minmax(0, 1fr) minmax(0, 1.2fr)`, the artifact
 * column wider because its rows carry a provenance line where the rail's carry
 * a name and a count. A `min` of 0 rather than a pixel floor so a narrow column
 * reflows instead of forcing a horizontal scrollbar.
 */
const PANE_TRACKS: readonly Track[] = [
  { id: 'stages', min: 0, weight: 1 },
  { id: 'artifacts', min: 0, weight: 1.2 },
]

/** The course page's two panes, side by side, which is the only way to see the
 *  thing they are for: a rail saying where the run is against a list saying
 *  what it has produced.
 *
 * `Split` and `Pane` are real here rather than stubbed, because the layout is
 * half of what these stories are showing -- the fold, the meta counts, and the
 * fact that a folded pane becomes a 34px rail with its title on its side. None
 * of that is assertable in jsdom, which is exactly why it earns a story.
 */
const meta: Meta = {
  title: 'course/CoursePanes',
  parameters: { layout: 'fullscreen' },
}

export default meta

type Story = StoryObj

const Panes = ({ data = course() }: { data?: ReturnType<typeof course> }) => {
  const [collapsed, setCollapsed] = useState<ReadonlySet<string>>(new Set())
  const [openStage, setOpenStage] = useState<string | null>(null)
  const slots = allArtifacts(data)

  return (
    <section className="view">
      <Split
        id="course"
        label="Course panes"
        tracks={PANE_TRACKS}
        collapsed={collapsed}
        onCollapsedChange={setCollapsed}
      >
        <Pane
          id="stages"
          label="Stages"
          meta={`${String(stagesLeftBehind(data))} of ${String(data.stageCount)} left behind`}
        >
          <StageList
            course={data}
            openStage={openStage}
            onToggleStage={(id) => {
              setOpenStage((current) => (current === id ? null : id))
            }}
          />
        </Pane>
        {/* Computed, from the same two calls `CourseView` makes. It was the
            literal "2 of 4 written" on all three stories, which read over a
            pane whose body said the workflow declares no artifacts at all, and
            over another whose rail beside it counted 3 of 3. A story that
            contradicts itself teaches the reader to distrust the render. */}
        <Pane
          id="artifacts"
          label="Artifacts"
          meta={`${String(writtenCount(slots))} of ${String(slots.length)} written`}
        >
          <ArtifactList course={data} />
        </Pane>
      </Split>
    </section>
  )
}

/** A run part-way through: one stage behind it, one current with a gate and a
 *  half-written pair of artifacts, two ahead. The missing artifacts are dimmed
 *  rather than hidden -- hiding them loses the gap the page exists to
 *  surface. */
export const Course: Story = { render: () => <Panes /> }

/** A workflow that declares no artifacts at all. "Nothing here is missing" is
 *  the distinction worth drawing: a preset naming no outputs is not a run that
 *  failed to produce any. */
export const NoArtifacts: Story = {
  render: () => (
    <Panes
      data={course({
        stages: [
          stage({ outputs: [] }),
          stage({ index: 2, id: 'step1.framing', name: 'Framing', status: 'current', outputs: [] }),
        ],
      })}
    />
  ),
}

/** Every artifact written, and none of them claiming anything. `claims
 *  nothing` is the state the contract exists to make visible: an artifact with
 *  neither a source nor an admission of inference is indistinguishable from
 *  one never checked against anything. */
export const ArtifactsClaimingNothing: Story = {
  render: () => (
    <Panes
      data={course({
        stages: [
          stage({
            outputs: [
              artifact({
                provenance: { sources: [], inferred: false, unreadable: 0, empty: true },
              }),
              artifact({ path: 'course/intake/scope.md', hasFrontmatter: false }),
              artifact({
                path: 'course/intake/notes.md',
                missingFields: ['title', 'rests_on'],
                provenance: { sources: [], inferred: true, unreadable: 2, empty: false },
              }),
            ],
          }),
        ],
      })}
    />
  ),
}
