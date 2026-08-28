import type { ReactNode } from 'react'
import { page } from 'vitest/browser'
import { render } from 'vitest-browser-react'
import { expect, it } from 'vitest'

import type { Dispatch } from '@domain/research/dispatch.ts'
import { focusCounts, type TopicView } from '@domain/research/topic.ts'
import { TopicId } from '@domain/shared/identifier.ts'

import { OverlayHost } from '../layout/OverlayHost.tsx'
import { QueueToolbar } from '../project/queue/QueueHeader.tsx'
import { TopicQueue } from './TopicQueue.tsx'

/** What the row reports about its own dispatch, at the width the row gets.
 *
 * `TopicQueue.test.tsx` asserts the chip is in the document and cannot assert
 * more than that: the clip is `overflow: hidden` on a flex line, and jsdom
 * neither lays out nor applies the stylesheet, so a chip painted 90px past the
 * right edge and a chip sitting comfortably inside it produce identical
 * markup. Every assertion below would pass there against the defect.
 *
 * **Proved red**, and by the change that matters rather than by the whole
 * commit: rendering the status chip beside the note again, with the `⋯`
 * menu left in place, puts the dispatch chip at 239 against a facts group
 * ending at 160.8 -- present in the DOM, painted nowhere, unreachable by
 * mouse, which is task #40 exactly. The second test stays green through that,
 * so the two are measuring different things.
 *
 * The whole queue rather than a bare `TopicRow`, because the slots are built
 * by `TopicQueue` and the measurement is of what they cost: a `TopicRow` test
 * would go on passing while the queue handed it a 58px button.
 */

/** The rail the queue actually gets, and the width the stories are drawn at.
 *  A queue measured at 1200px is a queue nobody sees. */
const RAIL = 340

/** The chip's whole sentence, matched exactly: the aggregate bar above the
 *  list also says "running", and a loose match resolves to both. */
const CHIP = '⟳ understanding · running'

const TOPIC: TopicView = {
  topicId: TopicId('11111111-1111-1111-1111-111111111111'),
  question: 'Who funded the study, and did they see it before publication?',
  status: 'investigating',
  sources: 4,
  findings: 2,
  openSubQuestions: 1,
  triggers: [],
  needsAttention: false,
  isBlocked: false,
}

const RUNNING: Dispatch = {
  dispatchId: 'd1',
  topicId: '11111111-1111-1111-1111-111111111111',
  action: 'understanding',
  status: 'running',
  question: null,
  position: null,
  path: null,
  sessionId: null,
  detail: null,
}

const Rail = ({
  dispatches,
  toolbar,
}: {
  dispatches: ReadonlyMap<string, Dispatch>
  toolbar?: ReactNode
}) => (
  <OverlayHost>
    <div
      style={{
        width: `${RAIL}px`,
        display: 'flex',
        flexDirection: 'column',
        border: '1px solid var(--line)',
        padding: '10px 12px 12px',
      }}
    >
      <TopicQueue
        topics={[TOPIC]}
        counts={focusCounts([TOPIC])}
        focus="all"
        search=""
        dispatches={dispatches}
        running
        queuedCount={0}
        dispatching={false}
        stopping={false}
        onFocusChange={() => {}}
        onSearchChange={() => {}}
        onDispatch={() => {}}
        onManage={() => {}}
        onStop={() => {}}
        toolbar={toolbar}
      />
    </div>
  </OverlayHost>
)

it('draws the dispatch chip inside the row it reports on', async () => {
  await render(<Rail dispatches={new Map([[String(TOPIC.topicId), RUNNING]])} />)

  const chip = page.getByText(CHIP, { exact: true }).element()
  // `.ent-topic-facts`, not `.ent-topic-meta`, and getting that wrong is worth
  // recording: the meta line is the whole row and the *facts* group is the box
  // that clips. Measured against the meta line, the defect passes — the chip
  // sat at 125..239 inside a line ending at 317, entirely invisible, because
  // the group it is in ended at 126.7.
  const facts = chip.closest('.ent-topic-facts')
  expect(facts).not.toBeNull()

  const chipBox = chip.getBoundingClientRect()
  const factsBox = facts!.getBoundingClientRect()

  // Width first, because the two failures are opposite and a single assertion
  // on position would call one of them a pass. `flex: none` clipped the chip
  // away entirely; the shrink it replaced took it to 0px, which looked like a
  // chip that had never rendered.
  expect(chipBox.width).toBeGreaterThan(0)

  // Drawn, not merely present. `overflow: hidden` leaves a clipped element in
  // the DOM at its full width with its box past the edge, which is why every
  // jsdom assertion about this chip passes against a chip nobody can see.
  expect(chipBox.right).toBeLessThanOrEqual(factsBox.right + 1)
})

it('keeps both verbs on the row while it does', async () => {
  // The other half of the trade, and the reason it needs asserting in the same
  // suite: freeing space for the chip by letting a verb fall off the edge is
  // the defect #38 fixed, arriving from the other direction.
  await render(<Rail dispatches={new Map([[String(TOPIC.topicId), RUNNING]])} />)

  const metaBox = page
    .getByText(CHIP, { exact: true })
    .element()
    .closest('.ent-topic-meta')!
    .getBoundingClientRect()

  for (const name of ['Write understanding', 'More actions']) {
    const verb = page.getByRole('button', { name: new RegExp(name) }).element()
    const box = verb.getBoundingClientRect()
    expect(box.width).toBeGreaterThan(0)
    expect(box.right).toBeLessThanOrEqual(metaBox.right + 1)
  }
})

/** The toolbar line, which is a width fight and therefore not a jsdom question.
 *
 * Three icon controls and a search field share the ~294px this rail gives one
 * line. jsdom lays nothing out, so a glyph painted past the right edge, a
 * field squeezed to nothing, and a row that fits produce identical markup --
 * the same blindness the two tests above exist for, one line higher up the
 * pane.
 *
 * Both directions are asserted because both have happened on this pane. The
 * `CHIP` comment in `TopicQueue.tsx` records a chip drawn 708px wide inside a
 * 294px line *and* a chip shrunk to 0px, from the same row, and a toolbar is
 * the same two failures: the icons clipped off the end, or the field they
 * share the line with reduced to a caret.
 *
 * **Proved red** by dropping `flex` from the line's wrapper, which is the
 * regression that matters: the toolbar falls to a second row and the header is
 * two stacked bands again, which is the shape this slice removed. Measured at
 * the first control's left edge of 13 against a field ending at 185. Every
 * jsdom assertion in `QueueHeader.test.tsx` stays green through that.
 *
 * What does **not** break it, measured rather than assumed: giving the field
 * `w-full` instead of `min-w-0 flex-1`. A flex item shrinks below `width:
 * 100%` on its own, so that spelling still fits -- `min-w-0 flex-1` is the
 * honest declaration of what is wanted rather than the thing standing between
 * this line and a defect, and a comment claiming otherwise would be a
 * measurement nobody took.
 */
it('fits the toolbar and the search box on one line', async () => {
  await render(
    <Rail
      dispatches={new Map()}
      toolbar={
        <QueueToolbar
          askHref="#/p/x/ask"
          dialogueHref="#/p/x/dialogue"
          topicsOpen={false}
          onOpenTopics={() => {}}
        />
      }
    />,
  )

  const field = page.getByRole('searchbox', { name: 'Filter topics' }).element()
  const fieldBox = field.getBoundingClientRect()
  const lineBox = field.parentElement!.getBoundingClientRect()

  const controls = [
    page.getByRole('button', { name: /seed and manage/i }),
    page.getByRole('link', { name: 'Ask this project' }),
    page.getByRole('link', { name: 'Be asked about this project' }),
  ]
  for (const control of controls) {
    const box = control.element().getBoundingClientRect()
    expect(box.width).toBeGreaterThan(0)
    expect(box.right).toBeLessThanOrEqual(lineBox.right + 1)
    // Not merely inside the line: past the field, rather than on top of it.
    // Two overlapping boxes both satisfy the bound above.
    expect(box.left).toBeGreaterThanOrEqual(fieldBox.right - 1)
  }

  // The field gives up the slack and keeps enough of itself to type in. 120px
  // is not a design token, it is a floor: below it the placeholder is gone and
  // the box reads as broken rather than as narrow.
  expect(fieldBox.width).toBeGreaterThan(120)
})
