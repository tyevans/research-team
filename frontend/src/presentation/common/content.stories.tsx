import type { Meta, StoryObj } from '@storybook/react-vite'

import { CodeBlock, DiffView, Markdown } from './content.tsx'

/** The three ways this console puts text on a page, side by side.
 *
 * They are one file and one story because the thing worth checking is the
 * comparison. All three render a body of text into a dark surface, all three
 * have an empty state, and all three are reached from the same two screens --
 * a file view and a conversation -- so a reader moving between them should not
 * have to relearn what a line looks like. Nothing in the suite can see that:
 * `markdown.test.ts` and `diff.test.ts` assert over the *strings* these
 * components render, which is the right place for the sanitiser's allow-list
 * and the elision arithmetic, and says nothing about whether the results look
 * like they belong to one application.
 *
 * What only a browser shows here, and why each is on the page:
 *
 * - **`Markdown` is the only `dangerouslySetInnerHTML` in the application**,
 *   and its output is dressed entirely by `markdown.css` -- headings, lists,
 *   tables, inline code, block quotes. jsdom applies no stylesheet, so a
 *   selector in that file that stopped matching would fail nothing. The sample
 *   deliberately uses every element the allow-list permits, so the story is
 *   also the answer to "is this tag styled?".
 * - **`CodeBlock`'s gutter is a `<span>` per line**, not a table and not
 *   `counter-increment`, so the numbers and the code stay aligned only as long
 *   as both are the same monospace metric. A wrapped long line is included
 *   because that is where the alignment breaks first.
 * - **`DiffView`'s three row tones** -- add, delete, unchanged -- are colour
 *   and nothing else. A reader who cannot separate them by hue has a diff that
 *   says nothing, which is a contrast question, and contrast is a measurement.
 *
 * The empty states get their own story rather than a variant of this one:
 * they are what a reader sees most often when something has gone wrong
 * upstream, they are three differently-worded parentheticals, and putting them
 * on one line is how anyone would notice that they disagree.
 */
const meta: Meta = {
  title: 'common/content',
  parameters: { layout: 'padded' },
}

export default meta

type Story = StoryObj

const MARKDOWN = `# A finding, as the extractor writes one

The claim rests on a **single** cohort, and the authors say so in a footnote
rather than the abstract. See \`table 3\` for the split.

> Funding was disclosed after acceptance.

- who paid for it
- who saw it first
- what was pre-registered

| stage | verdict |
| ----- | ------- |
| seed  | held    |
| draft | contested |

[The paper](https://example.invalid/paper "as published")
`

const BEFORE = `def score(attempt):
    if attempt.answers is None:
        return 0
    total = sum(a.weight for a in attempt.answers)
    return total
`

const AFTER = `def score(attempt):
    if not attempt.answers:
        return 0
    total = sum(a.weight for a in attempt.answers if a.correct)
    return round(total, 2)
`

/** All three with real content in them, stacked in the order a file view
 *  offers them. The heading above each is the story's own, not the
 *  components' -- none of them draws a label, which is itself worth seeing. */
export const Rendered: Story = {
  render: () => (
    <div style={{ display: 'grid', gap: 'var(--space-4)' }}>
      <section>
        <h3>Markdown</h3>
        <Markdown source={MARKDOWN} />
      </section>
      <section>
        <h3>CodeBlock</h3>
        <CodeBlock
          text={`${AFTER}\n# one deliberately long line, to show where the gutter and the text stop agreeing when it wraps\n`}
        />
      </section>
      <section>
        <h3>DiffView</h3>
        <DiffView before={BEFORE} after={AFTER} />
      </section>
    </div>
  ),
}

/** What each says when there is nothing to show.
 *
 * `Markdown` and `CodeBlock` both say "(empty file)" and `DiffView` says
 * "(no textual change)", which is the distinction to keep: the first two mean
 * the document is empty and the third means it is unchanged. A reader who sees
 * the third and reads it as the first concludes a revision lost their work. */
export const Empty: Story = {
  render: () => (
    <div style={{ display: 'grid', gap: 'var(--space-4)' }}>
      <Markdown source="   " />
      <CodeBlock text="" />
      <DiffView before={BEFORE} after={BEFORE} />
    </div>
  ),
}
