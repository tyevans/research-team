import { page } from 'vitest/browser'
import { render } from 'vitest-browser-react'
import { expect, it } from 'vitest'

import type { ProjectRollup } from '@domain/project/landing.ts'
import type { Project } from '@domain/project/project.ts'
import { ProjectId, SessionId } from '@domain/shared/identifier.ts'

import { Button, Chip } from '../../common/primitives.tsx'
import { OverlayHost } from '../../layout/OverlayHost.tsx'
import { ProjectCard } from './ProjectCard.tsx'

/** What the card's head costs at the width the landing page's rail gets.
 *
 * `ProjectCard.test.tsx` asserts every one of these things is in the document
 * and cannot assert more: whether the fifth item on a flex line is painted
 * past the card's right edge is a measurement, and jsdom neither lays out nor
 * applies the stylesheet, so a chip 90px outside the card and a chip sitting
 * comfortably inside it produce identical markup. Every assertion below would
 * pass there against the defect.
 *
 * The defect is not hypothetical for this head in particular. `ProjectRow`,
 * which this card replaced, wrote `flex-wrap: wrap` on `.project-head`, and
 * `.ent-project-head` did not — it was written for a gallery frame with two
 * chips on it, and the landing page puts five things there: a disclosure, a
 * name, a badge, a holder and a run marker. Clipping at rail width is
 * the same defect already filed twice against the topic row's meta line and
 * its dispatch chip.
 *
 * **Proved red, and not in the direction expected — which is why it was
 * measured rather than argued.** With `flex-wrap: wrap` taken back off
 * `.ent-project-head`, nothing overflows: the first test below stays green.
 * The name's measured width goes to **0**. `.ent-ref-name` carries
 * `min-width: 0` and `overflow: hidden` so that a long label ellipsises rather
 * than pushing its container wide, and on an unwrapped line with four
 * non-shrinking items beside it there is nothing left to give, so it shrinks
 * all the way out. Every project on the landing page would have rendered with
 * no visible name at rail width, inside a card whose bounds were perfectly
 * respected.
 *
 * So the two tests below measure different things and both are needed: the
 * first that the head does not paint outside the card, the second that the
 * name survives at all. Only the second is red without the wrap.
 */

/** The rail the landing list actually gets. A card measured at 1200px is a
 *  card nobody sees. */
const RAIL = 340

const project = (over: Partial<Project> = {}): Project => ({
  id: ProjectId('3f2a1b9c-1111-2222-3333-444444444444'),
  name: 'a project with a name long enough to want the room',
  activeSessionId: SessionId('7d41e0aa-1111-2222-3333-444444444444'),
  tipAtEvent: 128,
  ...over,
})

const rollup = (over: Partial<ProjectRollup> = {}): ProjectRollup => ({
  project: project(),
  sessions: [],
  sessionCount: 3,
  fileCount: 12,
  lastActivity: '2026-01-01T10:00:00Z',
  ...over,
})

/** The head with every slot filled, because the measurement is of what the
 *  *view's* slots cost. A card rendered with two of its five head items would
 *  go on passing while the landing page clipped.
 *
 * `badges` is a plain chip here and the landing page passes `null` today -- the
 * workflow chip that filled it went with the workflow system. Kept filled
 * deliberately: this file measures the widest head the card can be asked to
 * draw, and dropping the slot because nobody fills it right now would retire
 * the measurement the day somebody fills it again. */
const Rail = () => (
  <OverlayHost>
    <div style={{ width: `${RAIL}px` }}>
      <ProjectCard
        rollup={rollup()}
        slots={{
          toggle: (
            <Button small tone="quiet">
              all 3 sessions
            </Button>
          ),
          badges: <Chip>4 areas</Chip>,
          activity: <span className="chip chip-held">⟳ run · round 3</span>,
          primary: <Button small>Resume 7d41e0aa</Button>,
        }}
      />
    </div>
  </OverlayHost>
)

const rightEdgeOf = (selector: string) =>
  document.querySelector(selector)!.getBoundingClientRect().right

it('keeps everything in the head inside the card at rail width', async () => {
  await render(<Rail />)
  await expect.element(page.getByText('⟳ run · round 3')).toBeVisible()

  // The card's own content edge, not the viewport's: the viewport is set in
  // `vite.config.ts` and is far wider than the rail, so a chip painted outside
  // the card is still inside the window and `toBeVisible` says nothing about
  // it.
  const card = document.querySelector('.ent-project-card')!.getBoundingClientRect()

  for (const selector of ['.ent-project-name', '.chip', '.ent-project-holder']) {
    expect(rightEdgeOf(selector)).toBeLessThanOrEqual(card.right)
  }
  expect(rightEdgeOf('.chip-held')).toBeLessThanOrEqual(card.right)
})

it('gives the name the room the chips do not need, rather than an equal share', async () => {
  await render(<Rail />)
  await expect.element(page.getByText('⟳ run · round 3')).toBeVisible()

  // The name is the thing a list is scanned for, so it is what takes the
  // width. Measured at 0 without `flex-wrap: wrap` on the head: `.ent-ref-name`
  // shrinks without limit by design, and on a single line shared with four
  // items that do not shrink there is nothing left for it.
  const name = document.querySelector('.ent-project-name')!.getBoundingClientRect()
  expect(name.width).toBeGreaterThan(RAIL / 2)
})
