import clsx from 'clsx'
import { useCallback, useEffect, useRef, useState } from 'react'

import { useContainer } from '@app/container-context.tsx'
import { shortId } from '@domain/shared/identifier.ts'
import { sample } from '@domain/worker/transcript-tail.ts'

import { WorkerDrawer } from '../course/WorkerDrawer.tsx'
import { elapsed } from '../formatting/format.ts'
import { Overlay } from '../layout/OverlayHost.tsx'
import { useRunningAgents, type RunningAgent } from './use-running-agents.ts'

/** Where the open/closed choice is remembered.
 *
 * `PreferenceStore` is keyed by group and stores pane names, so this is one
 * pane in its own group rather than a new method on the port -- the session and
 * research views already remember a layout this way, and a second mechanism for
 * the same fact is how the two drift.
 *
 * The name recorded here means **open**, which is the opposite of what the
 * port's method is called, and that inversion is deliberate. The port's default
 * is an empty list; as a floating panel that read as *open*, which was tolerable
 * because the panel sat in the corner of its own accord. A popover hanging off
 * the nav is over the page content, so a default of open is the occlusion this
 * change exists to remove -- it would appear unbidden on the first load of every
 * fresh browser that had anything running. The cost is that a reader inspecting
 * `rt.collapsedPanes.agents` in devtools sees a name whose sense is reversed;
 * paid here rather than widening the port with a boolean for one control.
 * `stays shut on a console it has never been opened on` is what fails if the
 * default drifts back.
 */
const GROUP = 'agents'
const OPEN = 'popover'

/** What "actively running" resolves to.
 *
 * `Roster.workers` -- and nothing else. The server draws the line, not this
 * component: a `Worker` is a thing that is working, and `idleSessionIds` is a
 * separate field precisely so that "is anything running" is a length rather
 * than a filter (see `Roster`'s own docstring). A run, a dispatch, a turn and
 * an extraction all count, because all four are work a person started and may
 * be waiting on. A session that is merely *attached* to a project counts for
 * nothing, which is the distinction the count would lose if it were taken from
 * anywhere else.
 */
export const AgentWidget = () => {
  const { preferences } = useContainer()
  const [expanded, setExpanded] = useState(() => preferences.collapsedPanes(GROUP).includes(OPEN))
  const [watching, setWatching] = useState<RunningAgent | null>(null)
  const toggleRef = useRef<HTMLButtonElement>(null)
  const rootRef = useRef<HTMLDivElement>(null)
  const panelRef = useRef<HTMLDivElement>(null)

  const { agents, count, failed } = useRunningAgents(expanded)

  const setOpen = useCallback(
    (open: boolean) => {
      setExpanded(open)
      preferences.setCollapsedPanes(GROUP, open ? [OPEN] : [])
    },
    [preferences],
  )

  const close = useCallback(() => {
    setOpen(false)
    toggleRef.current?.focus()
  }, [setOpen])

  // Escape, outside-pointer dismissal and the guard on `watching` were all
  // here, in twenty lines, and are all deleted. The popover is an `Overlay`
  // now and the host owns every one of them.
  //
  // The guard is the interesting deletion, because it was *wrong* and the
  // stylesheet is what made it wrong. It read "with a feed open the drawer is
  // in front and owns Escape" -- true as a description of what should happen,
  // false as a description of what did: `.agents-panel` was `z-index: 40` and
  // `.drawer-backdrop` was `z-index: 20`, so this panel painted on top of the
  // dialog it had politely stood down for, stayed clickable, and had switched
  // off its own Escape handling. A component reasoning about what else is open
  // is the coupling that produced that; under the host there is nothing to
  // reason about, because a layer cannot see the layers around it.
  //
  // Still not a focus *trap*. This is a popover, not a modal -- the page
  // behind it stays usable on purpose, because the whole point is to watch
  // agents while doing something else. `modal` is left off for exactly that,
  // and `Drawer` (the feed opened from a row) sets it.

  // Focus lands in the popover on open, so a keyboard reader is not made to
  // tab through the rest of the topbar to reach what they just asked for. The
  // panel itself is the target rather than the first row: the rows re-order as
  // agents come and go, and focusing one would make that reordering move the
  // focus ring. It is `tabIndex={-1}` for that -- programmatic only, never a
  // tab stop of its own.
  useEffect(() => {
    if (!expanded) return
    // A button, not any row: an extraction's row is flat text with nothing to
    // open, and `focus()` on a div silently does nothing.
    const first = panelRef.current?.querySelector<HTMLElement>('button')
    ;(first ?? panelRef.current)?.focus()
  }, [expanded])

  // Nothing running and closed: draw nothing at all. It exists to surface
  // activity, and with none it has nothing to say -- so on an idle console,
  // which is most of the time, it takes no width in the topbar and the
  // breadcrumb gets it back. Open, it stays and says so, rather than vanishing
  // under the reader's cursor the moment the last agent finishes.
  if (!expanded && count === 0 && !failed) return null

  return (
    <>
      <div className="agents" data-open={expanded || undefined} ref={rootRef}>
        <button
          type="button"
          className="agents-toggle"
          ref={toggleRef}
          aria-expanded={expanded}
          aria-controls="agents-popover"
          // A real sentence, not the glyph. `Pane.tsx` announces its toggles
          // as "◂"/"▸", which tells a screen-reader user nothing about what
          // they control -- a known bug, and not one to spread.
          aria-label={`${label(count, failed)}. ${expanded ? 'Hide' : 'Show'} what is running.`}
          onClick={() => (expanded ? close() : setOpen(true))}
        >
          <span
            className={clsx(
              'agents-dot',
              failed ? 'agents-dot-unknown' : count > 0 && 'agents-dot-live',
            )}
            aria-hidden="true"
          />
          {/* Polite rather than assertive, and on the count alone: a person
              working in another part of the console should learn that a run
              finished, but not have a screen reader interrupt them for it.

              The numeral and the word are separate nodes so the word can go at
              420px, where the topbar's fixed items are close to filling it and
              the breadcrumb has already given up everything it has. The
              announcement narrows to "3" there, which is the fact that
              changed; the sentence is on the button and is never abbreviated.
              The failure state keeps its words at every width -- it is rare,
              and a lone "?" would say nothing. */}
          <span className="agents-count" aria-live="polite">
            {failed ? (
              'agents unknown'
            ) : (
              <>
                {count}
                <span className="agents-count-word"> running</span>
              </>
            )}
          </span>
        </button>
      </div>

      {/* The panel is a layer, so it is no longer a sibling of the toggle in
          the document -- it is portalled into the overlay host.

          **What that costs, stated because it is the one real regression.**
          Tab order followed the document, and the panel was placed after the
          toggle so a reader tabbed forwards into it. From the host it is at
          the end of the document instead, so Tab from the toggle continues
          into the page. That is why the focus effect below matters more than
          it did: focus is *moved* into the panel on open, so the reader gets
          there regardless of document order, and Escape returns it to the
          toggle. The remaining gap is Tab *out* of the last row, which now
          lands in the page rather than back on the toggle. Anchoring on the
          host would fix it properly; a `tabIndex` shuffle here would not.

          `anchor` is the toggle's own row, so a press on the toggle is not an
          "outside" press -- without it the pointerdown would close the panel
          and the click that follows would immediately reopen it. */}
      {expanded ? (
        <Overlay label="Agents running now" onDismiss={close} anchor={rootRef}>
          <div className="agents-panel" id="agents-popover" ref={panelRef} tabIndex={-1}>
            <div className="agents-rows">
              {agents.map((agent) => (
                <AgentRow
                  key={`${agent.projectId}:${agent.worker.ref}`}
                  agent={agent}
                  onOpen={() => setWatching(agent)}
                />
              ))}
              {agents.length === 0 ? (
                <p className="agents-quiet">
                  {failed ? 'Could not read what is running.' : 'Nothing is running right now.'}
                </p>
              ) : null}
            </div>
          </div>
        </Overlay>
      ) : null}

      {watching?.worker.sessionId ? (
        <WorkerDrawer
          sessionId={watching.worker.sessionId}
          heading={headingFor(watching)}
          onClose={() => setWatching(null)}
        />
      ) : null}
    </>
  )
}

const label = (count: number, failed: boolean): string => {
  if (failed) return 'agents unknown'
  return count === 1 ? '1 running' : `${count} running`
}

/** How the feed names the agent it is showing.
 *
 * `WorkerDrawer` alone titles itself `Watching 3f2a…`, which is the right name
 * when the reader arrived from a course page and already knows the project. A
 * reader arriving from this widget knows the agent as "the extraction in
 * atlas" and may not recognise any id on the screen.
 */
const headingFor = (agent: RunningAgent): string =>
  `${agent.worker.detail} · ${agent.projectName ?? shortId(agent.projectId)}`

/** One agent, on exactly one line, whatever the width.
 *
 * The hard part of this widget, and what each field is doing:
 *
 * - **the dot** is the only thing that survives every breakpoint. It is what a
 *   reader scans, and its colour is the worker's kind -- reusing the event-kind
 *   tokens the timeline already spends on the same four things, so liveness
 *   reads as the colour the log uses for it rather than one invented here.
 * - **kind and project** say what it is and whose it is. Monospace, so a
 *   column of them aligns and can be skimmed vertically.
 * - **elapsed** is the "is this stuck?" signal, and the reason a person opens
 *   this widget at all rather than reading a project page.
 * - **the statement** is the only flexible field: it takes all the slack and
 *   ellipsises. It is last to be dropped because it is the only thing here
 *   that says what the agent is actually doing.
 * - **the tool call** is dropped first, at 560px, because it is the field a
 *   reader can most often infer from the statement beside it.
 *
 * Elapsed goes next, at 420px. Nothing wraps and no row changes height,
 * because a widget that grows a row when an agent starts talking would move
 * every other row under the reader's cursor.
 */
const AgentRow = ({ agent, onOpen }: { agent: RunningAgent; onOpen: () => void }) => {
  const { worker, projectName, projectId, tail } = agent
  const since = elapsed(worker.startedAt)
  const say = sample(tail?.say ?? null)
  const tool = sample(tail?.tool ?? null)
  const where = projectName ?? shortId(projectId)

  // An extraction has no session of its own -- its detail view is the
  // extraction pane, not a transcript -- so its row is text rather than a
  // button that would open an empty drawer. Saying why in the title beats a
  // control that looks live and does nothing.
  const readable = worker.sessionId !== null

  const content = (
    <>
      <span className={`agents-kind agents-kind-${worker.kind}`} aria-hidden="true" />
      <span className="agents-what">{worker.kind}</span>
      <span className="agents-where">{where}</span>
      <span className="agents-since">{since}</span>
      {/* The flex item: `min-width: 0` is what actually lets it shrink below
          its content, and without it the row would push the tool call off the
          edge instead of ellipsising. */}
      <span className="agents-say">{say ?? worker.detail}</span>
      {tool ? <span className="agents-tool">{tool}</span> : null}
    </>
  )

  if (!readable) {
    return (
      <div className="agents-row agents-row-flat" title="This has no transcript to open.">
        {content}
      </div>
    )
  }

  return (
    <button
      type="button"
      className="agents-row"
      onClick={onOpen}
      // The visible row is a dozen fragments, several of them truncated. The
      // accessible name is the whole sentence instead, because a screen reader
      // reading the fragments in order gets the least useful version of it.
      aria-label={`${worker.kind} in ${where}, ${since || 'just started'}. ${
        say ?? worker.detail
      }${tool ? `. Last tool: ${tool}` : ''}. Open its feed.`}
    >
      {content}
    </button>
  )
}
