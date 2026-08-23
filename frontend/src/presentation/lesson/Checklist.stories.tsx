import { useState } from 'react'
import type { Meta, StoryObj } from '@storybook/react-vite'

import type { AttemptsApi } from '@application/lesson/use-attempts.ts'
import type { AttemptState } from '@domain/lesson/attempt.ts'
import { freshAttempt, mcqResponse } from '@domain/lesson/attempt.ts'
import type { ComponentBlock } from '@domain/lesson/document.ts'
import { ComponentId } from '@domain/shared/identifier.ts'

import { Checklist } from './Checklist.tsx'

/** A checklist, and the promise it used to make on surfaces that could not
 *  keep it.
 *
 * **`PersistsAgainstCannot` is why this file exists.** Whether a tick survives
 * is two facts, not one: `persist` on the block is what the *author* asked
 * for, and `AttemptsApi.saveChecklist` is what the *surface* can do.
 * `use-attempts.ts` leaves that method `undefined` rather than a no-op
 * precisely so the widget can tell them apart — an ask answer and a dialogue
 * question both render `LessonDocument` without it.
 *
 * The widget was reading only the first. So a checklist authored with
 * `persist: true` inside an ask drew **"saved as you go"** and saved nothing,
 * with the tick landing normally and the reader finding out on their next
 * visit. The optional call was always correct; the claim beside it was not.
 *
 * Fixed in the same commit as this page. The two stories are the standing
 * check, and they have to be a pair — a build that dropped the hint entirely
 * passes "the unsaveable one makes no promise" on its own.
 *
 * The other rule worth a page: **required items are counted separately.** A
 * checklist can be 6-of-8 done and still have every required item outstanding,
 * and a single "6 of 8" would hide that. The completion tone keys off the
 * required count, not the total.
 */
const meta: Meta = {
  title: 'lesson/Checklist',
}

export default meta

type Story = StoryObj

const block = (
  items: readonly { text: string; note?: string; required?: boolean }[],
  persist: boolean,
  title?: string,
): ComponentBlock => ({
  kind: 'component',
  id: ComponentId('check-1'),
  type: 'checklist',
  data: {
    title: title ?? null,
    persist,
    items: items.map((item) => ({
      text: item.text,
      note: item.note ?? null,
      required: item.required ?? false,
    })),
  },
  raw: '',
  lang: 'checklist',
  unknown: false,
  errors: [],
  withheld: [],
  resolved: false,
})

const ITEMS = [
  { text: 'Name the four tetrarchs', required: true },
  { text: 'Say which two were Augusti', required: true },
  { text: 'Locate each capital', note: 'Nicomedia, Sirmium, Mediolanum, Augusta Treverorum.' },
  { text: 'Explain why the succession failed' },
]

/** Two stubs, and the difference between them is the whole subject.
 *
 *  `canSave` supplies `saveChecklist`; `cannotSave` omits it, exactly as
 *  `use-attempts.ts` does for a surface with no workspace to write to. */
const useStub = (canSave: boolean, initial: Partial<AttemptState> = {}): AttemptsApi => {
  const [state, setState] = useState<AttemptState>({ ...freshAttempt(), ...initial })
  const base: AttemptsApi = {
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
  return canSave ? { ...base, saveChecklist: () => undefined } : base
}

const Frame = ({ heading, children }: { heading: string; children: React.ReactNode }) => (
  <section style={{ padding: 'var(--space-3)', maxWidth: 560 }}>
    <h3 style={{ font: 'inherit', color: 'var(--fg-faint)', margin: '0 0 var(--space-2)' }}>
      {heading}
    </h3>
    {children}
  </section>
)

/** **The pair.** Same block, same `persist: true`, different surfaces.
 *
 *  The top one can save and says so. The bottom one cannot and says nothing —
 *  it does not claim, and it does not apologise either, because a reader who
 *  never asked for persistence does not need to be told it is unavailable.
 *
 *  What to check: the bottom checklist carries no "saved as you go". If it
 *  does, the widget is reading the author's flag instead of the surface's
 *  capability, which is the defect this page was written for. */
export const PersistsAgainstCannot: Story = {
  render: function Render() {
    const saving = useStub(true, { ticked: { 0: true } })
    const notSaving = useStub(false, { ticked: { 0: true } })
    return (
      <>
        <Frame heading="a lesson — ticks are kept">
          <Checklist block={block(ITEMS, true, 'Before you move on')} attempts={saving} />
        </Frame>
        <Frame heading="an ask or a dialogue — the same block, nothing to save into">
          <Checklist block={block(ITEMS, true, 'Before you move on')} attempts={notSaving} />
        </Frame>
      </>
    )
  },
}

/** The author did not ask for persistence. Nothing is claimed either way,
 *  which is the same rendering as the unsaveable case above — correctly, since
 *  from the reader's side they are the same situation. */
export const NotPersisted: Story = {
  render: function Render() {
    const attempts = useStub(true)
    return (
      <Frame heading="persist: false">
        <Checklist block={block(ITEMS, false, 'Before you move on')} attempts={attempts} />
      </Frame>
    )
  },
}

/** **Required items counted separately.** Six of eight done and none of the
 *  required ones.
 *
 *  A single "6 of 8" would read as nearly finished. The required tally is what
 *  says otherwise, and the completion tone keys off it rather than the total —
 *  so this checklist must not read as complete. */
export const RequiredOutstanding: Story = {
  render: function Render() {
    const attempts = useStub(true, {
      ticked: { 2: true, 3: true, 4: true, 5: true, 6: true, 7: true },
    })
    return (
      <Frame heading="mostly ticked, nothing required">
        <Checklist
          block={block(
            [
              { text: 'Name the four tetrarchs', required: true },
              { text: 'Say which two were Augusti', required: true },
              { text: 'Skim the source' },
              { text: 'Note the dates' },
              { text: 'Check the map' },
              { text: 'Read the footnotes' },
              { text: 'Look at the coin evidence' },
              { text: 'Bookmark the article' },
            ],
            true,
          )}
          attempts={attempts}
        />
      </Frame>
    )
  },
}

/** Everything required is done. The counter takes its completion tone from the
 *  required tally, so this reads finished while two optional items remain. */
export const RequiredComplete: Story = {
  render: function Render() {
    const attempts = useStub(true, { ticked: { 0: true, 1: true } })
    return (
      <Frame heading="all required done, two optional left">
        <Checklist block={block(ITEMS, true)} attempts={attempts} />
      </Frame>
    )
  },
}

/** The save failed.
 *
 *  Replaces the reassurance rather than sitting beside it: "saved as you go"
 *  and "not saved" cannot both be on screen, because the first is exactly the
 *  thing that turned out to be false. */
export const SaveFailed: Story = {
  render: function Render() {
    const attempts = useStub(true, { ticked: { 0: true }, saveError: 'the workspace is read-only' })
    return (
      <Frame heading="the save failed">
        <Checklist block={block(ITEMS, true, 'Before you move on')} attempts={attempts} />
      </Frame>
    )
  },
}

/** No required items at all, which is the ordinary case. The counter shows a
 *  plain tally and no required clause. */
export const NoRequiredItems: Story = {
  render: function Render() {
    const attempts = useStub(true, { ticked: { 0: true } })
    return (
      <Frame heading="nothing required">
        <Checklist
          block={block(
            [{ text: 'Skim the source' }, { text: 'Note the dates' }, { text: 'Check the map' }],
            true,
          )}
          attempts={attempts}
        />
      </Frame>
    )
  },
}
