import { composeStories } from '@storybook/react-vite'
import { render } from '@testing-library/react'
import { describe, it } from 'vitest'

import * as askPageStories from './AskPage.stories.tsx'
import * as askTurnStories from './AskTurn.stories.tsx'
import * as askHeadStories from './AskHead.stories.tsx'
import * as askComposerStories from './AskComposer.stories.tsx'
import * as citationListStories from './CitationList.stories.tsx'

/** Smoke test over every story in the ask page's five story files.
 *
 * This asserts only that each composed story renders without throwing. It is
 * the fix for the gap the spec's "stories are exercised by the suite through
 * `composeStories`" promise left open: `storybook build` is deliberately
 * outside `npm run verify` (see `.storybook/main.ts`), so a story that
 * COMPILES but THROWS when rendered was previously caught by nothing. This
 * catches that. It does NOT catch a story that renders the wrong thing --
 * wrong text, wrong layout, a control drawing in the wrong state -- that is
 * what the behavioural tests and eyes-on-Storybook are for.
 *
 * `CitationList`'s `None` story renders nothing at all by design (see its
 * story file's docstring) -- worth noting because it is the one story here
 * where an empty container is the correct outcome, not a sign the story
 * failed to render. No story in this file, that one included, is asserted
 * to have produced any particular output; `render` not throwing is all any
 * of them are checked for.
 */
describe('ask stories render without throwing', () => {
  const suites = {
    AskPage: composeStories(askPageStories),
    AskTurn: composeStories(askTurnStories),
    AskHead: composeStories(askHeadStories),
    AskComposer: composeStories(askComposerStories),
    CitationList: composeStories(citationListStories),
  }

  for (const [suiteName, stories] of Object.entries(suites)) {
    for (const [storyName, Story] of Object.entries(stories)) {
      it(`${suiteName}/${storyName}`, () => {
        render(<Story />)
      })
    }
  }
})
