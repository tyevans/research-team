import type { Meta, StoryObj } from '@storybook/react-vite'

import { AskGlyph, SlidersGlyph } from '../project/topics/TopicControls.tsx'
import { NarrowGlyph, PenGlyph, SearchGlyph } from '../research/TopicQueue.tsx'
import { Glyph } from './Glyph.tsx'

/** The console's whole icon set, on one page, at the size it is drawn at.
 *
 * This console imports no icon library — `Glyph`'s own docstring gives the
 * reason — so every one of these five was drawn by hand, in two different
 * files, weeks apart. **Whether they read as one family is the only question
 * about them that no test can answer**, and it is a question that gets
 * answered wrongly by looking at each in isolation: each is legible on its
 * own, and the failure mode is a set where one stroke is heavier, one shape
 * sits low in its box, or two of them read as the same picture at 12px.
 *
 * So the page is the comparison rather than a catalogue. `Glyph` is a frame
 * with no output of its own, and a story showing it empty would show a blank
 * 12×12 box; what it *has* is the five things it frames, side by side.
 *
 * The glyphs are imported from the components that ship them rather than
 * redrawn here. A story that copied the path data would be a second renderer
 * of it, and would go on showing a coherent family after the real one drifted
 * — which is precisely the failure this page exists to catch.
 *
 * What to check, in order of how badly it would fail:
 *
 * - **`InTheirButtons`** — the five in the `.btn-ghost.btn-sm` dressing they
 *   actually wear, at the two places they actually sit: three on a topic row,
 *   two on the queue toolbar. Optical weight is a property of the pair
 *   *glyph + button*, not of the glyph, and this is the only view of it.
 * - **`Enlarged`** — the same five at 4×. Every one is a `viewBox` of 16
 *   rendered at 12, so a path that is a smudge at shipping size is legible
 *   here, which is how a badly-centred shape is diagnosed rather than merely
 *   noticed.
 * - **`AgainstTheStates`** — `.btn` sets colour on hover and on
 *   `[aria-disabled='true']`, and the glyphs take `currentColor` precisely so
 *   they follow it. A glyph that hard-coded a stroke would look correct here
 *   until the control beside it went off.
 *
 * The pairing worth staring at is `SearchGlyph` and `NarrowGlyph`: both are
 * about a question being examined, they sit two controls apart on the same
 * row, and if they read as the same picture then the row offers two verbs a
 * reader cannot tell apart. `PenGlyph` between them is what makes that
 * comparison honest rather than a side-by-side of two things chosen to differ.
 */
const meta: Meta = {
  title: 'common/Glyph',
  parameters: { layout: 'centered' },
}

export default meta

type Story = StoryObj

/** Named rather than positional, because a page whose whole job is comparison
 *  is useless if a reader cannot say which one is wrong. */
const GLYPHS = [
  ['SlidersGlyph', <SlidersGlyph key="sliders" />],
  ['AskGlyph', <AskGlyph key="ask" />],
  ['AskGlyph incoming', <AskGlyph key="incoming" incoming />],
  ['SearchGlyph', <SearchGlyph key="search" />],
  ['PenGlyph', <PenGlyph key="pen" />],
  ['NarrowGlyph', <NarrowGlyph key="narrow" />],
] as const

/** Inline styles and CSS variables rather than utilities, which is the
 *  standing rule for a story's own scaffolding: what is under test here is the
 *  glyphs and `.btn-ghost`, and a caption dressed in utilities would be a
 *  second thing on the page that could break. */
const Caption = ({ children }: { children: string }) => (
  <span style={{ font: 'var(--t-xs)/1.4 var(--font-mono)', color: 'var(--fg-dim)' }}>
    {children}
  </span>
)

/** The set in its dressing, split the way the console splits it.
 *
 * Two groups rather than six in a line, because the thing being judged is
 * whether the row's three and the toolbar's three look like they came from the
 * same hand *while sitting apart on screen*, which a single even row would
 * flatter.
 */
export const InTheirButtons: Story = {
  render: () => (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '18px', padding: '24px' }}>
      {(
        [
          ['on a topic row', GLYPHS.slice(3)],
          ['on the queue toolbar', GLYPHS.slice(0, 3)],
        ] as const
      ).map(([where, group]) => (
        <div key={where} style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
          <Caption>{where}</Caption>
          <div style={{ display: 'flex', alignItems: 'center', gap: '2px' }}>
            {group.map(([name, glyph]) => (
              // `.btn.btn-ghost.btn-sm` written out rather than reached for
              // through `Button`: what is being shown is the dressing, so the
              // story naming it is the story saying what it is showing.
              <button key={name} type="button" className="btn btn-ghost btn-sm" aria-label={name}>
                {glyph}
              </button>
            ))}
          </div>
        </div>
      ))}
    </div>
  ),
}

/** 4×, with each one's name under it.
 *
 * `transform: scale` rather than a larger `Glyph`, deliberately: scaling the
 * rendered 12px element magnifies exactly what ships, where re-rendering the
 * same paths at 48px would quietly fix any rounding that is part of the
 * defect.
 */
export const Enlarged: Story = {
  render: () => (
    <div style={{ display: 'flex', gap: '32px', padding: '32px', alignItems: 'flex-end' }}>
      {GLYPHS.map(([name, glyph]) => (
        <div
          key={name}
          style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '12px' }}
        >
          <div style={{ width: '48px', height: '48px' }}>
            <div style={{ transform: 'scale(4)', transformOrigin: 'top left' }}>{glyph}</div>
          </div>
          <Caption>{name}</Caption>
        </div>
      ))}
    </div>
  ),
}

/** On, off, and the frame with nothing in it.
 *
 * The empty `Glyph` is here rather than in a story of its own, and this is the
 * only place it earns being shown: it is the 12×12 box every one of the five
 * is drawn inside, so seeing it beside them is how a glyph that overflows its
 * `viewBox` or sits low in it becomes visible as a *difference* rather than as
 * a feeling.
 *
 * The disabled column is the one that fails silently. `shell.css`'s
 * `.btn[aria-disabled='true']` dims the button, and the glyphs follow only
 * because they stroke `currentColor` — one that named a colour would stay
 * bright in a control that is off, which reads as a control that is broken.
 */
export const AgainstTheStates: Story = {
  render: () => (
    <div style={{ display: 'flex', gap: '24px', padding: '24px' }}>
      {(
        [
          ['enabled', false],
          ['aria-disabled', true],
        ] as const
      ).map(([state, off]) => (
        <div key={state} style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
          <Caption>{state}</Caption>
          <div style={{ display: 'flex', alignItems: 'center', gap: '2px' }}>
            {GLYPHS.map(([name, glyph]) => (
              <button
                key={name}
                type="button"
                className="btn btn-ghost btn-sm"
                aria-label={`${name}, ${state}`}
                aria-disabled={off}
              >
                {glyph}
              </button>
            ))}
            <button
              type="button"
              className="btn btn-ghost btn-sm"
              aria-label={`empty frame, ${state}`}
              aria-disabled={off}
            >
              <Glyph>{null}</Glyph>
            </button>
          </div>
        </div>
      ))}
    </div>
  ),
}
