import type { Meta, StoryObj } from '@storybook/react-vite'

import { CmpButton } from '../lesson/widgets.tsx'

import { Button, Chip, Disclosure, EmptyState, ErrorBox, Loading } from './primitives.tsx'

/** The shapes every view reaches for, and the gallery entry they never had.
 *
 * `primitives.tsx` is the most-rendered file in `presentation` and had no
 * story until now. That is the exact gap `.storybook/main.ts` says this
 * workbench exists to close: "finding out whether a thing already existed
 * meant grepping for a name you had to guess first."
 *
 * Two findings came straight out of writing it, and neither is visible from
 * any single file:
 *
 * - **There are two button implementations.** `TwoButtons` puts them side by
 *   side. See the note on that story.
 * - **Five of the fourteen chip tones are drawn by a stylesheet that is on
 *   the deletion list.** `Chip`'s own docstring says the `tone` prop "goes
 *   when the last one does". `ChipTones` is what makes "the last one" a
 *   number rather than a guess.
 */
const meta: Meta = {
  title: 'common/primitives',
}

export default meta

type Story = StoryObj

const Row = ({ heading, children }: { heading: string; children: React.ReactNode }) => (
  <section style={{ padding: 'var(--space-3)' }}>
    <h3 style={{ font: 'inherit', color: 'var(--fg-dim)', margin: '0 0 var(--space-2)' }}>
      {heading}
    </h3>
    <div style={{ display: 'flex', gap: 'var(--space-2)', flexWrap: 'wrap', alignItems: 'center' }}>
      {children}
    </div>
  </section>
)

/** All five tones, at both sizes.
 *
 *  The rule to check by eye: `accent` is the only filled one, and it is the
 *  only one a view should have more than one of per decision. A pane with two
 *  filled buttons has not chosen. */
export const ButtonTones: Story = {
  render: () => (
    <>
      <Row heading="tone">
        <Button>default</Button>
        <Button tone="accent">accent</Button>
        <Button tone="quiet">quiet</Button>
        <Button tone="danger">danger</Button>
        <Button tone="ghost">ghost</Button>
      </Row>
      <Row heading="small">
        <Button small>default</Button>
        <Button small tone="accent">
          accent
        </Button>
        <Button small tone="quiet">
          quiet
        </Button>
        <Button small tone="danger">
          danger
        </Button>
        <Button small tone="ghost">
          ghost
        </Button>
      </Row>
    </>
  ),
}

/** Off, both ways round, and pressed.
 *
 *  `shell.css` carries the reasoning: `aria-disabled` is styled exactly as
 *  `disabled`, because a `disabled` element takes neither focus nor pointer
 *  events and so can never open the tooltip that says why it is off. The two
 *  must be indistinguishable here. If they are not, the rule has been edited.
 *
 *  `aria-pressed` is accent border and accent text — and is deliberately
 *  excluded on `.btn-accent`, which would otherwise draw its label in its own
 *  background colour. The last pair below is that exclusion. */
export const ButtonStates: Story = {
  render: () => (
    <>
      <Row heading="off">
        <Button disabled>disabled</Button>
        <Button aria-disabled="true">aria-disabled</Button>
      </Row>
      <Row heading="pressed">
        <Button aria-pressed="true">pressed</Button>
        <Button aria-pressed="false">not pressed</Button>
      </Row>
      <Row heading="pressed, excluded on accent">
        <Button tone="accent" aria-pressed="true">
          accent pressed
        </Button>
        <Button tone="accent">accent</Button>
      </Row>
    </>
  ),
}

/** **A finding, not a demonstration.** The console has two button
 *  implementations and this is the only place they meet.
 *
 *  `Button` (`.btn`, `shell.css`) is used everywhere. `CmpButton` (`.cmp-btn`,
 *  `components.css`) is used by six call sites, all of them lesson widgets:
 *  `Mcq`, `Cloze` and `Flashcards`.
 *
 *  They differ by more than a name. Measured from the two stylesheets:
 *
 *  | | `.btn` | `.cmp-btn` |
 *  |---|---|---|
 *  | padding | `5px 11px` | `4px 11px` |
 *  | colour | `--fg` | `--fg-dim` |
 *  | primary | accent **fill** | accent **outline**, fill on hover |
 *  | focus offset | via the global rule | `2px`, declared again |
 *
 *  So a lesson's buttons are one pixel shorter and one tier dimmer than every
 *  other button in the console, and its primary action is an outline where
 *  every other primary action is a fill.
 *
 *  Consolidating is not a rename. `Button` has no accent-outline tone —
 *  `.btn[aria-pressed='true']` is the nearest thing and it means "pressed",
 *  not "primary". So the merge needs a decision about what a lesson's submit
 *  button should look like, and that decision is yours rather than a
 *  refactor's. This story is here so it can be made by looking. */
export const TwoButtons: Story = {
  render: () => (
    <>
      <Row heading="Button — the console">
        <Button>submit</Button>
        <Button tone="accent">submit</Button>
      </Row>
      <Row heading="CmpButton — the lesson widgets">
        <CmpButton label="submit" onClick={() => undefined} />
        <CmpButton label="submit" primary onClick={() => undefined} />
      </Row>
      <Row heading="off, both">
        <Button disabled>submit</Button>
        <CmpButton label="submit" disabled onClick={() => undefined} />
      </Row>
    </>
  ),
}

/** Every tone a stylesheet draws, plus the undressed default.
 *
 *  `Chip` carries its shape as utilities and its colour as a stylesheet class,
 *  and the docstring says the `tone` prop is deleted when the last stylesheet
 *  tone goes. Fourteen is the number that has to reach zero. */
export const ChipTones: Story = {
  render: () => (
    <>
      <Row heading="default (no tone)">
        <Chip>plain</Chip>
      </Row>
      <Row heading="run endings">
        <Chip tone="run-done">run-done</Chip>
        <Chip tone="run-bad">run-bad</Chip>
        <Chip tone="run-short">run-short</Chip>
      </Row>
      <Row heading="outcome">
        <Chip tone="ok">ok</Chip>
        <Chip tone="warn">warn</Chip>
        <Chip tone="fail">fail</Chip>
        <Chip tone="done">done</Chip>
        <Chip tone="held">held</Chip>
        <Chip tone="unknown">unknown</Chip>
      </Row>
      <Row heading="position">
        <Chip tone="current">current</Chip>
        <Chip tone="upcoming">upcoming</Chip>
        <Chip tone="present">present</Chip>
        <Chip tone="fork">fork</Chip>
        <Chip tone="readonly">readonly</Chip>
      </Row>
    </>
  ),
}

/** The three ways a pane says it has nothing to show.
 *
 *  They share `.empty` and `.error-box` in `states.css`, which is what stops
 *  the "three subtly different empty states" `primitives.tsx` was extracted to
 *  end. Seeing them together is what keeps that true. */
export const States: Story = {
  render: () => (
    <div style={{ display: 'grid', gap: 'var(--space-3)', padding: 'var(--space-3)' }}>
      <EmptyState heading="No documents" />
      <EmptyState heading="No documents" detail="Seed a topic to start collecting them." />
      <Loading what="documents" />
      <ErrorBox heading="Could not load documents" message="the server answered 503" />
      <ErrorBox
        heading="Could not load documents"
        message="the server answered 503"
        onRetry={() => undefined}
      />
    </div>
  ),
}

/** A fold, both ways round.
 *
 *  A `<button>` driving `aria-controls` rather than `<details>`, because the
 *  open state has to survive a re-render driven from elsewhere. The caret is
 *  `aria-hidden`; the state a screen reader gets is `aria-expanded`. */
export const Folds: Story = {
  render: () => (
    <div style={{ display: 'grid', gap: 'var(--space-2)', padding: 'var(--space-3)' }}>
      <Disclosure label="closed" open={false} onToggle={() => undefined}>
        <p>Not rendered while closed — the body is `null`, not merely hidden.</p>
      </Disclosure>
      <Disclosure label="open" open onToggle={() => undefined}>
        <p>Rendered.</p>
      </Disclosure>
    </div>
  ),
}
