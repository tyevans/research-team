import { render } from 'vitest-browser-react'
import { expect, it } from 'vitest'

/** The connection badges stay at the right edge on a page that draws no
 *  breadcrumb.
 *
 * The defect this is written against was introduced by making the landing
 * page's trail empty. `.lay-chrome` is a plain flex row -- no
 * `justify-content` -- and `.crumbs` was the only child with `flex: 1 1 auto`,
 * so the trail was doing double duty as the spacer that pushed `.chrome-right`
 * over. Delete the nav and the badges slide left and sit against the `log`
 * link, on the one page that is most people's first screen.
 *
 * The fix is `margin-left: auto` on `.chrome-right`, which anchors it to the
 * right edge whatever is or is not to its left -- so the header's layout stops
 * depending on a component's decision not to render.
 *
 * A browser test for CLAUDE.md's stated reason: jsdom lays nothing out, so
 * every rect here is a zero rect and the two arrangements -- badges at the
 * right edge and badges jammed against the log link -- are byte-identical to
 * it. The assertion is a measured x, which is the only thing that separates
 * them.
 */
const Chrome = ({ crumbs }: { crumbs: boolean }) => (
  <div className="lay-chrome" style={{ width: '900px' }}>
    <a className="brand" href="#/">
      <span className="brand-name">research&#8209;team</span>
    </a>
    <a className="btn btn-ghost btn-sm" href="#/log">
      log
    </a>
    {crumbs ? (
      <nav className="crumbs" id="crumbs">
        <span className="sid">a project</span>
      </nav>
    ) : null}
    <div className="chrome-right" data-testid="right">
      <span className="conn">live</span>
    </div>
  </div>
)

const rightEdgeOf = async (crumbs: boolean) => {
  const screen = await render(<Chrome crumbs={crumbs} />)
  const badges = document.querySelector('[data-testid="right"]') as HTMLElement
  const edge = badges.getBoundingClientRect().right
  await screen.unmount()
  return edge
}

it('anchors the badges to the right edge whether or not a trail is drawn', async () => {
  const anchored = await rightEdgeOf(true)
  const bare = await rightEdgeOf(false)

  // Same right edge in both arrangements. Without the fix the second is far to
  // the left of the first -- it ends wherever the `log` link happened to.
  expect(bare).toBeCloseTo(anchored, 0)
})
