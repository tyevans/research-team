/** That a resolved widget inside an ask turn has a QueryClient and a container.
 *
 * A browser test rather than a jsdom one for what it protects against: if
 * either provider is missing, `useEntityReference` throws during render, and a
 * thrown hook takes the whole answer down rather than one block. That is the
 * one failure mode in this feature that is not per-block, so it is worth a
 * test that mounts the real tree rather than a wrapper a test built.
 *
 * The assertion is deliberately about the *sibling prose surviving*, not about
 * the widget rendering: a widget that renders proves the providers are there,
 * but so would a widget that silently fell back, and only the prose surviving
 * distinguishes "one block degraded" from "the answer went down".
 *
 * **This test would pass with all of Task 2 reverted, and that is stated here
 * rather than left as reassurance.** No renderer in `RENDERERS` calls
 * `useEntityReference` yet -- Task 3 ships the first -- so the turn below
 * carries no blocks and the hook never runs. What it pins today is only that
 * `AskTurn` draws its answer under the real providers. Task 3 must widen it:
 * give `turn()` a `component:definition` block, and the assertion becomes a
 * real one, because a missing provider then throws during render and the
 * answer text below disappears with the turn.
 */
import { expect, it } from 'vitest'
import { page } from 'vitest/browser'
import { render } from 'vitest-browser-react'

import { AskTurn } from './AskTurn.tsx'
import { PROJECT, turn } from './ask-fixtures.ts'

it('renders the prose beside a resolved widget rather than losing the turn', async () => {
  await render(
    <AskTurn
      projectId={PROJECT}
      turn={turn({ blocks: [] })}
      open={false}
      onToggle={() => {}}
      conversationId="c1"
    />,
  )

  // The fixture's own default answer, quoted from `ask-fixtures.ts:71` rather
  // than invented: an assertion against text the fixture does not carry would
  // fail for a reason that has nothing to do with providers.
  await expect
    .element(page.getByText(/They agree on the effect and disagree on its size/))
    .toBeInTheDocument()
})
