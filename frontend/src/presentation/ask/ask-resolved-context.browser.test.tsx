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
 * **This now has teeth, and Task 2's version said it did not.** The turn below
 * carries a `component:definition` block, `RENDERERS` maps it to
 * `DefinitionWidget`, and that widget calls `useEntityReference` on the first
 * render -- so a missing provider is a throw during render, not a quiet
 * fallback. Measured rather than reasoned: with `ContainerProvider` removed
 * from the wrapper below, this fails with "useContainer must be used inside a
 * <ContainerProvider>" and the answer text is gone; with `QueryClientProvider`
 * removed it fails the same way on TanStack's own message.
 *
 * The providers are the real ones -- `createContainer()` and a `QueryClient`,
 * nested as `main.tsx` nests them -- rather than fakes. Its fetches have no
 * server here and fail, which lands the widget in `unavailable`; that is the
 * point. The claim is that a failing lookup costs one block, and a test whose
 * container always answered could not make it.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { expect, it } from 'vitest'
import { page } from 'vitest/browser'
import { render } from 'vitest-browser-react'

import { ContainerProvider } from '@app/container-context.tsx'
import { createContainer } from '@app/container.ts'
import type { MarkdownBlock } from '@domain/lesson/document.ts'

import { AskTurn } from './AskTurn.tsx'
import { componentBlock, PROJECT, turn } from './ask-fixtures.ts'

const DEFINITION = componentBlock({
  type: 'definition',
  id: 'nicene',
  data: { entity: 'Nicene Christianity' },
  raw: '```component:definition\nid: nicene\nentity: Nicene Christianity\n```',
})

/** The sibling the assertion is really about. It has to be a *block* and not
 *  `turn.answer`: `AskTurn` renders the answer string only when the turn
 *  carries no components, and switches to `LessonDocument` over `blocks` the
 *  moment one appears -- so a turn with a widget and prose only in `answer`
 *  shows no prose at all, and this test would fail for a reason that has
 *  nothing to do with providers. Found by running it. */
const PROSE: MarkdownBlock = {
  kind: 'markdown',
  text: 'They agree on the effect and disagree on its size.',
}

it('renders the prose beside a resolved widget rather than losing the turn', async () => {
  const container = createContainer()
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })

  await render(
    <ContainerProvider container={container}>
      <QueryClientProvider client={client}>
        <AskTurn
          projectId={PROJECT}
          turn={turn({ blocks: [PROSE, DEFINITION] })}
          open={false}
          onToggle={() => {}}
          conversationId="c1"
        />
      </QueryClientProvider>
    </ContainerProvider>,
  )

  // The widget itself renders, which is what proves the hook ran at all: with
  // no reachable server the reference degrades, and `ResolvedFrame` draws the
  // author's word in every non-resolved state.
  await expect.element(page.getByText('Nicene Christianity')).toBeInTheDocument()

  await expect
    .element(page.getByText(/They agree on the effect and disagree on its size/))
    .toBeInTheDocument()
})
