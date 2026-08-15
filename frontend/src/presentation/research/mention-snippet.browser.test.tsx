import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { page } from 'vitest/browser'
import { render } from 'vitest-browser-react'
import { expect, it, vi } from 'vitest'

import type { Container as AppContainer } from '@app/container.ts'
import { ContainerProvider } from '@app/container-context.tsx'
import type { DefinitionsRepository, UsagesRepository } from '@application/ports/repositories.ts'
import type { GraphView, Usage } from '@domain/knowledge/graph.ts'
import { ProjectId } from '@domain/shared/identifier.ts'

import { OverlayHost } from '../layout/OverlayHost.tsx'
import { GraphDetail } from './GraphDetail.tsx'

/** The two things about a rendered mention that only a browser can answer.
 *
 * **`.md-snippet` beating `.md`.** The snippet reuses the `Markdown` component,
 * whose `.md` carries `padding: 10px 14px 40px` -- page chrome for a document
 * filling a pane, and 40px of dead space under every row in a list. jsdom
 * returns only what an inline style said, so a `getComputedStyle` there reads
 * `0px` whether the override works, is misspelled, or was written as a Tailwind
 * utility that loses to the unlayered rule (`CLAUDE.md` carries that
 * measurement). Only a real cascade can tell those apart.
 *
 * **What the browser does with a nested anchor**, which is not what was
 * predicted. The mention row is one `<a>` to the source document and the
 * passage inside it is markdown that routinely carries links of its own;
 * `<a>`'s content model forbids interactive descendants, so this was expected
 * to split the row into sibling links and was accepted as a known cost. It
 * does not. The passage is written through `dangerouslySetInnerHTML` on a
 * `<div>`, and the fragment parser that runs there has no open anchor in scope
 * to close, so the inner anchor is attached as an ordinary child and stays
 * there. Measured in Chromium on 2026-08-15: the row is one link, its text and
 * its accessible name are complete, and the nested link works.
 *
 * The markup is still invalid, and that is why this file asserts the *current*
 * behaviour rather than the desired one. A browser that started enforcing the
 * content model on fragment insertion, or a change routing this markup through
 * a document parser, would fail here -- which is the notice this test exists to
 * give. If a future change strips the passage's own links instead, the fix is
 * to update this file, not to restore the nesting.
 *
 * Neither case is provable in `GraphDetail.test.tsx`: jsdom applies no
 * stylesheet, and its parser makes its own choices about nesting, so the row
 * measures the same there no matter what a browser would do.
 */

const PROJECT = ProjectId('11111111-1111-1111-1111-111111111111')

const VIEW: GraphView = {
  nodes: [{ id: 'ada', name: 'Ada Lovelace', entityType: 'Person' }],
  links: [],
  expanded: new Set(['ada']),
}

const usage = (over: Partial<Usage> = {}): Usage => ({
  sourceId: '22222222-2222-2222-2222-222222222222',
  start: 10,
  end: 40,
  text: 'Major prodigies were expiated by sacrifice.',
  score: 0.8,
  ...over,
})

const mount = async (passages: Usage[]) => {
  const usages: UsagesRepository = { usages: vi.fn().mockResolvedValue(passages) }
  const definitions: DefinitionsRepository = {
    definition: vi.fn().mockResolvedValue({
      text: null,
      citations: [],
      model: null,
      generatedAt: null,
      stale: false,
    }),
  }
  const container = { usages, definitions } as unknown as AppContainer
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } })

  return await render(
    <QueryClientProvider client={queryClient}>
      <ContainerProvider container={container}>
        <OverlayHost>
          {/* Boxed, because the panel is `absolute inset-y-3` and would
              measure as a zero rect inside an unsized parent. */}
          <div style={{ width: '320px', height: '520px', position: 'relative' }}>
            <GraphDetail
              projectId={PROJECT}
              view={VIEW}
              selected="ada"
              onSelect={() => {}}
              onRemove={() => {}}
              onClose={() => {}}
            />
          </div>
        </OverlayHost>
      </ContainerProvider>
    </QueryClientProvider>,
  )
}

const openMentions = async () => {
  await page.getByRole('button', { name: /mentions/i }).click()
}

it('draws a snippet without the document padding `.md` carries', async () => {
  await mount([usage()])
  await openMentions()

  const snippet = page.getByText(/Major prodigies/).element()
  const block = snippet.closest('.md') as HTMLElement
  expect(block).not.toBeNull()

  const style = getComputedStyle(block)
  // Would read 10px/14px/40px with `.md-snippet` absent, and the same with it
  // written as a `p-0` utility -- `.md` is unlayered, utilities are not.
  expect(style.paddingTop).toBe('0px')
  expect(style.paddingLeft).toBe('0px')
  expect(style.paddingBottom).toBe('0px')

  // The last block's own margin goes too: `.md-p`'s 10px is paragraph rhythm
  // inside prose and a gap the row did not ask for on its final line.
  const last = block.lastElementChild as HTMLElement
  expect(getComputedStyle(last).marginBottom).toBe('0px')
})

it('keeps a nested passage link inside the row rather than splitting the row', async () => {
  await mount([
    usage({ text: 'Major prodigies were [expiated](https://example.com/rite) by sacrifice.' }),
  ])
  await openMentions()

  const inner = page.getByRole('link', { name: 'expiated', exact: true }).element()
  expect(inner).toHaveAttribute('href', 'https://example.com/rite')

  // The measurement this file exists for, and it refutes the prediction the
  // design decision was taken against. An `<a>` inside an `<a>` is invalid and
  // a *parser* reading such markup in one pass splits the outer anchor around
  // the inner one -- but that is not the path this takes. The passage is set
  // through `dangerouslySetInnerHTML` on a `<div>`, and the fragment parser
  // that runs there has no open anchor in scope to close, so the inner anchor
  // is attached as an ordinary child. Chromium keeps it there.
  const row = inner.closest('li') as HTMLElement
  const outer = row.querySelector('a') as HTMLAnchorElement
  expect(outer.contains(inner)).toBe(true)
  expect(outer).toHaveAttribute('href', expect.stringContaining('/doc/'))

  // So the row is not cut short: the whole passage, on both sides of the
  // nested link, is still inside the anchor that opens the document.
  expect(outer.textContent).toContain('Major prodigies were')
  expect(outer.textContent).toContain('by sacrifice')

  // Nor is the accessible name cut short, which was the second guess after the
  // split was ruled out. The whole passage is announced, nested link included.
  // The markup remains invalid and a future browser is free to treat it
  // differently -- that is what this test is standing watch over -- but as of
  // 2026-08-15 in Chromium the observable cost of the nesting is nil.
  expect(outer).toHaveAccessibleName('22222222 Major prodigies were expiated by sacrifice.')
})
