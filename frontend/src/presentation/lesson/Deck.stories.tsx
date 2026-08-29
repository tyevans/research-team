import type { Meta, StoryObj } from '@storybook/react-vite'
import { useState } from 'react'
import { fn } from 'storybook/test'

import type { AttemptsApi } from '@application/lesson/use-attempts.ts'
import { freshAttempt } from '@domain/lesson/attempt.ts'
import type { LessonDocument } from '@domain/lesson/document.ts'
import { deckOf } from '@domain/lesson/slides.ts'
import { componentBlock } from '@presentation/ask/ask-fixtures.ts'

import { Deck, SlideOverview } from './Deck.tsx'

/** The four slide kinds, which is what there is to look at.
 *
 * Every claim about roles, keys and focus is in `Deck.test.tsx`, and every
 * measurement is in `deck.browser.test.tsx`. What neither can judge is whether
 * a slide reads as *presented* rather than as a document with a border round
 * it -- the title's measure, the pull-quote's weight against its bracket, the
 * rail's density at twenty rows.
 *
 * These also put the deck into `a11y.browser.test.tsx`'s sweep, which is the
 * reason a full-viewport surface with its own text scale should have a story
 * at all: the deck sets type from `clamp()` against the console's own tokens,
 * and a contrast pair that fails only at a slide's size would be invisible
 * everywhere else.
 *
 * The prose is a real lesson's -- `knowledge-graph/lesson-01.md`, the same file
 * `slides.test.ts` segments -- rather than lorem, so the slides are the length
 * the corpus actually produces. A deck tuned against three-word bullets is a
 * deck tuned against material this system does not write.
 */
const meta: Meta = {
  title: 'lesson/Deck',
}

export default meta

type Story = StoryObj

const attempts = {
  stateFor: () => freshAttempt(),
  update: fn(),
  submit: fn(),
  reset: fn(),
  mcqResponse: (picked: readonly number[]) => picked,
} as unknown as AttemptsApi

const LESSON: LessonDocument = {
  blocks: [
    {
      kind: 'markdown',
      text: [
        '# The Log Is the Only Source of Truth',
        '',
        'Everything in this system is one ordered list of events. A user message, a model reply, a tool call, a file write — each is a single event appended to a stream, and the stream is the whole state.',
        '',
        '## What a fold is, and why it cannot be wrong',
        '',
        'A fold is a pure function of the log. You hand it the events, it hands back the state. Run it twice and you get the same answer, because there is no hidden state to drift.',
        '',
        '"Cannot be stale" is the important half. A stale value is one that was computed once, written down, and then left behind while the world moved on. A fold has no such value — there is nothing to leave behind, because the computation is redone on every read.',
        '',
        '## What a projection is',
        '',
        '> A projection is written down once: if a handler throws, the subscription carries on, the checkpoint advances past it, and the row it would have updated is wrong permanently.',
        '',
        'Read that carefully. The projection is *written down*. That is the difference.',
        '',
        '## Check for understanding',
      ].join('\n'),
    },
    componentBlock({
      type: 'mcq',
      id: 'l1-mcq',
      data: {
        prompt:
          'A handler in a projection throws on event 47 and the process restarts. What is the state of the view?',
        options: [
          { text: 'The view is rebuilt from scratch on restart, so it is correct again.' },
          { text: 'Event 47 is retried and the row is corrected.' },
          { text: 'The row is wrong until somebody rebuilds the projection.' },
        ],
      },
      withheld: ['options[].correct'],
    }),
  ],
}

/** The deck as it opens: the title slide, its lead paragraph, and the rail with
 *  every section named once. */
export const TitleSlide: Story = {
  render: function Render() {
    return <Presented start={0} />
  },
}

/** A section's prose. What to check: the measure -- text should stop around 62
 *  characters, not run the width of the screen. */
export const Prose: Story = {
  render: function Render() {
    return <Presented start={1} />
  },
}

/** The cited passage, and the one risk this design takes: serif at 2.4x with a
 *  hanging accent bracket and no quotation marks. */
export const PullQuote: Story = {
  render: function Render() {
    return <Presented start={2} />
  },
}

/** A quiz on a slide, which must be answerable rather than a picture. Pick an
 *  option: the widget is the same one the document view mounts. */
export const Question: Story = {
  render: function Render() {
    return <Presented start={4} />
  },
}

/** Every slide at once. The thumbnails carry the slide's own words rather than
 *  a scaled render, because a 200px copy of a paragraph is unreadable.
 *
 * The overview rather than the deck-with-overview-open: the deck holds that in
 * state, and a prop added so a story could photograph it is a prop the next
 * reader takes for a feature. */
export const Overview: Story = {
  render: () => <SlideOverview deck={deckOf(LESSON)} current={2} onPick={fn()} onClose={fn()} />,
}

/** The deck with its position held outside it, the way `CourseFile` holds it in
 *  the URL. */
const Presented = ({ start }: { start: number }) => {
  const [slide, setSlide] = useState(start)
  return (
    <Deck
      doc={LESSON}
      attempts={attempts}
      label="lesson-01.md"
      withheldExplanation="The answer key was removed from this response and is graded on the server."
      slide={slide}
      onSlide={setSlide}
      onClose={fn()}
    />
  )
}
