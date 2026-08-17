/** The turn as rendered, when the answer carries a widget alongside the prose. */
import { render, screen } from '@testing-library/react'
import type { ReactNode } from 'react'
import { expect, it } from 'vitest'

import type { Container as AppContainer } from '@app/container.ts'
import { ContainerProvider } from '@app/container-context.tsx'
import type { ComponentBlock } from '@domain/lesson/document.ts'
import { ComponentId } from '@domain/shared/identifier.ts'

import { AskTurn } from './AskTurn.tsx'
import { PROJECT, turn } from './ask-fixtures.ts'

const renderTurn = (mcqTurn: ReturnType<typeof turn>) => {
  // `submitAskAttempt` is never called in these tests -- rendering alone is
  // what's under test -- but `useAskAttempts` reaches for the container on
  // every render, so a wrapper with none would throw before the assertion.
  const container = {
    ask: { submitAskAttempt: () => new Promise(() => {}) },
  } as unknown as AppContainer
  const wrapper = ({ children }: { children: ReactNode }) => (
    <ContainerProvider container={container}>{children}</ContainerProvider>
  )
  return render(
    <AskTurn
      projectId={PROJECT}
      turn={mcqTurn}
      open={false}
      onToggle={() => {}}
      conversationId="c1"
    />,
    { wrapper },
  )
}

const mcqBlock: ComponentBlock = {
  kind: 'component',
  id: ComponentId('q1'),
  type: 'mcq',
  data: { prompt: 'Which papers agree?', options: [{ text: 'A' }, { text: 'B' }], multiple: false },
  raw: '```component:mcq\n```',
  lang: 'component:mcq',
  unknown: false,
  errors: [],
  withheld: ['answer'],
}

it('renders a widget the model asked back, not a code block', () => {
  renderTurn(turn({ blocks: [mcqBlock] }))

  // `LessonDocument`'s component section is `<section aria-label="...">`,
  // which the accessibility tree exposes as `region`, not `group` -- there is
  // no `role="group"` anywhere in this render, so asserting that role would
  // be red for the wrong reason.
  expect(screen.getByRole('region', { name: /mcq component/i })).toBeInTheDocument()
  expect(screen.queryByText('component:mcq')).not.toBeInTheDocument()
})

it('keeps the plain markdown path for an answer with no widgets', () => {
  // The common case grows no second render tree -- `hasComponents` is the
  // same predicate `LessonDocument` uses and exists for this. Red against a
  // build that routes every turn through the component pipeline, because
  // the ask-widget note ("not saved") only exists on that pipeline's path.
  renderTurn(turn({ blocks: [] }))

  expect(screen.queryByRole('region')).not.toBeInTheDocument()
  expect(screen.queryByText(/not saved/i)).not.toBeInTheDocument()
})

it('says that an answer here is not remembered', () => {
  // The one honest difference from a lesson. A reader who does not know this
  // loses work and blames the page.
  renderTurn(turn({ blocks: [mcqBlock] }))

  expect(screen.getByText(/not saved/i)).toBeInTheDocument()
})
