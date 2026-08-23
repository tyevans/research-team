import { useState } from 'react'
import type { Meta, StoryObj } from '@storybook/react-vite'

import type { AttemptsApi } from '@application/lesson/use-attempts.ts'
import type { AttemptState } from '@domain/lesson/attempt.ts'
import { freshAttempt, mcqResponse } from '@domain/lesson/attempt.ts'
import type { ComponentBlock } from '@domain/lesson/document.ts'
import { ComponentId } from '@domain/shared/identifier.ts'

import { Flashcards } from './Flashcards.tsx'

/** A deck, and the one component in the console that is a button without
 *  looking like one.
 *
 * **The card is `role="button"` with `aria-pressed={flipped}`**, and
 * `CLAUDE.md` singles it out for exactly that: `.btn[aria-pressed='true']` is
 * scoped to `.btn` rather than written bare, because "a flipped card turning
 * accent-on-accent is a different decision from a toggle looking pressed". So
 * this widget is the reason that selector is narrow, and `Flipped` is where
 * the consequence is visible — a flipped card must read as *turned over*, not
 * as *selected*.
 *
 * It also has the console's only bespoke keyboard contract outside the overlay
 * host: Enter and Space flip, the arrow keys step. None of that is visible in
 * a screenshot, which is why the stories are live rather than posed.
 *
 * **A new card always starts face up**, which is a rule rather than an
 * implementation detail: a deck that remembered each card's side would show a
 * learner the answer to a card they have not been asked yet. `step` writes
 * `flipped: false` unconditionally for that reason, and `AtTheEnd` is where
 * wrapping past the last card can be checked to do the same.
 */
const meta: Meta = {
  title: 'lesson/Flashcards',
}

export default meta

type Story = StoryObj

const deck = (
  cards: readonly { front: string; back: string }[],
  title?: string,
): ComponentBlock => ({
  kind: 'component',
  id: ComponentId('deck-1'),
  type: 'flashcards',
  data: { title: title ?? null, cards },
  raw: '',
  lang: 'flashcards',
  unknown: false,
  errors: [],
  withheld: [],
  resolved: false,
})

const CARDS = [
  { front: 'Augustus', back: 'The senior title in the tetrarchy — two held it at once.' },
  { front: 'Caesar', back: 'The junior title, and the designated successor to an Augustus.' },
  { front: 'Nicomedia', back: 'Diocletian’s eastern capital, in Bithynia.' },
]

const useStub = (initial: Partial<AttemptState>): AttemptsApi => {
  const [state, setState] = useState<AttemptState>({ ...freshAttempt(), ...initial })
  return {
    stateFor: () => state,
    update: (_block, change) => {
      setState((current) => ({ ...current, ...change }))
    },
    submit: () => Promise.resolve(),
    reset: () => {
      setState(freshAttempt())
    },
    mcqResponse,
  }
}

const Frame = ({ heading, children }: { heading: string; children: React.ReactNode }) => (
  <section style={{ padding: 'var(--space-3)', maxWidth: 520 }}>
    <h3 style={{ font: 'inherit', color: 'var(--fg-faint)', margin: '0 0 var(--space-2)' }}>
      {heading}
    </h3>
    {children}
  </section>
)

/** Face up, the first card of three.
 *
 *  Live: click the card, or focus it and press Enter or Space. The arrow keys
 *  step without flipping. */
export const Front: Story = {
  render: function Render() {
    const attempts = useStub({})
    return (
      <Frame heading="face up">
        <Flashcards block={deck(CARDS, 'Tetrarchic vocabulary')} attempts={attempts} />
      </Frame>
    )
  },
}

/** **Turned over, which is the state the cascade rule is about.**
 *
 *  The card carries `aria-pressed="true"`. Read against `Front`: it must look
 *  *turned over* — a different side of the same object — rather than
 *  *selected*. `.btn[aria-pressed='true']` gives buttons an accent border and
 *  accent text, and that treatment is deliberately scoped away from this
 *  element, because a chosen control and a flipped card are not the same
 *  claim.
 *
 *  If this ever draws in the accent the way a pressed toggle does, the
 *  selector has been widened. */
export const Flipped: Story = {
  render: function Render() {
    const attempts = useStub({ flipped: true })
    return (
      <Frame heading="turned over — not selected">
        <Flashcards block={deck(CARDS, 'Tetrarchic vocabulary')} attempts={attempts} />
      </Frame>
    )
  },
}

/** The last card, so wrapping can be exercised.
 *
 *  `next ›` from here goes to card 1 and — the rule — arrives **face up**. A
 *  deck that remembered each card's side would show a learner the answer to a
 *  card they have not been asked yet. Flip this one, then press next twice. */
export const AtTheEnd: Story = {
  render: function Render() {
    const attempts = useStub({ card: CARDS.length - 1, flipped: true })
    return (
      <Frame heading="last card, turned over — step forward and it wraps face up">
        <Flashcards block={deck(CARDS, 'Tetrarchic vocabulary')} attempts={attempts} />
      </Frame>
    )
  },
}

/** One card. The counter still reads `1 / 1` and the steppers still work —
 *  they wrap onto the same card rather than being hidden, which keeps the
 *  control row the same shape for every deck. */
export const OneCard: Story = {
  render: function Render() {
    const attempts = useStub({})
    return (
      <Frame heading="a single card">
        <Flashcards block={deck([CARDS[0]!])} attempts={attempts} />
      </Frame>
    )
  },
}

/** A deck with nothing in it.
 *
 *  Says so, and draws no card and no controls — a stepper over an empty deck
 *  is a control that cannot do anything. Untitled here as well as empty,
 *  because the heading is optional and the two absences compound. */
export const EmptyDeck: Story = {
  render: function Render() {
    const attempts = useStub({})
    return (
      <Frame heading="an empty deck">
        <Flashcards block={deck([])} attempts={attempts} />
      </Frame>
    )
  },
}

/** Longer prose on both sides, which is what an authored deck usually is.
 *
 *  The card is `min-height: 96px` and centres its text, so what to check is a
 *  back that is three lines against a front that is one — the card grows and
 *  the controls stay put rather than the text overflowing a fixed box. */
export const LongerText: Story = {
  render: function Render() {
    const attempts = useStub({ flipped: true })
    return (
      <Frame heading="a long back">
        <Flashcards
          block={deck([
            {
              front: 'Why did the tetrarchy fail?',
              back: 'Because it had no rule of succession that survived its author. Diocletian’s abdication was meant to demonstrate one, and instead demonstrated that the Augusti could not compel their Caesars to wait.',
            },
          ])}
          attempts={attempts}
        />
      </Frame>
    )
  },
}
