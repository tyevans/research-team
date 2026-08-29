import { useCallback, useRef, useState, type KeyboardEvent } from 'react'

import type { AttemptsApi } from '@application/lesson/use-attempts.ts'
import type { LessonDocument } from '@domain/lesson/document.ts'
import { clampSlide, deckOf, railRows, type Deck as DeckModel } from '@domain/lesson/slides.ts'
import type { ProjectId } from '@domain/shared/identifier.ts'

import { Overlay } from '../layout/OverlayHost.tsx'
import { Button, EmptyState } from '../common/primitives.tsx'
import { SlideView } from './SlideView.tsx'

/** A lesson, presented.
 *
 * **The deck is a modal `Overlay` rather than a route that replaces the page.**
 * That buys, from a primitive already in the tree: Escape delivered to the
 * topmost layer only, the page behind marked `inert`, and focus given back to
 * whatever opened the deck when it closes. Hand-rolling any of those is the
 * defect `component-system-spec.md` §2 opens with, and this surface would have
 * been the fourth copy.
 *
 * **The document view is the accessible baseline and is not replaced.** A deck
 * is a second reading, reached from a button and left with one keypress. What
 * this adds on top of the document's own accessibility:
 *
 *  - Every slide is in the DOM and off-slides carry `hidden`, so a screen
 *    reader's virtual cursor gets exactly the current slide. The rejected
 *    alternatives were unmounting (which loses a half-answered quiz on the way
 *    past) and rendering everything visible to assistive technology (which is
 *    the document view with extra steps).
 *  - Every keyboard route has a control: the rail is real buttons, the footer
 *    is real buttons. Nothing here is reachable only by a key.
 *  - Keyboard handling skips events from a form control, so typing a space
 *    into a cloze blank does not advance the slide.
 *
 * **The rail is the signature and it is doing three jobs.** It is the progress
 * indicator, the jump list, and a claim about what a lesson is in this system:
 * everything here is folded from an ordered log and the reader already reads a
 * scrub bar for sessions, so the deck's progress affordance is a scrub rather
 * than a row of dots. `docs/design/lesson-slideshow.md` §6 argues it.
 */
export const Deck = ({
  doc,
  attempts,
  label,
  withheldExplanation,
  projectId,
  slide,
  onSlide,
  onClose,
}: {
  doc: LessonDocument
  attempts: AttemptsApi
  /** What to call this lesson when it has no `#` heading of its own. Real
   *  authored output does that -- see the design document §2 -- so this is a
   *  live case rather than a defensive one. */
  label: string
  withheldExplanation: string
  projectId?: ProjectId
  slide: number
  /** Position changes go up to the URL and come back down, which is what makes
   *  a slide linkable. Deliberately not local state: two sources for one
   *  position is how a deep link and a keypress start disagreeing. */
  onSlide: (index: number) => void
  onClose: () => void
}) => {
  const deck: DeckModel = deckOf(doc)
  const index = clampSlide(deck, slide)
  const total = deck.slides.length
  const current = deck.slides[index]

  const [overview, setOverview] = useState(false)
  const [notesOpen, setNotesOpen] = useState(false)
  const returnFocus = useRef<Element | null>(null)

  // Focus moves in on open and the host gives it back on close. `Overlay`
  // deliberately does not do this -- `inert` makes the page unreachable but
  // moves nothing -- so a deck that skipped it would confine a reader to a
  // dialog with their focus still on the button behind it.
  //
  // **A callback ref, not an effect, and the reason is a render that never
  // happens.** `Overlay` returns `null` until `OverlayHost` has published its
  // portal container, which it does through a `ref` callback -- so the deck's
  // first render portals nothing and any `useRef` is still null. The host then
  // re-renders itself, but `children` is the same element object it was given,
  // so **React bails out and this component does not re-render at all**: the
  // layer appears because `Overlay` reads the container off context, and every
  // effect here has already run for the last time. A mount-only effect focuses
  // nothing, and an every-render effect never gets another render.
  //
  // Measured rather than reasoned: thirteen tests in `Deck.test.tsx` failed on
  // it, all of them by pressing a key that went to `<body>`. A callback ref
  // fires when the node is attached, which is the moment that actually exists.
  const moved = useRef(false)
  const stage = useCallback((node: HTMLDivElement | null) => {
    if (node === null || moved.current) return
    // Read before the focus below moves it, so this is still the control that
    // opened the deck.
    returnFocus.current = document.activeElement
    moved.current = true
    node.focus()
  }, [])

  const go = useCallback(
    (next: number) => {
      onSlide(clampSlide(deck, next))
    },
    // `deck` is rebuilt every render from the same document, and `clampSlide`
    // reads only its length; depending on it would rebuild this callback on
    // every render for no behavioural difference.
    [onSlide, deck.slides.length], // eslint-disable-line react-hooks/exhaustive-deps
  )

  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    // A widget owns its own keys. Space in a cloze blank is a space, and the
    // arrow keys inside a flashcard deck belong to the flashcards.
    const target = event.target
    if (target instanceof HTMLElement && isTyping(target)) return
    if (event.altKey || event.ctrlKey || event.metaKey) return

    const key = event.key
    if (key === 'ArrowRight' || key === 'ArrowDown' || key === 'PageDown' || key === ' ') {
      event.preventDefault()
      go(index + 1)
      return
    }
    if (key === 'ArrowLeft' || key === 'ArrowUp' || key === 'PageUp') {
      event.preventDefault()
      go(index - 1)
      return
    }
    if (key === 'Home') {
      event.preventDefault()
      go(0)
      return
    }
    if (key === 'End') {
      event.preventDefault()
      go(total - 1)
      return
    }
    if (key === 'o' || key === 'O') {
      event.preventDefault()
      setOverview((open) => !open)
    }
  }

  const rows = railRows(deck)
  const title = deck.title ?? label

  return (
    <Overlay label={`${title}, presented`} modal onDismiss={onClose} returnFocus={returnFocus}>
      {/* The rule is `no-noninteractive-element-interactions`, and it is asking
          for something this element already has. It wants a keyboard listener
          to sit on something operable; this *is* the operable thing -- it is
          focusable, focus is moved into it on open, and it carries the
          `group`/`aria-roledescription` pair the carousel pattern specifies.
          The alternative the rule would accept is `role="application"`, which
          switches a screen reader out of browse mode across the whole deck and
          would cost a reader far more than it buys.

          What makes the disable safe rather than convenient: **every key here
          also has a control.** Previous, Next, All slides and the rail rows are
          real buttons, and Escape is the host's. Nothing below is the only
          route to anything, which is the failure the rule exists to prevent.
          `Deck.test.tsx` holds both halves. The directive sits on its own line
          above the element because one written among the attributes attaches to
          the wrong line -- `OverlayHost`'s backdrop records the same. */}
      {/* eslint-disable-next-line jsx-a11y/no-noninteractive-element-interactions */}
      <div
        ref={stage}
        tabIndex={-1}
        onKeyDown={onKeyDown}
        // `group` with an `aria-roledescription`, which is the carousel
        // pattern: the deck is a named grouping of slides, and it is what
        // makes a keydown handler on this element legitimate rather than a
        // handler on a `<div>` that announces nothing. `jsx-a11y` rejects the
        // second, correctly.
        role="group"
        aria-roledescription="slideshow"
        aria-label={title}
        // `fixed inset-0` rather than a size: `.lay-layer-content` is
        // `position: relative` and sizes to its content, so a deck laid out
        // inside it would be as tall as its tallest slide rather than as tall
        // as the screen. `deck-root` is a hook for the browser test that
        // measures exactly that.
        className="deck-root fixed inset-0 grid grid-cols-[var(--deck-rail)_1fr] bg-bg text-fg [--deck-rail:180px] focus:outline-none max-[821px]:grid-cols-[1fr]"
      >
        <nav
          aria-label="Slides"
          // The rail: a hairline on its right edge, written as a directional
          // width beside `border-0` -- see CLAUDE.md's `border-solid` entry for
          // why the pair is the fix and either half alone is not.
          className="deck-rail flex min-h-0 flex-col gap-0 overflow-y-auto border-0 border-r border-solid border-line bg-bg-panel py-4 max-[821px]:hidden"
        >
          {rows.map((row) => (
            <RailRow
              key={row.index}
              index={row.index}
              label={row.label}
              current={row.index === index}
              onSelect={() => go(row.index)}
            />
          ))}
        </nav>

        <div className="flex min-h-0 min-w-0 flex-col">
          <header className="flex shrink-0 items-center justify-between gap-3 px-6 pt-4 pb-2">
            <p className="m-0 truncate font-mono text-xs tracking-[0.14em] text-fg-faint uppercase">
              {current?.section ?? title}
              {current && !current.opensSection && current.kind !== 'title' ? (
                <span className="ml-2 text-fg-faint normal-case opacity-70">continued</span>
              ) : null}
            </p>
            <div className="flex shrink-0 items-center gap-2">
              <span className="font-mono text-xs text-fg-faint tabular-nums">
                {total === 0 ? '0 / 0' : `${String(index + 1)} / ${String(total)}`}
              </span>
              <Button small tone="quiet" onClick={onClose}>
                Read as document
              </Button>
            </div>
          </header>

          <div className="relative min-h-0 flex-1 px-6 pb-2">
            {total === 0 ? (
              <EmptyState
                heading="This lesson has nothing to present."
                detail="It parsed, and it holds no prose and no components. Read it as a document to see the file."
              />
            ) : (
              deck.slides.map((item) => (
                <section
                  key={item.index}
                  // Every slide stays mounted. `hidden` is what takes the
                  // others out of the accessibility tree -- `base.css` gives
                  // `[hidden]` a `display: none !important` -- so a screen
                  // reader gets this slide and not the lesson.
                  hidden={item.index !== index}
                  className="h-full"
                  // `role="group"` explicitly: a `<section>` with a name is a
                  // `region`, which is a landmark, and a deck of forty
                  // landmarks makes the landmark list useless. `group` with an
                  // `aria-roledescription` is the pattern for a slide.
                  role="group"
                  aria-roledescription="slide"
                  aria-label={`Slide ${String(item.index + 1)} of ${String(total)}${
                    item.section === null ? '' : `, ${item.section}`
                  }`}
                >
                  <SlideView
                    slide={item}
                    attempts={attempts}
                    withheldExplanation={withheldExplanation}
                    {...(projectId ? { projectId } : {})}
                  />
                </section>
              ))
            )}
          </div>

          {current && current.notes.length > 0 && notesOpen ? (
            <aside
              aria-label="Speaker notes"
              className="deck-notes mx-6 mb-2 shrink-0 border-0 border-l-2 border-solid border-accent-dim bg-bg-panel-2 px-3 py-2 text-sm text-fg-dim"
            >
              {current.notes.map((note, position) => (
                <p key={position} className="m-0">
                  {note}
                </p>
              ))}
            </aside>
          ) : null}

          <footer className="flex shrink-0 items-center gap-2 px-6 pb-4">
            <Button small onClick={() => go(index - 1)} disabled={index === 0}>
              Previous
            </Button>
            <Button
              small
              tone="accent"
              onClick={() => go(index + 1)}
              disabled={total === 0 || index === total - 1}
            >
              Next
            </Button>
            <Button small tone="quiet" onClick={() => setOverview(true)}>
              All slides
            </Button>
            {current && current.notes.length > 0 ? (
              <Button small tone="quiet" onClick={() => setNotesOpen((open) => !open)}>
                {notesOpen ? 'Hide notes' : 'Speaker notes'}
              </Button>
            ) : null}
            <p className="m-0 ml-auto font-mono text-xs text-fg-faint">
              &larr; &rarr; to move &middot; o for all slides &middot; Esc to close
            </p>
          </footer>
        </div>

        {overview ? (
          <SlideOverview
            deck={deck}
            current={index}
            onPick={(next) => {
              setOverview(false)
              go(next)
            }}
            onClose={() => setOverview(false)}
          />
        ) : null}
      </div>
    </Overlay>
  )
}

/** One rail row: a monospace index, a tick, and the section name where a
 *  section begins.
 *
 * **A plain `<button>` and not the `Button` primitive, which is the opposite of
 * the usual advice here and is deliberate.** `.btn-ghost` is unlayered and sets
 * `padding`, `background`, `border-color`, `color`, `font-family` and
 * `font-size`; `.btn` adds `white-space: nowrap`. A rail row is a two-line
 * label on a 180px column, so every one of those would have had to be fought,
 * and an unlayered rule cannot be fought from `@layer utilities` -- the fight
 * would have been silent and the row would simply have refused to wrap.
 *
 * The bare-element hazard CLAUDE.md records does not apply: #313 moved
 * `tokens.css`'s `button` defaults into `@layer base` precisely so a utility on
 * a control wins, and `control-defaults.browser.test.tsx` is the standing
 * measurement. `deck.browser.test.tsx` takes the same measurement for this row,
 * because "the class is in the attribute and the rule is in the bundle" is
 * invisible to jsdom either way. */
const RailRow = ({
  index,
  label,
  current,
  onSelect,
}: {
  index: number
  label: string | null
  current: boolean
  onSelect: () => void
}) => (
  <button
    type="button"
    onClick={onSelect}
    aria-current={current ? 'true' : undefined}
    data-deck-rail-row={index}
    className="deck-rail-row focus-visible:lay-ring-inward flex w-full cursor-pointer items-start gap-2 border-none bg-transparent px-3 py-1 text-left hover:bg-bg-hover"
  >
    <span
      aria-hidden
      className={
        current
          ? 'deck-tick mt-[7px] h-[2px] w-4 shrink-0 bg-accent'
          : 'deck-tick mt-[7px] h-[2px] w-2 shrink-0 bg-line-strong'
      }
    />
    <span
      className={
        current
          ? 'font-mono text-xs text-accent tabular-nums'
          : 'font-mono text-xs text-fg-faint tabular-nums'
      }
    >
      {String(index + 1).padStart(2, '0')}
    </span>
    {label === null ? null : (
      <span
        className={
          current
            ? 'leading-snug flex-1 text-xs text-fg'
            : 'leading-snug flex-1 text-xs text-fg-dim'
        }
      >
        {label}
      </span>
    )}
  </button>
)

/** Every slide at once, as a grid of what each one actually says.
 *
 * Its own non-modal layer rather than a panel inside the deck: it is
 * dismissable, it sits over the deck, and the host is what decides that Escape
 * closes the overview and not the deck underneath it. A `useState` boolean plus
 * a hand-written Escape listener would have closed both on one keypress, which
 * is the exact failure `Drawer`'s docstring records.
 *
 * Exported for its story alone. The deck opens it from state, so a story of the
 * *deck* cannot show it without a story-only prop -- and a prop that exists to
 * be photographed is a prop somebody later reads as a feature. */
export const SlideOverview = ({
  deck,
  current,
  onPick,
  onClose,
}: {
  deck: DeckModel
  current: number
  onPick: (index: number) => void
  onClose: () => void
}) => (
  <Overlay label="All slides" modal onDismiss={onClose}>
    <div className="deck-overview fixed inset-0 flex flex-col gap-3 overflow-y-auto bg-bg p-6 shadow-1">
      <div className="flex items-center justify-between">
        <h2 className="m-0 font-mono text-xs tracking-[0.14em] text-fg-faint uppercase">
          All slides
        </h2>
        <Button small tone="quiet" onClick={onClose}>
          Back to the deck
        </Button>
      </div>
      <ol className="m-0 grid list-none grid-cols-[repeat(auto-fill,minmax(200px,1fr))] gap-3 p-0">
        {deck.slides.map((slide) => (
          <li key={slide.index}>
            {/* A bare `<button>` for `RailRow`'s reason: `.btn`'s unlayered
                `white-space: nowrap` and padding cannot be overridden from a
                utility, and a thumbnail is four wrapped lines in a box. */}
            <button
              type="button"
              onClick={() => onPick(slide.index)}
              aria-current={slide.index === current ? 'true' : undefined}
              className={
                slide.index === current
                  ? 'deck-thumb focus-visible:lay-ring-inward flex h-[124px] w-full cursor-pointer flex-col items-start gap-1 border border-accent bg-bg-panel-2 p-3 text-left'
                  : 'deck-thumb focus-visible:lay-ring-inward flex h-[124px] w-full cursor-pointer flex-col items-start gap-1 border border-line bg-bg-panel p-3 text-left'
              }
            >
              <span className="font-mono text-xs text-fg-faint tabular-nums">
                {String(slide.index + 1).padStart(2, '0')}
              </span>
              <span className="leading-snug line-clamp-4 text-xs text-fg-dim">
                {summarise(slide)}
              </span>
            </button>
          </li>
        ))}
      </ol>
    </div>
  </Overlay>
)

/** What a thumbnail says. Deliberately the slide's own words rather than a
 *  scaled render of it: a 200px-wide copy of a paragraph is unreadable, and the
 *  question a reader is asking the overview is "which slide was the one
 *  about…". A component names its kind, because a quiz's own prompt is the
 *  thing the reader is trying to get back to. */
const summarise = (slide: DeckModel['slides'][number]): string => {
  if (slide.kind === 'component') return `${slide.block.type} · ${slide.section ?? ''}`.trim()
  if (slide.kind === 'title') return slide.title
  const plain = slide.text
    .replace(/\[\[src:[^\]]*\]\]/g, '')
    .replace(/[#>*_`]/g, '')
    .trim()
  return plain.length > 160 ? `${plain.slice(0, 160)}…` : plain
}

/** Whether a keystroke belongs to something the reader is typing into.
 *
 * `isContentEditable` as well as the three tags, because `Markdown` renders no
 * editable regions today and a future one would silently start swallowing its
 * own spacebar. */
const isTyping = (element: HTMLElement): boolean =>
  element.isContentEditable ||
  element instanceof HTMLInputElement ||
  element instanceof HTMLTextAreaElement ||
  element instanceof HTMLSelectElement
