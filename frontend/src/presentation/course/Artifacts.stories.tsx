import type { Meta, StoryObj } from '@storybook/react-vite'

import type { ArtifactSlot, Provenance } from '@domain/project/course.ts'
import { SourceId } from '@domain/shared/identifier.ts'

import { Artifact } from './Artifacts.tsx'
import { artifact, course } from './course-fixtures.ts'

/** One declared artifact, in the states a naive row would flatten.
 *
 * `Artifacts.tsx` names the rule: an artifact is in "one of four states a
 * naive row would flatten into two: missing; present but with no readable
 * frontmatter; present and claiming sources; present and claiming its thinking
 * was the model's own. **The last two are both legitimate and must not look
 * alike.**"
 *
 * That is a claim about four chip dresses, and `EveryState` is the only place
 * it can be judged. Each dress is a *replacement* for `Chip`'s default trio
 * rather than an addition, because two colour utilities on one element both
 * land in `@layer utilities` and the winner is Tailwind's sort order — so a
 * tone that resolved to nothing would collapse four states into one grey and
 * look like a design decision.
 *
 * **`inferred` is not a defect and must not wear the defect colour.** A stage
 * whose reasoning is its own and says so is working as designed; the flag
 * exists so a reviewer can weigh it. `ClaimsNothing` is the state that *is* a
 * problem — neither a source nor an admission of inference, which the domain
 * calls "indistinguishable from an artifact never checked against anything".
 * Those two are the pair most likely to be conflated, and they are adjacent
 * here for that reason.
 */
const meta: Meta = {
  title: 'course/Artifact',
}

export default meta

type Story = StoryObj

const COURSE = course()

const SPAN = {
  sourceId: SourceId('aaaaaaaa-1111-4111-8111-444444444444'),
  start: 0,
  end: 420,
}

const provenance = (over: Partial<Provenance> = {}): Provenance => ({
  sources: [SPAN],
  inferred: false,
  unreadable: 0,
  empty: false,
  ...over,
})

const slot = (over: Partial<ArtifactSlot> = {}): ArtifactSlot =>
  artifact({ provenance: provenance(), ...over })

const List = ({ children }: { children: React.ReactNode }) => (
  <ul className="m-0 list-none p-0">{children}</ul>
)

const Frame = ({ heading, children }: { heading: string; children: React.ReactNode }) => (
  <section style={{ padding: 'var(--space-3)', maxWidth: 640 }}>
    <h3 style={{ font: 'inherit', color: 'var(--fg-faint)', margin: '0 0 var(--space-2)' }}>
      {heading}
    </h3>
    <List>{children}</List>
  </section>
)

/** **All four, in one column.** The rule is about what these look like
 *  *against each other*, so a single row proves nothing.
 *
 *  Reading down: written-with-sources is the ordinary good case;
 *  written-and-inferred is *also* good and must not read as a fault;
 *  no-frontmatter is a genuine problem; not-written is an absence rather than
 *  a fault. Four states, four treatments, and the two in the middle are the
 *  ones a naive row would merge. */
export const EveryState: Story = {
  render: () => (
    <Frame heading="the four states">
      <Artifact
        course={COURSE}
        slot={slot({ path: 'course/framing/outline.md', artifactType: 'outline' })}
      />
      <Artifact
        course={COURSE}
        slot={slot({
          path: 'course/framing/objectives.md',
          artifactType: 'objectives',
          provenance: provenance({ sources: [], inferred: true }),
        })}
      />
      <Artifact
        course={COURSE}
        slot={slot({
          path: 'course/framing/rationale.md',
          artifactType: 'rationale',
          hasFrontmatter: false,
          provenance: null,
        })}
      />
      <Artifact
        course={COURSE}
        slot={slot({
          path: 'course/framing/appendix.md',
          artifactType: 'appendix',
          present: false,
          hasFrontmatter: false,
          provenance: null,
        })}
      />
    </Frame>
  ),
}

/** **The pair most likely to be conflated**, on their own.
 *
 *  `inferred` says "some of this was reasoned rather than drawn from a
 *  source, and says so". `claims nothing` says neither — which the domain
 *  calls indistinguishable from an artifact never checked against anything.
 *  One is a disclosure and one is a gap, and only their colours separate
 *  them. */
export const InferredAgainstClaimsNothing: Story = {
  render: () => (
    <Frame heading="a disclosure against a gap">
      <Artifact
        course={COURSE}
        slot={slot({
          path: 'course/framing/reasoned.md',
          provenance: provenance({ sources: [], inferred: true }),
        })}
      />
      <Artifact
        course={COURSE}
        slot={slot({
          path: 'course/framing/unchecked.md',
          provenance: provenance({ sources: [], empty: true }),
        })}
      />
    </Frame>
  ),
}

/** Provenance entries the parser could not read.
 *
 *  Neither a span nor the inference flag — so the count is shown rather than
 *  dropped. Dropping them would make a partly-unreadable provenance look
 *  complete. */
export const Unreadable: Story = {
  render: () => (
    <Frame heading="entries that parsed as neither">
      <Artifact course={COURSE} slot={slot({ provenance: provenance({ unreadable: 3 }) })} />
    </Frame>
  ),
}

/** Frontmatter present but incomplete. Distinct from *no* frontmatter, which
 *  is the red state above — a file that says some of what it is differs from
 *  one that says none of it. */
export const MissingFields: Story = {
  render: () => (
    <Frame heading="frontmatter present, fields absent">
      <Artifact course={COURSE} slot={slot({ missingFields: ['objective_ids', 'reviewed_by'] })} />
    </Frame>
  ),
}

/** Several sources cited, which is the busiest a row gets. */
export const ManySources: Story = {
  render: () => (
    <Frame heading="four cited spans">
      <Artifact
        course={COURSE}
        slot={slot({
          provenance: provenance({
            sources: [
              SPAN,
              { sourceId: SourceId('bbbbbbbb-1111-4111-8111-444444444444'), start: 120, end: 640 },
              { sourceId: SourceId('cccccccc-1111-4111-8111-444444444444'), start: 0, end: 96 },
              {
                sourceId: SourceId('dddddddd-1111-4111-8111-444444444444'),
                start: null,
                end: null,
              },
            ],
          }),
        })}
      />
    </Frame>
  ),
}

/** The row a link named.
 *
 *  `aria-current` as well as a fill, because "the one you followed a link to"
 *  is a fact a screen reader needs and a background colour is not one. */
export const Open: Story = {
  render: () => (
    <Frame heading="followed a link to this row">
      <Artifact course={COURSE} slot={slot()} open />
      <Artifact course={COURSE} slot={slot({ path: 'course/framing/other.md' })} />
    </Frame>
  ),
}
