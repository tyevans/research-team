import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useCallback, useEffect, useId, useRef, useState } from 'react'

import { notify } from '@application/notifications/toast-store.ts'
import { errorMessage } from '@application/ports/errors.ts'
import { queryKeys } from '@application/queries/keys.ts'
import { useRunMediaCuration } from '@application/research/use-media-proposals.ts'
import { curationSummary } from '@domain/research/media-proposal.ts'
import { useContainer } from '@app/container-context.tsx'
import { statusLabel } from '@domain/entity/status.ts'
import { CLOSED_STATUSES, type TopicDetail, type TopicStatus } from '@domain/research/topic.ts'
import type { ProjectId } from '@domain/shared/identifier.ts'

import { Confirm } from '../common/Confirm.tsx'
import { Button } from '../common/primitives.tsx'
import { SubQuestions } from './SubQuestions.tsx'
import { TopicDocuments } from './TopicDocuments.tsx'

/** The statuses this build offers, in queue order rather than the wire's --
 *  a reader picking a next status wants "not pursuing"/"superseded" grouped
 *  apart from the live ones, the same split `byUrgency` makes for the list. */
const ALL_STATUSES: readonly TopicStatus[] = [
  'open',
  'investigating',
  'answered',
  'not_pursuing',
  'superseded',
]

/** Change a topic's status, with the sub-question breakdown alongside it.
 *
 * One panel rather than two, because both concerns act on the same
 * `TopicDetail` and closing one to open the other for a related edit would
 * cost a reader a click for no reason. Re-selecting the topic's own current
 * status is left off the choices entirely rather than offered and rejected
 * with the 409 the domain answers for a no-op transition -- a control that
 * is not there cannot be clicked by mistake, and there is nothing useful to
 * tell a user who tries to set a topic to what it already is.
 *
 * A justification is required to submit *any* status: the aggregate treats
 * an unexplained change as invalid (422 for blank or whitespace-only), so
 * the Save control mirrors that here rather than letting a submit round-trip
 * to the server just to be told no. Trimmed before both the disabled check
 * and the request, so three spaces do not count as an explanation either.
 *
 * ## What demodalising cost, and what it did not
 *
 * It was a `Drawer` -- an `Overlay` with `modal`, so the page behind it was
 * `inert`: unreachable to the pointer, the keyboard and a screen reader's
 * virtual cursor at once. Before that it hand-rolled a Tab trap of its own,
 * which `check-deleted.mjs` records as deleted, so what this change removes is
 * only the platform's confinement and not a keyboard contract anyone wrote.
 *
 * **What is genuinely lost is one thing: the page cannot take a click while a
 * half-written justification is on screen, and now it can.** A reader who
 * types two sentences and then clicks another topic's Manage loses them. That
 * is the reason the commit went behind a `Confirm` below rather than being
 * left as a bare button, and it is the trade this slice is making: modality
 * everywhere it was, in exchange for a topic you can read *beside* the queue
 * it came from, at a URL you can send.
 *
 * **Escape and focus return both had to be rewritten rather than deleted**,
 * because both meant something a non-modal region cannot mean:
 *
 * - Escape was the host's, given to the topmost layer only. There is no layer
 *   now, so it is a `document` listener that acts only on a key pressed inside
 *   this region -- see the effect below for why it is scoped that way rather
 *   than left on `window`, and why the containment test is written out rather
 *   than expressed as an `onKeyDown` in the markup.
 * - Focus return was unconditional, and had to be: nothing else was reachable,
 *   so focus at close time was always inside. Now a reader can tab out into
 *   the queue and leave this open, and yanking them back to the row they
 *   originally came from would be worse than doing nothing. So the restore is
 *   conditional on focus still being in here when it closes.
 *
 * Focus still moves *in* on open, which is a choice rather than an inheritance.
 * The pane renders below a queue that can be screens long, so a keyboard
 * reader who picked Manage out of a row's menu would otherwise have to find it
 * by tabbing. The cost is stated plainly: a page opened directly at
 * `#/p/<id>/topic/<tid>` moves focus off `<body>` once, after the detail read
 * resolves.
 */
export const TopicManagePane = ({
  projectId,
  topic,
  onClose,
}: {
  projectId: ProjectId
  topic: TopicDetail
  onClose: () => void
}) => {
  const { topics } = useContainer()
  const queryClient = useQueryClient()
  const justificationId = useId()
  const runCuration = useRunMediaCuration(projectId)

  const [chosen, setChosen] = useState<TopicStatus | null>(null)
  const [justification, setJustification] = useState('')
  /** Whether the commit is waiting on its confirmation. Separate from
   *  `chosen`, because a reader may pick a status, change their mind about the
   *  wording, and pick again without ever having reached the confirm. */
  const [confirming, setConfirming] = useState(false)

  const choices = ALL_STATUSES.filter((status) => status !== topic.status)

  const save = useMutation({
    mutationFn: () => {
      if (!chosen) throw new Error('no status chosen')
      return topics.setStatus(projectId, topic.topicId, chosen, justification.trim())
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.topic(projectId, topic.topicId) })
      void queryClient.invalidateQueries({ queryKey: queryKeys.topics(projectId) })
      setConfirming(false)
      onClose()
    },
    onError: (error) => {
      setConfirming(false)
      notify(errorMessage(error), 'bad')
    },
  })

  const canSave = chosen !== null && justification.trim().length > 0 && !save.isPending

  /** The region's own node, held through the unmount that reads it.
   *
   * A callback ref that ignores `null` rather than a plain `ref={}`, and the
   * distinction is load-bearing: React detaches refs top-down as it deletes a
   * subtree, so a `useRef` here would already be `null` by the time the close
   * button's ref (a descendant, detached second) asks whether focus was still
   * inside. Retaining the node costs nothing -- it is dropped with the
   * component -- and it is the only way that question can be asked at the
   * moment it has an answer.
   */
  const section = useRef<HTMLElement | null>(null)
  const sectionRef = useCallback((node: HTMLElement | null) => {
    if (node !== null) section.current = node
  }, [])

  /** Where focus was before this pane took it.
   *
   * Captured in the close button's callback ref rather than in an effect, for
   * the ordering reason `Drawer` sets out at length: React runs callback refs
   * during commit and effects after it, so an effect reading
   * `document.activeElement` records this pane's own button as "where the
   * reader came from" and the restore then targets a node that is being
   * removed. */
  const previouslyFocused = useRef<Element | null>(null)
  const focused = useRef(false)
  /** Whether focus was still inside this region at the moment it went away.
   *  Read in the cleanup below, which cannot ask the question itself. */
  const heldFocus = useRef(false)
  const closeButtonRef = useCallback((node: HTMLButtonElement | null) => {
    // Guarded so it fires once: a callback ref re-runs whenever React
    // re-attaches the node, and without the guard a re-render mid-read would
    // yank focus off whatever the reader had tabbed to and back onto Close.
    if (node && !focused.current) {
      focused.current = true
      previouslyFocused.current = document.activeElement
      node.focus()
      return
    }

    // Detach is the close, and it is where the *question* is answered rather
    // than where the answer is acted on. React clears callback refs during the
    // mutation phase, while this subtree is still in the document and still
    // holds focus if nobody moved it -- and that is the only moment
    // containment can be asked about at all, because a tick later the node is
    // gone and `contains` is false whatever the reader was doing.
    if (node === null && focused.current) {
      heldFocus.current = section.current?.contains(document.activeElement) ?? false
    }
  }, [])

  /** Escape, scoped to this region by where the key was pressed.
   *
   * On `document` rather than as an `onKeyDown` in the markup, and the reason
   * is `jsx-a11y/no-noninteractive-element-interactions`: a `<section>` with a
   * key handler is not an interactive element, the rule says so, and this file
   * has form here -- its own history records two suppressions that sat on
   * markup for exactly this reason and were deleted rather than argued with.
   * The containment test is what a handler in the markup was buying, so it is
   * written out instead of suppressed.
   *
   * Not `window` and not unconditional, which is the whole difference between
   * this and the defect `GraphDetail` shipped: the page behind is live now, so
   * an Escape pressed on the queue, the header or another region has nothing
   * to do with this panel. It also excludes the save confirmation for free --
   * `Confirm` is an `Overlay` and renders into the host, so its DOM is outside
   * this section however close it looks on screen, and the host gives Escape
   * to the topmost layer. A React `onKeyDown` would *not* have got that right:
   * React bubbles portal events along the component tree, so the confirm's
   * Escape would have arrived here and closed both.
   */
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return
      if (!(event.target instanceof Node) || !section.current?.contains(event.target)) return
      onClose()
    }
    document.addEventListener('keydown', onKeyDown)
    return () => document.removeEventListener('keydown', onKeyDown)
  }, [onClose])

  /** ...and this is where it is acted on, one phase later.
   *
   * **A `focus()` call made during the mutation phase does not survive the
   * commit**, and this cost an hour to find because it looks like it works:
   * `document.activeElement` is the restored element on the next line, and is
   * the reader's own element again by the time any assertion can run. React
   * captures the focused element before mutating the DOM and restores it
   * afterwards -- the mechanism that keeps focus alive across a re-render that
   * replaces a node -- so it faithfully undid this. It is invisible in the
   * closing-by-Close case, because there the focused element is the button
   * being removed and React has nothing to restore, which is exactly the case
   * every test covered before there was a second one.
   *
   * A passive unmount cleanup runs after that restoration, so a `focus()` here
   * is the last word. `OverlayHost` reached the same place from the other
   * direction and its comment says so: the restore has to be owned by
   * something that knows when the commit is over. */
  useEffect(
    () => () => {
      const target = previouslyFocused.current
      if (heldFocus.current && target instanceof HTMLElement && target.isConnected) target.focus()
    },
    [],
  )

  return (
    /* A `<section>` with a name rather than a `role="dialog"`, which is the
       whole of the demodalisation as far as assistive technology is concerned:
       a region is announced as a landmark a reader can navigate to and out of,
       where a dialog announces something they are held inside. The name is
       "Manage <question>" for the reason it was the drawer's `label` -- the
       question alone does not say that this is the thing that changes it. */
    <section
      ref={sectionRef}
      aria-label={`Manage ${topic.question}`}
      className="mt-[16px] flex flex-col border-0 border-t border-solid border-line pt-[12px]"
    >
      <header className="mb-[8px] flex items-center gap-[8px]">
        <h3 className="font-semibold m-0 text-sm">{topic.question}</h3>
        <span className="flex-auto" />
        <button type="button" className="btn btn-sm" ref={closeButtonRef} onClick={onClose}>
          Close
        </button>
      </header>

      <div className="mb-[8px] text-sm text-fg-dim">
        Currently <strong>{statusLabel(topic.status)}</strong>
        {CLOSED_STATUSES.includes(topic.status) ? ' -- reopening is allowed.' : ''}
      </div>

      <div className="mb-[10px] flex flex-wrap gap-[6px]">
        {choices.map((status) => (
          <button
            key={status}
            type="button"
            className="btn btn-sm"
            // The only mark of the choice: `.btn[aria-pressed='true']` in
            // `shell.css` draws the pressed look, so a class saying the same
            // thing is a second place to forget.
            aria-pressed={chosen === status}
            onClick={() => setChosen(status)}
          >
            {statusLabel(status)}
          </button>
        ))}
      </div>

      <label htmlFor={justificationId}>Justification</label>
      {/* `resize-y` rather than the `resize: vertical` the rule spelled: the
          two are the same declaration, and `min-h-[4.5em]` is `em` because the
          field is sized in lines of its own text rather than in pixels. */}
      <textarea
        id={justificationId}
        className="input mx-0 mt-[4px] mb-[10px] block min-h-[4.5em] w-full resize-y"
        value={justification}
        onChange={(event) => setJustification(event.target.value)}
        placeholder="why this change"
      />

      <div className="mb-[16px]">
        {/* Opens the confirmation rather than mutating, and this is the one
            control the demodalisation changed. A status change writes the
            project's audit trail and cannot be undone from this pane; while
            this was a modal, a stray click could not reach it from anywhere
            else on the page, and now it can. The extra click is the cost and
            is charged only here, on the irreversible action, rather than by
            making the whole panel a dialog again. */}
        <Button tone="accent" disabled={!canSave} onClick={() => setConfirming(true)}>
          {save.isPending ? 'Saving…' : 'Save'}
        </Button>
      </div>

      {confirming && chosen !== null ? (
        <Confirm
          heading={`Change this topic to ${statusLabel(chosen)}?`}
          lines={[
            // The justification is quoted back rather than described, because
            // it is the thing being written down and the last moment anyone
            // can read it before it becomes a fact about the project.
            `Recorded as: “${justification.trim()}”`,
            'The change and its justification are added to the topic’s audit trail.',
          ]}
          confirmLabel={`Set to ${statusLabel(chosen)}`}
          onCancel={() => setConfirming(false)}
          onConfirm={() => save.mutate()}
        />
      ) : null}

      <SubQuestions projectId={projectId} topic={topic} />

      {/* The chain's only trigger anywhere in the product -- see
          `MediaCurationService.curate`/`run_media_curation`. Placed here
          rather than in `MediaProposalPane` because the chain needs a topic
          and this is the one place a topic is already in scope; the pane's
          own empty state ("Run the media curation chain from a topic...")
          points here. */}
      <section className="mt-[16px] border-0 border-t border-solid border-line pt-[12px]">
        <h3 className="font-medium m-0 mb-[8px] font-mono text-xs tracking-[0.06em] text-fg-faint uppercase">
          Media
        </h3>
        <Button
          tone="ghost"
          disabled={runCuration.isPending}
          onClick={() =>
            runCuration.mutate(topic.topicId, {
              onSuccess: (outcome) => notify(curationSummary(outcome)),
              onError: (error) => notify(errorMessage(error), 'bad'),
            })
          }
        >
          {runCuration.isPending ? 'Searching for media…' : 'Find media for this topic'}
        </Button>
      </section>

      {/* Last, and inside this panel rather than as a fifth pane: what a
          dispatch wrote is the answer to the question this topic asks, so it
          belongs behind the topic rather than beside the graph. That this
          section arrives late and grows used to matter to the Tab trap this
          file once held, which re-queried its focusable children per keypress
          to keep up; nothing traps anything now, so a body that grows is not a
          thing anyone has to keep track of. */}
      <section className="mt-[16px] border-0 border-t border-solid border-line pt-[12px]">
        {/* `.topic-section-heading`'s rule, per branch and whole: the mono
            face, the 10.5px, the 0.06em tracking and the faint tone all
            travelled together and none of them is a default. */}
        <h3 className="font-medium m-0 mb-[8px] font-mono text-xs tracking-[0.06em] text-fg-faint uppercase">
          Documents
        </h3>
        <TopicDocuments projectId={projectId} topicId={topic.topicId} />
      </section>
    </section>
  )
}
