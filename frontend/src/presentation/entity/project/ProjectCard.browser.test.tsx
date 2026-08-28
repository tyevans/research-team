import { page } from 'vitest/browser'
import { render } from 'vitest-browser-react'
import { expect, it } from 'vitest'

import type { ProjectRollup } from '@domain/project/landing.ts'
import type { Project } from '@domain/project/project.ts'
import { ProjectId, SessionId } from '@domain/shared/identifier.ts'

import { Menu, MenuItem, MenuTrigger } from '../../common/Menu.tsx'
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
 * chips on it, and the landing page put five things there: a disclosure, a
 * name, a badge, a holder and a run marker (four now, the holder having left).
 * Clipping at rail width is
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
        href="#/p/3f2a1b9c-1111-2222-3333-444444444444"
        slots={{
          toggle: 'all 3 sessions',
          badges: <Chip>4 areas</Chip>,
          activity: <span className="chip chip-held">⟳ run · round 3</span>,
          meta: <span>2 days ago</span>,
          primary: <Button small>Continue</Button>,
          overflow: [
            <Menu
              key="more"
              label="More actions"
              open={false}
              onOpenChange={() => undefined}
              trigger={<MenuTrigger aria-label="More actions" />}
            >
              <MenuItem onSelect={() => undefined}>Delete</MenuItem>
            </Menu>,
          ],
          preview: <p className="preview-text">the current session sits here</p>,
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

  for (const selector of ['.ent-project-name', '.chip', '.ent-project-toggle']) {
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

/** The card is one link, and every control on it is still a control.
 *
 * `entity.css` stretches `.ent-project-name::after` over the whole card so that
 * the padding and the stat line lead to the project page — the friction this
 * page's redesign is mostly about, since the name was an inert `<span>` (the
 * landing page never passed `href`) and the project page was reached through a
 * small secondary button four controls along. The half of that trade which can
 * go wrong is invisible: an element under the overlay is not merely hard to
 * click, it is unreachable by mouse entirely, and it renders completely
 * normally.
 *
 * **jsdom cannot see any of this.** It lays nothing out, so every rect is 0×0
 * and `elementFromPoint` has nothing to answer with, and it applies no
 * stylesheet, so the `z-index` rules that raise the controls do not exist there
 * at all. A card with the overlay and a card without produce identical markup.
 *
 * **Both were proved red in Chromium on 2026-08-27**, each against the rule it
 * is about: deleting `.ent-project-name::after` fails the first (the hit lands
 * on `.ent-project-stats`), and deleting the `position: relative`
 * block fails the second (every control reports the anchor). They fail
 * separately, which is the point of having two — the overlay and the raising
 * are one mechanism and two mistakes.
 */
const centreOf = (selector: string) => {
  const rect = document.querySelector(selector)!.getBoundingClientRect()
  return document.elementFromPoint(rect.left + rect.width / 2, rect.top + rect.height / 2)
}

it('makes the card itself the way to the project', async () => {
  await render(<Rail />)
  await expect.element(page.getByText('⟳ run · round 3')).toBeVisible()

  const card = document.querySelector('.ent-project-card')!.getBoundingClientRect()
  const link = document.querySelector('.ent-project-name')!

  // The overlay is a pseudo-element and has no rect of its own to read. What
  // can be read is the consequence: a point inside the card that is over no
  // control at all hits the anchor. The stat line is that point — metadata,
  // deliberately left under the overlay, which is the same choice that costs it
  // drag-selection.
  expect(centreOf('.ent-project-stats')).toBe(link)

  // And the overlay does not reach past the card into the gap between rows,
  // which is what `position: relative` on the card is for: without it the
  // `::after` resolves against the virtualizer's absolutely positioned `<li>`
  // and would cover the margin as well.
  const outside = document.elementFromPoint(card.left + card.width / 2, card.bottom + 4)
  expect(outside).not.toBe(link)
})

it('leaves every control on the card clickable through the overlay', async () => {
  await render(<Rail />)
  await expect.element(page.getByText('⟳ run · round 3')).toBeVisible()

  // Each of these is a real target a reader is meant to hit, and each one sits
  // over the stretched link. Containment rather than identity, because a
  // control's centre may be its own text node — what matters is that the hit
  // lands inside the control rather than on the anchor, and a button whose
  // label is raised while its padding is not would still fail this.
  for (const selector of [
    '.ent-project-toggle',
    '.chip-held',
    '.preview-text',
    '.ent-project-actions .btn',
  ]) {
    const control = document.querySelector(selector)!
    expect(control.contains(centreOf(selector))).toBe(true)
  }
})
