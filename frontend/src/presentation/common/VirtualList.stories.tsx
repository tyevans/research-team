import { useRef, useState } from 'react'
import type { Meta, StoryObj } from '@storybook/react-vite'

import { Button, Chip } from './primitives.tsx'
import { VirtualList } from './VirtualList.tsx'

/** The virtualized list, and the three defects it was built to end — each of
 *  which is invisible in jsdom and reproducible here.
 *
 * `VirtualList.tsx` records all three. They are worth restating as *what to
 * look for*, because a virtualized list fails quietly: it reserves the right
 * amount of scroll and simply draws the wrong thing in it.
 *
 * 1. **`scrollMargin`.** The virtualizer works in the scroll element's
 *    coordinates. A list that does not start at its scroller's top is
 *    displaced by exactly that much — invisible at three rows, drawing the
 *    wrong rows at fifty. `DocumentBrowser` set no margin and was correct only
 *    by accident of having no header. `BelowAHeader` is that case.
 * 2. **Per-row measurement.** `ROW_HEIGHT` was once treated as exact, and a
 *    title that wrapped to two lines drew over the row beneath. `RaggedRows`
 *    is that case.
 * 3. **The scroller ref's timing.** A parent's ref attaches after its
 *    children's, so reading it at render returned `null` on the only render
 *    that mattered and `getVirtualItems()` came back empty forever. The
 *    symptom was a correctly sized `<ul>` containing no rows at all. Every
 *    story here is that case, because every one of them mounts.
 *
 * **jsdom cannot judge any of this and does not fail honestly either.**
 * `vitest.setup.ts` pins `offsetWidth`/`offsetHeight` to constants, and the
 * `|| estimate` fallback in the component exists precisely because jsdom
 * reports every height as 0 — a measured 0 would collapse the list. So in the
 * unit suite every row is its estimate, which is the one condition under
 * which all three defects above are absent.
 */
const meta: Meta = {
  title: 'common/VirtualList',
}

export default meta

type Story = StoryObj

interface Row {
  readonly id: string
  readonly title: string
  readonly kind: string
}

const rows = (n: number, long = false): Row[] =>
  Array.from({ length: n }, (_, i) => ({
    id: `r${String(i)}`,
    kind: i % 3 === 0 ? 'note' : i % 3 === 1 ? 'page' : 'pdf',
    title:
      long && i % 4 === 0
        ? `Row ${String(i)} — ${'a title long enough to wrap '.repeat(3)}`
        : `Row ${String(i)}`,
  }))

const RowView = ({ row }: { row: Row }) => (
  <div
    style={{
      display: 'flex',
      gap: 'var(--space-2)',
      alignItems: 'baseline',
      padding: 'var(--space-2)',
      borderBottom: '1px solid var(--line)',
    }}
  >
    <Chip>{row.kind}</Chip>
    <span style={{ color: 'var(--fg)' }}>{row.title}</span>
  </div>
)

/** The list, and the scroller the caller owns. Written once because every
 *  story below differs only in what sits above the list inside that scroller. */
const Scroller = ({
  items,
  above,
  width = 340,
}: {
  items: readonly Row[]
  above?: React.ReactNode
  width?: number
}) => {
  const scrollRef = useRef<HTMLDivElement>(null)
  return (
    <div
      ref={scrollRef}
      style={{
        height: 420,
        width,
        overflow: 'auto',
        border: '1px solid var(--line)',
        background: 'var(--bg-panel)',
      }}
    >
      {above}
      <VirtualList items={items} scrollRef={scrollRef} getKey={(row) => row.id} estimate={() => 34}>
        {(row, position) => (
          <li
            key={row.id}
            data-index={position.index}
            ref={position.measure}
            style={{
              position: 'absolute',
              top: 0,
              left: 0,
              width: '100%',
              transform: `translateY(${String(position.top)}px)`,
              listStyle: 'none',
            }}
          >
            <RowView row={row} />
          </li>
        )}
      </VirtualList>
    </div>
  )
}

/** Two hundred uniform rows, list flush with its scroller's top.
 *
 *  The baseline, and deliberately the *easy* case: this is the arrangement
 *  `DocumentBrowser` was correct under while carrying a latent `scrollMargin`
 *  bug. A story that only ever showed this would certify nothing. */
export const Plain: Story = {
  render: () => <Scroller items={rows(200)} />,
}

/** **The `scrollMargin` case.** The same list, under a header inside the same
 *  scroller.
 *
 *  What to check: scroll to the middle and read a row's number. It must match
 *  its position. If the drawn window is displaced by roughly the header's
 *  height — the rows are right but the wrong ones are on screen, or the last
 *  rows are unreachable — the margin has stopped being measured.
 *
 *  This is the story that would have caught the latent bug the moment anybody
 *  put a header above `DocumentBrowser`. */
export const BelowAHeader: Story = {
  render: () => (
    <Scroller
      items={rows(200)}
      above={
        <div style={{ padding: 'var(--space-3)', borderBottom: '1px solid var(--line)' }}>
          <h3 style={{ font: 'inherit', color: 'var(--fg)', margin: '0 0 var(--space-2)' }}>
            Documents
          </h3>
          <p style={{ color: 'var(--fg-dim)', margin: '0 0 var(--space-2)' }}>
            A purpose line, an action bar and a heading — which is what
            <code> ProjectList </code> actually has above its list.
          </p>
          <Button small>Add a source</Button>
        </div>
      }
    />
  ),
}

/** **The per-row measurement case.** Every fourth title wraps to two or three
 *  lines in a 340px rail.
 *
 *  What to check: no row draws over the row beneath it, and the scrollbar
 *  settles rather than jittering as tall rows are measured. The estimate is
 *  34px and a wrapped row is roughly double that, so a build that trusted the
 *  estimate would overlap visibly within the first screen. */
export const RaggedRows: Story = {
  render: () => <Scroller items={rows(200, true)} />,
}

/** **Both at once**, which is what a real pane is.
 *
 *  Neither original list had a header *and* ragged rows, which is why each
 *  learned only one of the two lessons. */
export const RaggedBelowAHeader: Story = {
  render: () => (
    <Scroller
      items={rows(200, true)}
      above={
        <div style={{ padding: 'var(--space-3)', borderBottom: '1px solid var(--line)' }}>
          <h3 style={{ font: 'inherit', color: 'var(--fg)', margin: 0 }}>Documents</h3>
        </div>
      }
    />
  ),
}

/** **The `getItemKey` case.** A row added at the top, on demand.
 *
 *  Without `getItemKey` the virtualizer keys by index, so gaining a row at the
 *  top re-keys every row below it and React rebuilds the lot — losing focus,
 *  scroll position and any open fold.
 *
 *  What to check: scroll down, then press the button. The scroll position must
 *  hold and the rows you were reading must stay the rows you were reading,
 *  one place lower. A jump back to the top is the defect. */
export const RowAddedAtTheTop: Story = {
  render: function Render() {
    const [items, setItems] = useState(() => rows(200))
    return (
      <div style={{ display: 'grid', gap: 'var(--space-2)', padding: 'var(--space-3)' }}>
        <div>
          <Button
            onClick={() => {
              setItems((current) => [
                { id: `new${String(current.length)}`, kind: 'note', title: 'A newly arrived row' },
                ...current,
              ])
            }}
          >
            Add a row at the top
          </Button>
        </div>
        <Scroller items={items} />
      </div>
    )
  },
}

/** Nothing to virtualize.
 *
 *  Worth a story because the failure mode of this component is "the right
 *  amount of space with nothing in it", and an empty list is what that looks
 *  like when it is correct. The two must be told apart by the scroller not
 *  scrolling. */
export const Empty: Story = {
  render: () => <Scroller items={[]} />,
}
