import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState, type ReactElement } from 'react'
import { expect, it, vi } from 'vitest'

import type { AttemptsApi } from '@application/lesson/use-attempts.ts'
import { freshAttempt } from '@domain/lesson/attempt.ts'
import type { LessonDocument } from '@domain/lesson/document.ts'
import { componentBlock } from '@presentation/ask/ask-fixtures.ts'

import { OverlayHost } from '../layout/OverlayHost.tsx'
import { Deck } from './Deck.tsx'

/** What the deck owes a reader, in the places jsdom can judge: roles, focus,
 *  keyboard routing and rendered text.
 *
 * Everything whose answer is a computed style or a measurement is in
 * `deck.browser.test.tsx` instead, per CLAUDE.md -- and the split matters more
 * here than usual, because a full-viewport surface invites assertions jsdom
 * will happily answer wrongly. Nothing below reads a size or a colour.
 *
 * **Proved red**, each against the specific break named:
 *  - remove the `hidden` on off-slides -> "shows one slide at a time" fails
 *    finding two headings.
 *  - drop the `isTyping` guard -> "a space typed into a widget is a space"
 *    fails with the slide advanced to 2.
 *  - swap `go(index + 1)` for `go(index)` on ArrowRight -> four tests fail.
 *  - remove the mount-time `focus()` -> "moves focus into the deck" fails.
 */

const DOC: LessonDocument = {
  blocks: [
    {
      kind: 'markdown',
      text: '# The Log Is the Only Source of Truth\n\nEverything is one ordered list.\n\n## What a fold is\n\nA fold is a pure function of the log.\n\n> A fold is recomputed every time.\n\n## Check for understanding',
    },
    componentBlock({ type: 'mcq', id: 'q1', data: { prompt: 'Fold or projection?', options: [] } }),
  ],
}

/** `freshAttempt()` rather than a hand-written state object: the widgets read
 *  `picked`, `typed`, `ticked`, `card` and `busy`, and a stub missing any one
 *  of them throws inside the widget rather than failing the deck's assertion --
 *  which is a test failing for a reason that has nothing to do with what it
 *  claims. Found the hard way on the first run of this file. */
const attempts = {
  stateFor: () => freshAttempt(),
  update: vi.fn(),
  submit: vi.fn(),
  reset: vi.fn(),
  mcqResponse: (picked: readonly number[]) => picked,
} as unknown as AttemptsApi

/** The deck with its position held the way `CourseFile` holds it -- in one
 *  place, changed by `onSlide`. Local state here stands in for the URL, which
 *  `deck-route.test.ts` covers separately; what matters for these tests is that
 *  the deck owns no position of its own. */
const Harness = ({ start = 0, doc = DOC }: { start?: number; doc?: LessonDocument }) => {
  const [slide, setSlide] = useState(start)
  const [open, setOpen] = useState(true)
  return (
    <OverlayHost>
      <button type="button">behind the deck</button>
      {open ? (
        <Deck
          doc={doc}
          attempts={attempts}
          label="lesson-01.md"
          withheldExplanation="graded on the server"
          slide={slide}
          onSlide={setSlide}
          onClose={() => setOpen(false)}
        />
      ) : null}
    </OverlayHost>
  )
}

const show = (element: ReactElement = <Harness />) => render(element)

const deck = () => screen.getByRole('dialog', { name: /presented/ })

/** The slides reachable to a reader.
 *
 * Filtered by `aria-roledescription` rather than taken as "the only group on
 * the page": the deck's own root is a `group` too -- that is the carousel
 * pattern -- so a bare `getByRole('group')` would be ambiguous and, worse,
 * would pass for the wrong reason if the slides stopped being groups. */
const slides = () =>
  screen
    .getAllByRole('group')
    .filter((element) => element.getAttribute('aria-roledescription') === 'slide')

const shown = () => slides()[0]!

it('names itself for the lesson it is presenting', () => {
  show()
  expect(deck()).toHaveAttribute('aria-label', 'The Log Is the Only Source of Truth, presented')
})

it('falls back to the file name when the lesson has no heading', () => {
  show(<Harness doc={{ blocks: [{ kind: 'markdown', text: 'Just prose.' }] }} />)
  expect(screen.getByRole('dialog', { name: 'lesson-01.md, presented' })).toBeInTheDocument()
})

it('shows one slide at a time, with the rest out of the accessibility tree', () => {
  show()
  // Two `group`-shaped sections exist in the DOM; only one is reachable. The
  // assertion is the *count*, because a deck that showed everything would
  // still show the right first slide.
  expect(slides()).toHaveLength(1)
  expect(within(shown()).getByText(/Everything is one ordered list/)).toBeInTheDocument()
})

it('describes each slide as a slide, and says where in the deck it is', () => {
  show()
  expect(shown()).toHaveAttribute('aria-roledescription', 'slide')
  expect(shown().getAttribute('aria-label')).toMatch(/^Slide 1 of \d+/)
})

it('moves forward and back on the arrows', async () => {
  const user = userEvent.setup()
  show()
  await user.keyboard('{ArrowRight}')
  expect(shown().getAttribute('aria-label')).toMatch(/^Slide 2 /)
  await user.keyboard('{ArrowLeft}')
  expect(shown().getAttribute('aria-label')).toMatch(/^Slide 1 /)
})

it('jumps to the ends on Home and End', async () => {
  const user = userEvent.setup()
  show()
  await user.keyboard('{End}')
  const label = shown().getAttribute('aria-label') ?? ''
  const total = /of (\d+)/.exec(label)?.[1]
  expect(label).toBe(`Slide ${total!} of ${total!}, Check for understanding`)
  await user.keyboard('{Home}')
  expect(shown().getAttribute('aria-label')).toMatch(/^Slide 1 /)
})

it('stops at the ends rather than wrapping', async () => {
  const user = userEvent.setup()
  show()
  await user.keyboard('{ArrowLeft}{ArrowLeft}')
  expect(shown().getAttribute('aria-label')).toMatch(/^Slide 1 /)
})

it('advances on space, because that is what a presenter presses', async () => {
  const user = userEvent.setup()
  show()
  await user.keyboard(' ')
  expect(shown().getAttribute('aria-label')).toMatch(/^Slide 2 /)
})

it('leaves a space typed into a widget alone', async () => {
  // The failure this guards is specific and would be reported as "the cloze
  // input eats my answer": with a deck-level key handler, every space in a
  // blank advances the slide instead of reaching the field. Driven through the
  // real `Cloze`, not a bare `<input>` appended to the body, because the claim
  // is about a control *inside* the deck -- one outside it would pass with the
  // guard deleted.
  const user = userEvent.setup()
  const onSlide = vi.fn()
  render(
    <OverlayHost>
      <Deck
        doc={{
          blocks: [
            componentBlock({
              type: 'cloze',
              id: 'c1',
              data: {
                mode: 'all-at-once',
                segments: [{ text: 'A fold is ' }, { blank: 0, hint: 'pure' }],
              },
            }),
          ],
        }}
        attempts={attempts}
        label="lesson-01.md"
        withheldExplanation=""
        slide={0}
        onSlide={onSlide}
        onClose={vi.fn()}
      />
    </OverlayHost>,
  )
  await user.click(screen.getByRole('textbox', { name: /Blank 1/ }))
  await user.keyboard(' ')
  expect(onSlide).not.toHaveBeenCalled()
})

it('moves focus into the deck on open', () => {
  show()
  expect(deck().contains(document.activeElement)).toBe(true)
})

it('closes on Escape and gives focus back to what opened it', async () => {
  const user = userEvent.setup()
  const opener = document.createElement('button')
  document.body.append(opener)
  opener.focus()
  show()
  await user.keyboard('{Escape}')
  expect(screen.queryByRole('dialog', { name: /presented/ })).not.toBeInTheDocument()
  opener.remove()
})

it('closes from the button that names where it goes', async () => {
  const user = userEvent.setup()
  show()
  await user.click(screen.getByRole('button', { name: 'Read as document' }))
  expect(screen.queryByRole('dialog', { name: /presented/ })).not.toBeInTheDocument()
})

it('lists every slide in the rail, and jumping is one click', async () => {
  const user = userEvent.setup()
  show()
  const rail = screen.getByRole('navigation', { name: 'Slides' })
  const rows = within(rail).getAllByRole('button')
  expect(rows.length).toBeGreaterThan(2)
  await user.click(rows[2]!)
  expect(shown().getAttribute('aria-label')).toMatch(/^Slide 3 /)
})

it('marks the reader position in the rail', async () => {
  const user = userEvent.setup()
  show()
  const rail = screen.getByRole('navigation', { name: 'Slides' })
  expect(within(rail).getAllByRole('button', { current: true })).toHaveLength(1)
  await user.keyboard('{ArrowRight}')
  const marked = within(rail).getAllByRole('button', { current: true })
  expect(marked).toHaveLength(1)
  expect(marked[0]).toHaveTextContent('02')
})

it('prints each section name once in the rail', () => {
  show()
  const rail = screen.getByRole('navigation', { name: 'Slides' })
  expect(within(rail).getAllByText('What a fold is')).toHaveLength(1)
})

it('opens the overview on o, and picking a slide goes there', async () => {
  const user = userEvent.setup()
  show()
  await user.keyboard('o')
  const overview = screen.getByRole('dialog', { name: 'All slides' })
  const thumbs = within(overview).getAllByRole('button')
  await user.click(thumbs[thumbs.length - 1]!)
  expect(screen.queryByRole('dialog', { name: 'All slides' })).not.toBeInTheDocument()
  expect(shown().getAttribute('aria-label')).toMatch(/Check for understanding/)
})

it('closes the overview on Escape without closing the deck under it', async () => {
  // The host gives Escape to the topmost layer only. A hand-written `window`
  // listener -- which is what a `useState` boolean plus a keydown would have
  // been -- closes both on one press, which is the defect `Drawer`'s docstring
  // records having shipped once.
  const user = userEvent.setup()
  show()
  await user.keyboard('o')
  await user.keyboard('{Escape}')
  expect(screen.queryByRole('dialog', { name: 'All slides' })).not.toBeInTheDocument()
  expect(screen.getByRole('dialog', { name: /presented/ })).toBeInTheDocument()
})

it('opens at the slide it was given, which is what a deep link is', () => {
  show(<Harness start={2} />)
  expect(shown().getAttribute('aria-label')).toMatch(/^Slide 3 /)
})

it('lands somewhere in the lesson when the link is past the end', () => {
  // A stale link into a re-authored lesson. `clampSlide`'s reasoning, at the
  // surface that shows the consequence.
  show(<Harness start={999} />)
  const label = shown().getAttribute('aria-label') ?? ''
  const total = /of (\d+)/.exec(label)?.[1]
  expect(label).toMatch(new RegExp(`^Slide ${total!} of ${total!}`))
})

it('says so rather than drawing an empty stage for a document with no blocks', () => {
  show(<Harness doc={{ blocks: [] }} />)
  expect(screen.getByText(/nothing to present/)).toBeInTheDocument()
})

it('offers speaker notes only where the lesson carries them', async () => {
  const user = userEvent.setup()
  show()
  expect(screen.queryByRole('button', { name: 'Speaker notes' })).not.toBeInTheDocument()

  show(
    <Harness
      doc={{
        blocks: [{ kind: 'markdown', text: 'Prose.\n<!-- notes: pause here -->' }],
      }}
    />,
  )
  const toggle = screen.getAllByRole('button', { name: 'Speaker notes' })[0]!
  await user.click(toggle)
  expect(screen.getByRole('complementary', { name: 'Speaker notes' })).toHaveTextContent(
    'pause here',
  )
})
