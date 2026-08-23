import { composeStories } from '@storybook/react-vite'
import { render } from '@testing-library/react'
import { expect, it } from 'vitest'

import * as stories from './Approvals.stories.tsx'

/** A decision is never hidden, only disabled -- and the two gates prove each
 *  other.
 *
 * `Approvals.tsx` argues it: hiding a decision the server will not take makes
 * the console's vocabulary depend on state nothing on screen reports, so a
 * reader sees three controls here and four there "and has no way to tell
 * whether the fourth is missing, broken, or was never a thing".
 *
 * **Neither half is worth having alone**, which is the reason the stories are
 * a pair. "The stage gate has four controls" passes on a build that maps over
 * `allowedDecisions` -- the exact build the fixed `DECISIONS` list exists to
 * prevent. It is only wrong on the *tool* gate, and only visibly so beside a
 * card that has four.
 *
 * The second assertion is the one that carries the accessibility claim: the
 * unavailable control is `disabled` (so it takes no focus, because there is
 * genuinely nothing to do with it) *and* joined to its reason by
 * `aria-describedby`, so a screen-reader user gets the explanation rather than
 * a silently dead button.
 *
 * **Proved red** by mapping the decision list over `approval.allowedDecisions`
 * instead of the fixed `DECISIONS` -- which is the change `Approvals.tsx` says
 * "is exactly how a decision goes missing without anybody noticing". Three of
 * the five fail; the stage-gate test stays green, because a gate that allows
 * all four is identical under both builds. That asymmetry is the whole reason
 * a single-card test is worthless here.
 */
const { AToolGate, AStageGate, Deciding } = composeStories(stories)

const decisionButtons = () =>
  [...document.body.querySelectorAll('button')].filter((button) =>
    /^(Approve|Edit the call|Reject|Respond instead)$/.test(button.textContent?.trim() ?? ''),
  )

it('names all four decisions on a gate that takes only three', () => {
  render(<AToolGate />)
  const buttons = decisionButtons()
  expect(buttons.map((each) => each.textContent?.trim())).toEqual([
    'Approve',
    'Edit the call',
    'Reject',
    'Respond instead',
  ])
  expect(buttons.filter((each) => each.disabled)).toHaveLength(1)
})

/** The excluded control explains itself to everyone, not only to a sighted
 *  reader. */
it('joins the unavailable decision to its reason', () => {
  render(<AToolGate />)
  const respond = decisionButtons().find((each) => each.textContent?.trim() === 'Respond instead')
  expect(respond).toBeDefined()
  expect(respond!.disabled).toBe(true)

  const describedBy = respond!.getAttribute('aria-describedby')
  expect(describedBy).toBeTruthy()
  const reason = document.getElementById(describedBy!)
  expect(reason?.textContent ?? '').toMatch(/invents a result/)
})

/** The half that gives the first its meaning: a gate that takes all four has
 *  none disabled. */
it('leaves every decision live on a gate that takes all four', () => {
  render(<AStageGate />)
  const buttons = decisionButtons()
  expect(buttons).toHaveLength(4)
  expect(buttons.filter((each) => each.disabled)).toHaveLength(0)
})

/** A decision in flight disables everything, and the accent stays where it is.
 *
 *  This is the case the accent rule does *not* apply to, asserted so the two
 *  are not confused: `Approve` is still the action and there is no other live
 *  control to move the emphasis to. Moving it here would be the mistake. */
it('keeps the accent on Approve while a decision is in flight', () => {
  render(<Deciding />)
  const approve = decisionButtons().find((each) => each.textContent?.trim() === 'Approve')
  expect(approve).toBeDefined()
  expect(approve!.disabled).toBe(true)
  expect(approve!.className).toContain('btn-accent')
  expect(decisionButtons().filter((each) => each.className.includes('btn-accent'))).toHaveLength(1)
})

/** Both gates on one page, which is how a reader actually meets the
 *  difference.
 *
 *  Counted rather than located. The first draft walked the DOM for card
 *  elements (`section > div > div`) and found none, because it was guessing at
 *  a structure `Approvals` does not promise. Eight decision buttons across two
 *  cards and exactly one disabled says the same thing and survives any
 *  rearrangement of the markup -- which is what a test of a *rule* should do,
 *  since the rule is about counts and not about nesting. */
it('shows four decisions per card and excludes exactly one across the pair', () => {
  const { BothGates } = composeStories(stories)
  render(<BothGates />)

  const buttons = decisionButtons()
  expect(buttons).toHaveLength(8)
  expect(buttons.filter((each) => each.disabled)).toHaveLength(1)
})
