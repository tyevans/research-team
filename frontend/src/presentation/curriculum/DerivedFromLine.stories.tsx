import type { Meta, StoryObj } from '@storybook/react-vite'

import type { Curriculum } from '@domain/knowledge/curriculum.ts'
import { emptyCurriculum } from '@domain/knowledge/curriculum.ts'

import { DerivedFromLine } from './AreaMap.tsx'

/** The sentence that says how much a curriculum map is actually built on —
 *  and the state it spent a whole feature printing without anyone reading it.
 *
 * **The story to look at is `NoSharedPassages`.** `CLAUDE.md` records what
 * happened: the co-mention channel shipped, produced nothing from the day it
 * merged, and this line printed "**0** shared passages" on every projection
 * for the whole time. Measured over a real ingest afterwards — 36 chunks, 0
 * with entity links, 0 passages, and an area projection byte-identical with
 * the channel present and absent.
 *
 * The entry's own conclusion is the reason this page exists:
 *
 * > A surface that displays a health metric nobody reads is not
 * > observability; it is the same silence with a number in front of it.
 *
 * A story cannot make anyone read it either. What it can do is put the zero
 * next to a healthy number, so that "0 shared passages" stops being a
 * plausible-looking word in a sentence and becomes the odd one out on a page.
 * That is the difference between a number being *rendered* and a number being
 * *legible*, and it is the cheapest half of the fix. The expensive half is
 * `test_a_curriculum_built_over_a_real_ingest_counts_shared_passages`, which
 * is the actual guard and postdates the defect by a feature.
 *
 * The other stories are the flags this component branches on. Three of them —
 * `usedEmbeddings`, `truncated`, and the empty-entity split — change what a
 * reader should *believe* about a map that draws identically either way.
 */
const meta: Meta = {
  title: 'curriculum/DerivedFromLine',
}

export default meta

type Story = StoryObj

const from = (over: Partial<Curriculum['derivedFrom']>): Curriculum => ({
  ...emptyCurriculum,
  derivedFrom: { ...emptyCurriculum.derivedFrom, ...over },
})

const HEALTHY = {
  entities: 4127,
  relationships: 1893,
  passages: 612,
  semanticEdges: 340,
  usedEmbeddings: true,
}

const Row = ({ heading, curriculum }: { heading: string; curriculum: Curriculum }) => (
  <section style={{ padding: 'var(--space-3)', maxWidth: 720 }}>
    <h3 style={{ font: 'inherit', color: 'var(--fg-faint)', margin: '0 0 var(--space-2)' }}>
      {heading}
    </h3>
    <DerivedFromLine curriculum={curriculum} />
  </section>
)

/** A map built on everything the pipeline can give it. The reference the
 *  other stories are read against. */
export const Healthy: Story = {
  render: () => <Row heading="every channel contributing" curriculum={from(HEALTHY)} />,
}

/** **The defect that shipped.** Everything healthy except the co-mention
 *  channel, which produced nothing for a whole feature.
 *
 *  Read the two sentences on this page in order. The second is a correct
 *  report of a broken pipeline, and on its own it reads as ordinary prose —
 *  which is exactly why it survived. Next to the first, the zero is the only
 *  thing on the page. */
export const NoSharedPassages: Story = {
  render: () => (
    <>
      <Row heading="healthy" curriculum={from(HEALTHY)} />
      <Row
        heading="the channel that shipped producing nothing"
        curriculum={from({ ...HEALTHY, passages: 0 })}
      />
    </>
  ),
}

/** Embeddings off, which the component names explicitly rather than omitting.
 *
 *  The comment in `AreaMap.tsx` argues why: embeddings can be switched off, a
 *  project ingested before they were durable has none, and a provider whose
 *  endpoint was down leaves them missing — and all three draw a perfect map.
 *  A reader who is not told is looking at a weaker claim than they think.
 *
 *  Check that the second sentence is present and not merely implied by the
 *  first stopping early. */
export const NoEmbeddings: Story = {
  render: () => (
    <>
      <Row heading="joined by meaning" curriculum={from(HEALTHY)} />
      <Row
        heading="the graph alone"
        curriculum={from({ ...HEALTHY, usedEmbeddings: false, semanticEdges: 0 })}
      />
    </>
  ),
}

/** The graph outgrew one read, so the areas cover part of it.
 *
 *  The only clause here drawn in `--k-failure`, and rightly: every other
 *  sentence describes a map that is complete and thin, where this one
 *  describes a map that is incomplete and does not say by how much. */
export const Truncated: Story = {
  render: () => (
    <Row heading="partial coverage" curriculum={from({ ...HEALTHY, truncated: true })} />
  ),
}

/** Everything wrong at once, which is what a first run against a
 *  misconfigured project actually looks like.
 *
 *  Worth a story because the clauses are appended rather than prioritised: a
 *  reader meeting all three has to find the one that explains the others. */
export const EverythingWrong: Story = {
  render: () => (
    <Row
      heading="no passages, no embeddings, truncated"
      curriculum={from({
        entities: 4127,
        relationships: 1893,
        passages: 0,
        semanticEdges: 0,
        usedEmbeddings: false,
        truncated: true,
      })}
    />
  ),
}

/** Nothing at all — the state `emptyCurriculum` describes.
 *
 *  All zeroes and no embeddings. Included so the zero in `NoSharedPassages`
 *  can be told apart from a project that has simply not run yet: those are
 *  different problems with the same digit, and this line is the only place a
 *  reader could tell them apart. */
export const NothingRun: Story = {
  render: () => <Row heading="a project that has not run" curriculum={emptyCurriculum} />,
}
