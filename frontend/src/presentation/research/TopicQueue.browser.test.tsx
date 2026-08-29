import { page } from 'vitest/browser'
import { render } from 'vitest-browser-react'
import { expect, it } from 'vitest'

import type { Dispatch } from '@domain/research/dispatch.ts'
import { focusCounts, type TopicView } from '@domain/research/topic.ts'
import { TopicId } from '@domain/shared/identifier.ts'

import { OverlayHost } from '../layout/OverlayHost.tsx'
import { ROW_VERBS, TopicQueue } from './TopicQueue.tsx'

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

const Rail = ({ dispatches }: { dispatches: ReadonlyMap<string, Dispatch> }) => (
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

it('keeps every verb on the row while it does', async () => {
  // The other half of the trade, and the reason it needs asserting in the same
  // suite: freeing space for the chip by letting a verb fall off the edge is
  // the defect #38 fixed, arriving from the other direction.
  //
  // Four controls now rather than two. `docs/design/
  // topic-actions-on-the-row.md` §5 names this exact assertion as required
  // before three icons may sit here at all, and it is the assertion that
  // decided the split -- see the next test for the numbers.
  await render(<Rail dispatches={new Map([[String(TOPIC.topicId), RUNNING]])} />)

  const metaBox = page
    .getByText(CHIP, { exact: true })
    .element()
    .closest('.ent-topic-meta')!
    .getBoundingClientRect()

  for (const name of [...Object.values(ROW_VERBS), 'More actions']) {
    const verb = page.getByRole('button', { name: new RegExp(escape(name)) }).element()
    const box = verb.getBoundingClientRect()
    expect(box.width).toBeGreaterThan(0)
    expect(box.right).toBeLessThanOrEqual(metaBox.right + 1)
  }
})

/** `RegExp` metacharacters in an accessible name, of which `ROW_VERBS` has
 *  none today and would have the moment a verb's sentence ends in a `?`. */
const escape = (text: string): string => text.replaceAll(/[.*+?^${}()|[\]\\]/g, String.raw`\$&`)

/** The width decision itself, as the numbers that made it.
 *
 * `docs/design/topic-actions-on-the-row.md` §2 sketches **two** icons on the
 * row with "write our understanding" under the `⋯`, and says out loud that the
 * split belongs to whoever measures it. This is that measurement, and it went
 * the other way: three `.btn-ghost.btn-sm` icons plus the `⋯` are **narrower**
 * than the single worded `Write understanding` button plus the `⋯` they
 * replace. Moving a verb under the menu would be spending a click to buy width
 * the row already has.
 *
 * Measured in Chromium at the 340px rail above, on the very row the test
 * before this one renders, by reading `.ent-topic-verbs`:
 *
 * - `Write understanding` + `⋯`, which is what shipped: **151.16px**
 * - three icons + `⋯`, which is what this is: **133px**
 * - four icons + `⋯`, for the tripwire below: **169px**
 *
 * So the facts group beside the verbs *ends further right* after this change
 * than before it — the opposite of the direction `CHIP` above records losing
 * twice, and the reason the chip's own assertions did not have to move.
 *
 * The bound is the old arrangement's width rather than a tighter round number,
 * because the property worth keeping is comparative: two verbs were added and
 * must not have cost the chip beside them any room. A `toBeLessThan(140)` also
 * passes today and would fail on a font change that moved nothing anybody
 * could see.
 *
 * **Proved red** by adding a fourth `RowVerb` to `RowVerbs`: 169 against a 151
 * bound. That is the tripwire this test is for — a fourth control on this row
 * is where §2's split stops being a click spent for nothing, and it fails here
 * rather than by somebody noticing a clipped glyph.
 *
 * `.ent-topic-verbs` is found through the `⋯` rather than through a verb,
 * deliberately: the `⋯` is the one control in the group that is present in
 * every arrangement, so this locator survives the split being revisited.
 */
it('spends less of the row on three icons than on the one worded button', async () => {
  await render(<Rail dispatches={new Map([[String(TOPIC.topicId), RUNNING]])} />)

  const verbs = page
    .getByRole('button', { name: /More actions/ })
    .element()
    .closest('.ent-topic-verbs')!
    .getBoundingClientRect()

  // 151 is not a token. It is the measured width of what stood here -- a
  // `.btn.btn-sm` reading `Write understanding`, the 28px `⋯`, and the gap
  // between them -- recorded so the comparison survives this file being read
  // by somebody who never saw that row.
  expect(verbs.width).toBeLessThan(151)
})
