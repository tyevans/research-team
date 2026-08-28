import clsx from 'clsx'
import { useState, type ReactNode } from 'react'

import type { TopicView } from '@domain/research/topic.ts'
import { isClosed } from '@domain/research/topic.ts'

import { Menu, MenuItem, MenuTrigger } from '../../common/Menu.tsx'
import { EntityStatus } from '../EntityStatus.tsx'

/** Affordances a topic row can be given, by the view that knows why.
 *
 * Named slots rather than `children`, so a story can enumerate "row with
 * dispatch" against "row with nothing", and so a type error catches a row
 * rendering a verb it was not given.
 *
 * **Three, and the ceiling is four.** The design's own tripwire: more than four
 * named slots means the density set is wrong rather than the slot set, and the
 * correction at that point is a fifth density, not a sixth slot. Recording the
 * count here is what makes that checkable later instead of aspirational.
 *
 * The third was not a new affordance. `note` was already being passed, inside
 * `primary`, which is how a paragraph-length error came to sit in the group
 * that must never shrink. Splitting it is what gives the line a give-order at
 * all.
 */
export interface TopicRowSlots {
  /** The verbs this row offers on the line — today three dispatch icons. The
   *  view owns them because the view owns the reason one of them is disabled:
   *  R-F3.4's single disabled control is carefully reasoned about at its call
   *  site, and a row that decided its own disabled-ness would have to
   *  re-derive that reasoning.
   *
   *  It was one worded button and the slot did not have to change to hold
   *  three icons, which is the whole argument for it being a `ReactNode`
   *  rather than a `TopicVerb[]` like `overflow` below. `overflow` is a
   *  description because a `Menu` will not route the keyboard to anything that
   *  is not a `MenuItem`; this group has no such contract to protect, and the
   *  price of that freedom is that its width is the view's to measure —
   *  `TopicQueue.browser.test.tsx` is where that is done. */
  primary: ReactNode
  /** What the row reports about itself — today a dispatch chip. Not a verb:
   *  it is read, not pressed, so it belongs on the side of the line that gives
   *  way rather than the side that is pinned.
   *
   *  Separate from `primary` because it arrived inside it, and that is what
   *  put an unbounded sentence in the pinned group: a failed dispatch's chip
   *  measured **708px** in a 294px line and pushed both verbs off the row. */
  note: ReactNode
  /** Verbs behind a menu.
   *
   *  **Verbs rather than `ReactNode`s, which is the change #40 forced.** They
   *  were nodes, rendered inline, and the row's own comment argued that "a
   *  menu holding a single item is a click in front of a button". That was
   *  true and cost 58px of a 294px line: the `Manage` button, plus its gap,
   *  is most of the reason the dispatch chip began past the clip edge and was
   *  not drawn at all. A `⋯` is 28px.
   *
   *  Nodes could not survive that move. `Menu`'s docstring is explicit that
   *  anything which is not a `MenuItem` falls outside the keyboard contract —
   *  Radix moves between `role="menuitem"` children and skips what it does
   *  not recognise, so a `<button>` handed in here would become a control
   *  neither the arrow keys nor Tab can reach. Describing the verb and
   *  letting the row render the item is what makes that unexpressible rather
   *  than merely discouraged. */
  overflow: readonly TopicVerb[]
}

/** A verb the row will render as a `MenuItem`.
 *
 * `onSelect` rather than `onClick` to match `MenuItem`, whose docstring
 * records that the two behave identically here and keeps `onSelect` because
 * it is the event a menu means.
 */
export interface TopicVerb {
  key: string
  label: string
  onSelect: () => void
  disabled?: boolean
  /** `danger` for a verb that destroys something. */
  tone?: 'danger'
}

/** The `Row` density: a uniform-height member of a scanned list.
 *
 * **Its defining property is that its height is a function of its kind, not of
 * its content**, and that is not decoration — it is the contract a virtualizer
 * relies on. L-F8 is what it costs when the contract is broken: measurements
 * cached against an array index "followed the wrong row and left a **122px
 * hole** at three projects". So this row clamps its question to one line
 * rather than wrapping, and carries no disclosure. A topic that needs to show
 * more than this is a `TopicDetail`, not a taller row.
 *
 * Extracted rather than invented: `TopicList.tsx:293` is already exactly this
 * component, already props-only, and merely not exported. What changes is that
 * its status goes through `EntityStatus` instead of a fourth
 * `.replace('_', ' ')`, its navigation is an `href` instead of an `onClick`,
 * and its verbs arrive as slots instead of two callbacks.
 */
export const TopicRow = ({
  topic,
  href,
  selected = false,
  slots = {},
}: {
  topic: TopicView
  href?: string | undefined
  selected?: boolean
  slots?: Partial<TopicRowSlots>
}) => {
  // The row is stateful for the first time, and only this. Open-ness belongs
  // here rather than to the queue because the queue would then hold a map
  // keyed by topic id and have to forget entries as rows come and go — state
  // about a row, kept somewhere a row's disappearance is not obvious.
  const [menuOpen, setMenuOpen] = useState(false)
  const verbs = slots.overflow ?? []

  return (
    <li
      className={clsx(
        'ent-topic-row',
        topic.isBlocked && 'is-blocked',
        !topic.isBlocked && topic.needsAttention && 'needs-attention',
        !topic.isBlocked && !topic.needsAttention && isClosed(topic) && 'is-closed',
        selected && 'is-selected',
      )}
      data-topic={topic.topicId}
      aria-current={selected ? 'true' : undefined}
    >
      {/* The question is the row's name and its link. A whole-row click target
        was considered and rejected: it makes the row's verbs harder to reach
        by keyboard, because every one of them then sits inside the link. */}
      <div className="ent-topic-question">
        {href === undefined ? topic.question : <a href={href}>{topic.question}</a>}
      </div>

      {/* Two groups, and which is which is the row's whole layout policy: what is
        read gives way, what is pressed does not. The line is narrower than its
        contents at rail width and always will be — 468px of content in 292px,
        measured — so the only question is what goes first, and a verb clipped
        off the right edge is still in the DOM and unreachable by mouse. */}
      <div className="ent-topic-meta">
        <div className="ent-topic-facts">
          {/* The note *replaces* the status rather than sitting beside it, and
            that is the other half of #40 — the half no amount of shaving
            reaches. At rail width the line holds 294px and its contents want
            468: with `Manage` behind a `⋯` the facts get 138px, of which the
            status word takes 100, and a 113px chip still does not fit. One of
            the two has to go.

            It is the status, for a reason `DispatchChip`'s own docstring had
            already written down while still rendering both: a topic whose
            dispatch failed is not a failed topic, and `✕ failed` beside
            `investigating` reads as two chips disagreeing about one fact.
            They answer the same question — what is happening to this topic —
            and the dispatch is the more recent and more specific answer.

            What is lost is real and is bounded: the status word, for as long
            as a dispatch chip is on the row. `blocked`, `flagged` and
            `closed` are drawn as the row's left border either way, the
            filter tabs above the list say which slice is on screen, and the
            detail says it in words. Nothing that is lost here is lost
            anywhere else. */}
          {slots.note ?? <EntityStatus status={topic.status} />}

          {/* Counts, not percentages, and each says what it counts. `findings` is
            an `int` here and `findingNotes` is a list of strings on the detail —
            two different fields the wire spells with two different keys, which a
            props contract mapping both onto `findings` would turn into a bug
            that typechecks.

            Last, so they are what the clip eats first. They are a scanning aid
            and every one of them is on the detail; the status is the row's
            identity and the note is what just happened to it. */}
          <span className="ent-topic-count">{topic.sources} sources</span>
          <span className="ent-topic-count">{topic.findings} findings</span>
          {topic.openSubQuestions > 0 ? (
            <span className="ent-topic-count">{topic.openSubQuestions} open</span>
          ) : null}
        </div>

        <div className="ent-topic-verbs">
          {slots.primary}
          {verbs.length > 0 ? (
            <Menu
              label={`More actions for ${topic.question}`}
              open={menuOpen}
              onOpenChange={setMenuOpen}
              trigger={<MenuTrigger aria-label={`More actions for ${topic.question}`} />}
            >
              {verbs.map((verb) => (
                <MenuItem
                  key={verb.key}
                  onSelect={verb.onSelect}
                  disabled={verb.disabled ?? false}
                  {...(verb.tone === undefined ? {} : { tone: verb.tone })}
                >
                  {verb.label}
                </MenuItem>
              ))}
            </Menu>
          ) : null}
        </div>
      </div>
    </li>
  )
}
