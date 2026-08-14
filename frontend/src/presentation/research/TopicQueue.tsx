import clsx from 'clsx'

import type { Dispatch } from '@domain/research/dispatch.ts'
import type { TopicFocus, TopicView } from '@domain/research/topic.ts'
import type { TopicId } from '@domain/shared/identifier.ts'

import { Button, EmptyState } from '../common/primitives.tsx'
import { Tooltip } from '../common/Tooltip.tsx'
import { TopicRow } from '../entity/topic/TopicRow.tsx'

/** The slices, in the order they are offered: everything, then the one that
 *  wants a person, then what is still moving, then what is done with. */
const FOCUSES: readonly (readonly [TopicFocus, string])[] = [
  ['all', 'All'],
  ['attention', 'Needs you'],
  ['live', 'Live'],
  ['closed', 'Closed'],
]

/** Nothing has been gathered for this topic yet.
 *
 * The one thing in this feature that disables a control, and it is worth it:
 * synthesising a topic with no sources and no findings produces the model's
 * own prior knowledge presented as project findings, which is confabulation
 * that looks like a deliverable. Research is the action that fixes it, and
 * research is not built yet — so the button says why rather than offering a
 * next step it cannot take.
 */
const hasNothingToSynthesise = (topic: TopicView): boolean =>
  topic.sources === 0 && topic.findings === 0

/** The scroller's inward focus ring, and why `-2px` rather than the global
 *  `+1px`.
 *
 * The same measured fix `DocumentBrowser.tsx` carries and the second of the two
 * live exposures `component-system-spec.md` §5.2 names. Chromium makes a scroll
 * container focusable with no `tabIndex` at all, so this list is a real tab stop
 * as soon as the queue is longer than the rail. `tokens.css`'s global
 * `:focus-visible` draws 2px at `outline-offset: 1px` — three pixels *outside*
 * the border box — and `.topic-list` had `padding: 0` and `overflow-y: auto`,
 * so every one of those pixels was on the far side of its own clip.
 * `topic-list-ring.browser.test.tsx` is the measurement.
 *
 * **A named class rather than the utilities that read like the obvious fix**,
 * and this was found by measuring rather than by reasoning.
 * `tokens.css`'s `:focus-visible` is *unlayered*, and Tailwind's utilities are
 * in `@layer utilities` — an unlayered normal declaration beats a layered one
 * whatever the specificity, so `.focus-visible\:outline-offset-\[-2px\]` at
 * (0,2,0) still loses to a bare `:focus-visible` at (0,1,0), and the offset
 * resolves to the global `+1px` with every utility present in the class
 * attribute. Measured that way in Chromium at the 1440x900 viewport
 * `vite.config.ts` sets, with a 340x280 list: ring `72.5..` against a clip
 * starting at `75.5` — three pixels out, exactly the defect the utilities
 * claimed to fix.
 *
 * `.lay-ring-inward` (`layout.css`) is unlayered at (0,2,0) and wins that
 * comparison, and it declares the ring whole — width, colour and offset — so
 * nothing about it depends on the global rule it is overriding. Tailwind's `!`
 * modifier also works (important reverses layer order) and this list carried
 * it for a day; it lost on three counts, all in `layout.css`'s comment: this
 * codebase uses `!` nowhere, a forgotten one fails silently, and a rule is
 * somewhere the measurement can live. Two spellings of one fix is the thing to
 * avoid, so both the document browser and this list use the class.
 *
 * This is the same shape `tree.css:368` and `shell.css:257` already record for
 * `.chip-*`, met a third time. */
const RING_INWARD = 'lay-ring-inward'

/** One slice of the queue, off and on.
 *
 * Four buttons in a `radiogroup`, so the chosen one is announced by
 * `aria-checked` and drawn by these strings. The tone is applied per branch
 * rather than as a base colour plus an override, deliberately: two `text-*`
 * utilities on one element resolve in Tailwind's emission order, not the
 * attribute's, so "dim unless chosen" written that way is a coin toss. */
const FOCUS_TAB =
  'flex-1 basis-0 cursor-pointer rounded-md border border-solid bg-transparent px-[6px] py-[4px] font-sans text-[11px] whitespace-nowrap'

/** `1st`, `2nd`, `3rd`, `4th`. Small enough that a dependency would be absurd. */
const ordinal = (position: number): string => {
  const tens = position % 100
  if (tens >= 11 && tens <= 13) return `${String(position)}th`
  const suffix = ['th', 'st', 'nd', 'rd'][position % 10] ?? 'th'
  return `${String(position)}${suffix}`
}

/** The chip's box, without its tone.
 *
 * Every declaration here was measured and each one is load-bearing; this is a
 * transcription of `.topic-dispatch` and not a fresh choice.
 *
 * `inline-block` is what makes the clamp do anything, and its absence is why
 * this chip was believed clamped for as long as it was: `max-width`,
 * `overflow` and `text-overflow` **do not apply to a non-replaced inline box**.
 * They worked only while the chip was a direct flex child (a flex item is
 * blockified); then the failed chip gained a `Tooltip`, its parent became the
 * trigger rather than the flex line, and every one of them silently became a
 * comment. Measured in Chromium: the failed chip drew **708px wide** inside a
 * 294px line.
 *
 * `flex-none` is the opposite failure on the same line. `overflow: hidden`
 * takes a flex item's automatic minimum size to zero, so the chips *not*
 * wrapped in a tooltip were free to shrink all the way — measured at **0px**
 * for `⟳ understanding · running`, which is to say the feedback for pressing
 * the button was not drawn at all. Refusing to shrink puts every fact on the
 * line under one rule: each is its own width and `.ent-topic-facts` clips the
 * tail.
 *
 * `TopicQueue.browser.test.tsx` measures both directions and is the only place
 * that can — jsdom lays nothing out, so a chip painted 90px past the edge and
 * one sitting comfortably inside produce identical markup. */
const CHIP =
  'inline-block max-w-[18ch] flex-none overflow-hidden align-middle font-mono text-xs text-ellipsis whitespace-nowrap'

/** What one dispatch reads as on the row that produced it.
 *
 * Kept for finished dispatches rather than cleared, deliberately: a chip that
 * vanishes on the next render is how a reader concludes the button did
 * nothing. A failure in particular has to persist, because the failure and the
 * retry are the same row.
 *
 * Deliberately *not* routed through `EntityStatus`, which was the first
 * attempt. `EntityStatus` derives its tone from the status of an entity, and
 * these five words name the state of an *action* taken against one — a topic
 * whose dispatch failed is not a failed topic, and painting `failed` in the
 * entity's own status palette beside the topic's real status (`investigating`)
 * puts two chips on one row that look like they disagree about the same fact.
 *
 * That worry is settled rather than still open: they are no longer beside each
 * other. `TopicRow` shows this chip *in place of* the status while a dispatch
 * is on the row, which #40 forced for width and which this paragraph had
 * already argued for on its own terms.
 */
export const DispatchChip = ({ dispatch }: { dispatch: Dispatch }) => {
  if (dispatch.status === 'queued') {
    // Neutral, and `.topic-dispatch-queued` is gone rather than translated: it
    // declared nothing in any stylesheet and never had, so a reader of the
    // markup was told a queued chip had a look of its own and it did not. Two
    // of the five states are deliberately the base tone -- queued and cancelled
    // are both "not happening", and the three that are toned are the three a
    // reader has to act on.
    return (
      <span className={clsx(CHIP, 'text-fg-dim')}>
        ⧗ queued · {dispatch.position === null ? 'waiting' : ordinal(dispatch.position)}
      </span>
    )
  }
  if (dispatch.status === 'running') {
    return <span className={clsx(CHIP, 'text-accent')}>⟳ {dispatch.action} · running</span>
  }
  if (dispatch.status === 'failed') {
    return (
      // The tooltip carries the untruncated text: the chip is clamped to one
      // line in a 320px rail, and a model's error can be a paragraph. It was a
      // `title`, which is to say the untruncated text was available to a
      // hovering mouse and to nothing else — the test that covers this is
      // named for reachability and was passing against an attribute no
      // keyboard can reach.
      <Tooltip explanation={dispatch.detail ?? 'no reason given'}>
        <span className={clsx(CHIP, 'text-k-failure')}>
          ✕ {dispatch.action} · failed · {dispatch.detail ?? 'no reason given'}
        </span>
      </Tooltip>
    )
  }
  if (dispatch.status === 'cancelled') {
    return <span className={clsx(CHIP, 'text-fg-dim')}>⊘ {dispatch.action} · cancelled</span>
  }
  return (
    <span className={clsx(CHIP, 'text-fg-faint')}>
      ✓ {dispatch.action} · {dispatch.path ?? 'written'}
    </span>
  )
}

/** The topic queue, as markup over data it is handed.
 *
 * Holds no query, no mutation and no container: `useTopicQueue` does all of
 * that and this renders the answer. The split is what lets a story put the
 * queue in every state it has — a failed dispatch, a filter that matches
 * nothing, an empty corpus — none of which was reachable while the component
 * that drew them also fetched them.
 *
 * The rows are `entity/topic/TopicRow`, which is where the queue stops
 * spelling `status.replace('_', ' ')` for the fourth time in this codebase.
 * Two things the old row drew are deliberately gone with it:
 *
 * - **Triggers.** A row's height is now a function of its kind rather than its
 *   content, which is the contract `TopicRow` documents and L-F8 records a
 *   122px hole for breaking. Triggers are prose of unbounded length; they are
 *   rendered by `TopicDetail`, which the Manage dialog shows.
 * - **The topic's own status word, twice.** `EntityStatus` spells and tones it
 *   from the status itself, so `not_pursuing` reads the same here as it does
 *   on the landing page.
 */
export const TopicQueue = ({
  topics,
  counts,
  focus,
  search,
  dispatches,
  running,
  queuedCount,
  dispatching,
  stopping,
  onFocusChange,
  onSearchChange,
  onDispatch,
  onManage,
  onStop,
}: {
  /** Already filtered and ranked. Ranking is `byUrgency`, a domain rule, and
   *  a component that re-sorted what it was given could disagree with the
   *  counts beside it. */
  topics: readonly TopicView[]
  /** Counted over the *whole* queue, before filtering — which is what lets
   *  `counts.all` tell "nothing seeded" apart from "nothing matches". */
  counts: Record<TopicFocus, number>
  focus: TopicFocus
  search: string
  dispatches: ReadonlyMap<string, Dispatch>
  running: boolean
  queuedCount: number
  dispatching: boolean
  stopping: boolean
  onFocusChange: (focus: TopicFocus) => void
  onSearchChange: (search: string) => void
  onDispatch: (topicId: TopicId) => void
  onManage: (topicId: TopicId) => void
  onStop: () => void
}) => (
  <div className="flex h-full flex-col gap-[8px]">
    {/* `.topic-filters` wrapped these two and is *dissolved* rather than
        translated. It declared nothing in any stylesheet, so it laid out as a
        plain block: the search box and the tabs sat flush against each other
        while every other pair in this column had 8px between them. As two
        items of the column they get that 8px, which is the only visible change
        in this rewrite and is the one the wrapper was hiding. Grouping them
        again would mean choosing a second, smaller gap for no reason a reader
        could see. */}

    {/* `input` stays a class: it is the shared field style, declared for every
        text field in the console, and it is not this slice's to dissolve. */}
    <input
      type="search"
      className="input w-full"
      placeholder="Filter topics"
      aria-label="Filter topics"
      value={search}
      onChange={(event) => onSearchChange(event.target.value)}
    />
    {/* A radio group, not a row of buttons: these four are one choice with
        one answer, and that is what a screen reader should be told. The
        count rides on the label so an empty slice announces itself as empty
        before it is picked. */}
    <div className="flex gap-[2px]" role="radiogroup" aria-label="Which topics to show">
      {FOCUSES.map(([value, label]) => (
        <button
          key={value}
          type="button"
          role="radio"
          aria-checked={focus === value}
          className={clsx(
            FOCUS_TAB,
            focus === value
              ? 'border-accent text-accent'
              : 'border-line text-fg-dim hover:border-fg-dim hover:text-fg',
          )}
          onClick={() => onFocusChange(value)}
        >
          {label}{' '}
          {/* The count took its colour from a descendant selector on the
              chosen tab. There is no descendant selector in a utility, so the
              condition is read twice rather than once — the alternative,
              `text-inherit`, would drop the dim tone the *unchosen* tabs give
              their counts, which is the contrast the whole row is built on. */}
          <span className={clsx('tabular-nums', focus === value ? 'text-accent' : 'text-fg-dim')}>
            {counts[value]}
          </span>
        </button>
      ))}
    </div>

    {/* The aggregate, so a reader who scrolled away from the running row still
        knows something is going. One stop control here rather than a cancel
        per queued row, because cancel is per project on the server and a
        per-row control would offer an action it cannot honour. */}
    {running || queuedCount > 0 ? (
      <div className="mb-[6px] flex items-center justify-between gap-[8px] rounded-md border border-solid border-line px-[6px] py-[4px] font-mono text-xs text-fg-dim">
        <span>
          {running ? '1 running' : 'none running'}
          {queuedCount > 0 ? `, ${String(queuedCount)} queued` : ''}
        </span>
        <Tooltip asChild explanation="Stop the running dispatch and drop everything queued">
          <Button small disabled={stopping} onClick={onStop}>
            Stop
          </Button>
        </Tooltip>
      </div>
    ) : null}

    {counts.all === 0 ? (
      <EmptyState heading="No topics" detail="Nothing has been seeded into this queue yet." />
    ) : topics.length === 0 ? (
      // Distinct from "No topics" above, and the distinction is the whole
      // point: that one means the queue is empty, this one means the queue has
      // work in it that the current filter is hiding.
      <EmptyState
        heading="No topics match"
        detail="Nothing in this project matches that filter. Widen it to see the rest of the queue."
      />
    ) : (
      // `flex-auto` and not `flex-1`: `flex-1` is `1 1 0%`, and the rule this
      // replaces was `flex: 1 1 auto`. The difference shows whenever the filter
      // box and the tabs above share the column, which is always.
      //
      // `data-topic-scroll` rather than a class hook, because what is being
      // identified is "the element the queue scrolls" and the browser test has
      // to find it now that the class names are dressing any refactor may
      // reshuffle.
      <ul
        data-topic-scroll
        className={clsx(
          'm-0 flex min-h-0 flex-auto list-none flex-col gap-[6px] overflow-y-auto p-0',
          RING_INWARD,
        )}
      >
        {topics.map((topic) => {
          const dispatch = dispatches.get(topic.topicId)
          const empty = hasNothingToSynthesise(topic)
          return (
            <TopicRow
              key={topic.topicId}
              topic={topic}
              slots={{
                // The chip stays on the meta line rather than taking one of
                // its own, because a row whose height depends on whether a
                // dispatch happened is the variable-height row `TopicRow`
                // exists to rule out. It is `note` rather than part of
                // `primary` because it is read rather than pressed: it reports
                // on the verb, it is not the verb, and inside `primary` it sat
                // in the group that must never yield -- which is how a failed
                // dispatch's sentence came to push both verbs off the row.
                note: dispatch ? <DispatchChip dispatch={dispatch} /> : null,
                primary: (
                  <>
                    {/* One button rather than the split control the design
                        sketches: with one action there is nothing to split,
                        and a menu holding a single item is a click in front of
                        a button. It becomes a split button when `research` and
                        `lesson` land. */}
                    {/* `aria-disabled` rather than `disabled`, and the reason
                        is the explanation beside it: this button's sentence
                        exists *because* it is off, and a `disabled` element
                        takes neither focus nor pointer events, so the tooltip
                        it hangs on could never open. Keeping it focusable is
                        what makes "why is this off" answerable at all — the
                        old `title` was not an answer, it was an answer a mouse
                        could find. The press is guarded here instead, which is
                        the cost: nothing but this handler stops the click. */}
                    <Tooltip
                      asChild
                      explanation={
                        empty
                          ? 'Nothing gathered for this topic yet'
                          : 'Write down what this project understands about this topic'
                      }
                    >
                      {/* `.topic-dispatch-button` was here and is gone with no
                          replacement. It declared nothing, and there was
                          nothing for it to declare: `Button` already dresses
                          this, and `shell.css`'s `.btn[aria-disabled='true']`
                          already draws the off state this button spends most of
                          its life in. A name that hooks nothing cannot be told
                          from one whose rule was lost, which is the whole
                          failure `check-deleted.mjs` exists about. */}
                      <Button
                        small
                        aria-disabled={empty || dispatching || dispatch?.status === 'queued'}
                        onClick={() => {
                          if (empty || dispatching || dispatch?.status === 'queued') return
                          onDispatch(topic.topicId)
                        }}
                      >
                        Write understanding
                      </Button>
                    </Tooltip>
                  </>
                ),
                // Described rather than rendered, so the row can put it behind
                // a `⋯`. It was a 58px button on a 294px line, and that button
                // plus its gap is most of the reason the chip above it was
                // drawn nowhere.
                overflow: [
                  { key: 'manage', label: 'Manage', onSelect: () => onManage(topic.topicId) },
                ],
              }}
            />
          )
        })}
      </ul>
    )}
  </div>
)
